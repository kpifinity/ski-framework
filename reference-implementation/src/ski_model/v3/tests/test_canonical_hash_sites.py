"""Runtime hash sites computed with the spec §7.3 canonicalizer.

``kg_version_hash``, ``structured_grammar_hash`` and the ledger's
``telemetry_hash`` are all digests of ``ski_schemas.canonical`` output, so a
non-Python implementation reproduces them from the contracts alone. The
ledger's ``telemetry_hash`` is also the buffer row's ``measurement_hash``:
that shared value is what deterministic replay joins on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from ski_schemas.canonical import CanonicalizationError, canonicalize, sha256_canonical
from ski_schemas.measurement import MeasurementRecord

from ski_model import server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import RESPONSE_GRAMMAR, STRUCTURED_GRAMMAR_HASH

from .test_endpoint import _install_test_state


class _RecordingBuffer:
    """Telemetry-buffer double that records appends and has no samples."""

    def __init__(self) -> None:
        self.appended: List[Dict[str, Any]] = []

    async def append(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)

    async def window_query(self, **_: Any) -> Any:
        return []


def _kg(rules: List[Dict[str, Any]], tag_registry: Dict[str, str]) -> KnowledgeGraph:
    return KnowledgeGraph(
        version="hash-sites-1",
        rules=rules,
        tag_registry=tag_registry,
        metadata={"version": "hash-sites-1"},
        signature_verified=True,
    )


def _payload(measurement: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "measurement_id": "hash-sites-001",
        "timestamp": "2026-01-15T12:00:00Z",
        "subject": "emissions",
        "measurement": measurement,
    }


# ---- structured_grammar_hash ----------------------------------------------------


def test_structured_grammar_hash_is_the_canonical_digest() -> None:
    assert sha256_canonical(RESPONSE_GRAMMAR) == STRUCTURED_GRAMMAR_HASH


def test_structured_grammar_hash_is_unchanged_from_3_2_0() -> None:
    # The grammar has no floats and only NFC strings, so the §7.3 bytes equal
    # the sorted-keys json.dumps it was hashed with before: the value
    # existing envelopes carry still identifies the same grammar.
    legacy = json.dumps(RESPONSE_GRAMMAR, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert "sha256:" + hashlib.sha256(legacy).hexdigest() == STRUCTURED_GRAMMAR_HASH


# ---- kg_version_hash ------------------------------------------------------------


def test_kg_version_hash_is_the_canonical_digest() -> None:
    rules: List[Dict[str, Any]] = [
        {"id": "r1", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
    ]
    kg = _kg(rules, {"emissions": "r1"})
    expected = sha256_canonical(
        {"version": "hash-sites-1", "rules": rules, "tag_registry": {"emissions": "r1"}}
    )
    assert server._compute_kg_version_hash(kg) == expected


def test_kg_version_hash_numbers_follow_rfc_8785() -> None:
    def rule(value: float) -> List[Dict[str, Any]]:
        return [{"id": "r1", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": value}]

    # 100.0 and 100 are the same JSON number; json.dumps wrote "100.0" vs "100".
    assert server._compute_kg_version_hash(_kg(rule(100.0), {})) == server._compute_kg_version_hash(
        _kg(rule(100), {})
    )


def test_kg_version_hash_refuses_a_kg_with_no_canonical_form() -> None:
    rules: List[Dict[str, Any]] = [
        {"id": "r1", "metric": "x", "predicate": "must_not_exceed", "value": 2**53 + 1}
    ]
    with pytest.raises(CanonicalizationError):
        server._compute_kg_version_hash(_kg(rules, {}))


# ---- telemetry_hash -------------------------------------------------------------


def test_ledger_telemetry_hash_is_the_buffer_measurement_hash() -> None:
    ledger = _install_test_state()
    buffer = _RecordingBuffer()
    server.state.telemetry_buffer = buffer
    try:
        response = TestClient(server.app).post("/api/evaluate", json=_payload({"so2_ppm": 42.5}))
    finally:
        server.state.telemetry_buffer = None
    assert response.status_code == 200, response.text

    record = MeasurementRecord.model_validate(_payload({"so2_ppm": 42.5}))
    expected = hashlib.sha256(canonicalize(record.model_dump())).hexdigest()
    assert len(ledger.appended) == 1 and len(buffer.appended) == 1
    assert ledger.appended[0]["telemetry_hash"] == expected
    assert buffer.appended[0]["measurement_hash"] == expected


def test_telemetry_hash_does_not_escape_non_ascii() -> None:
    record = MeasurementRecord.model_validate(
        {**_payload({"so2_ppm": 1}), "subject": "Schwefeldioxid-Messstelle-ü"}
    )
    assert server._hash_measurement(record) == hashlib.sha256(canonicalize(record.model_dump())).hexdigest()
    assert "ü".encode() in canonicalize(record.model_dump())


def test_measurement_with_no_canonical_form_is_422_and_never_reaches_ledger_or_buffer() -> None:
    ledger = _install_test_state()
    buffer = _RecordingBuffer()
    server.state.telemetry_buffer = buffer
    try:
        # 2**53 + 1 is inside the double *range* (so it passes the non-finite
        # check) but a double cannot hold it exactly: it has no §7.3 form.
        response = TestClient(server.app).post("/api/evaluate", json=_payload({"so2_ppm": 2**53 + 1}))
    finally:
        server.state.telemetry_buffer = None
    assert response.status_code == 422, response.text
    assert "canonical JSON" in response.json()["detail"]
    assert ledger.appended == []
    assert buffer.appended == []
