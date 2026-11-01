"""Standards-native evidence: SCITT statements + receipts, TRACE records, the CycloneDX ML-BOM."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi.testclient import TestClient
from ski_schemas.merkle import merkle_root
from ski_schemas.scitt import verify_transparent_statement
from ski_schemas.trace import EAT_PROFILE, verify_record

from ski_model import server
from ski_model.evidence import ledger_evidence
from ski_model.mlbom import ml_bom
from ski_model.v3.signing import TranscriptSigner

from .test_endpoint import _install_test_state

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _signer() -> TranscriptSigner:
    key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"evidence-test").digest())
    return TranscriptSigner(key, key.public_key())


def _hashes(n: int) -> list[str]:
    return [hashlib.sha256(f"entry-{i}".encode()).hexdigest() for i in range(1, n + 1)]


def _evidence(seq: int = 3, covered: Optional[int] = 4) -> dict[str, Any]:
    hashes = _hashes(max(seq, covered or 0))
    return {
        "entry": {
            "sequence_number": seq,
            "entry_hash": hashes[seq - 1],
            "previous_hash": hashes[seq - 2] if seq > 1 else "0" * 64,
            "timestamp": "2026-11-01T11:59:00+00:00",
            "tenant_id": "plant-7",
            "verdict": "FLAG",
            "telemetry_id": "m-3",
            "telemetry_hash": "f" * 64,
            "rule_id": "energy.so2.cap",
            "kg_version_hash": "sha256:" + "1" * 64,
            "model_weight_hash": "sha256:" + "2" * 64,
            "schema_version": "3.0.0",
            "verifier_status": "LLM_CONTRADICTION",
            "envelope_json": {
                "verdict": "FLAG",
                "model_provenance": {
                    "backend": "vllm-v3",
                    "model_id": "qwen",
                    "model_weight_hash": "sha256:" + "2" * 64,
                    "kg_version_hash": "sha256:" + "1" * 64,
                    "runtime_version": "3.3.0",
                },
            },
            "transcript_json": {"transcript_id": "t-3", "request_hash": "sha256:" + "a" * 64},
        },
        "checkpoint_hashes": hashes[:covered] if covered else None,
    }


def _verify_fn(signer: TranscriptSigner) -> Any:
    key = serialization.load_pem_public_key(signer.public_key_pem.encode())
    assert isinstance(key, Ed25519PublicKey)

    def verify(signature: bytes, message: bytes) -> bool:
        try:
            key.verify(signature, message)
        except InvalidSignature:
            return False
        return True

    return verify


def _evidence_doc(**kwargs: Any) -> dict[str, Any]:
    return ledger_evidence(
        _evidence(**kwargs),
        signer=_signer(),
        strict=True,
        kg_version="kg-2026.11",
        data_class="regulated-telemetry",
        image_digest="sha256:" + "9" * 64,
        codebase_commit="abc123",
        now=_NOW,
    )


def test_transparent_statement_verifies_and_its_receipt_root_is_the_checkpoint_root() -> None:
    doc = _evidence_doc()
    payload, roots = verify_transparent_statement(
        base64.b64decode(doc["scitt"]["transparent_statement"]), _verify_fn(_signer())
    )
    assert payload["ledger_entry"]["sequence_number"] == 3
    assert payload["envelope"]["verdict"] == "FLAG"
    assert roots == [(bytes.fromhex(merkle_root(_hashes(4))), 4)]
    assert doc["scitt"]["receipt_tree_size"] == 4


def test_a_generic_cose_verifier_accepts_the_statement_and_receipt() -> None:
    doc, signer = _evidence_doc(), _signer()
    key = serialization.load_pem_public_key(signer.public_key_pem.encode())
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    _cose_verify(base64.b64decode(doc["scitt"]["signed_statement"]), raw)
    _cose_verify(
        base64.b64decode(doc["scitt"]["receipt"]), raw, detached=bytes.fromhex(merkle_root(_hashes(4)))
    )


def _cose_verify(message: bytes, raw_key: bytes, detached: Optional[bytes] = None) -> dict[Any, Any]:
    """Verify a COSE_Sign1 independently of ski_schemas.cose: cbor2 decodes it and builds RFC 9052's
    Sig_structure; raises on a bad signature. Returns the protected header."""
    import cbor2
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Key

    tagged = cbor2.loads(message)
    assert tagged.tag == 18, "not a tagged COSE_Sign1"
    protected, _unprotected, payload, signature = tagged.value
    header = cbor2.loads(protected)
    assert header[1] == -8, "not EdDSA"
    to_be_signed = cbor2.dumps(["Signature1", protected, b"", payload if payload is not None else detached])
    _Key.from_public_bytes(raw_key).verify(signature, to_be_signed)
    return dict(header)


def test_no_receipt_until_a_checkpoint_covers_the_entry() -> None:
    doc = _evidence_doc(covered=None)
    assert doc["scitt"]["receipt"] is None and doc["scitt"]["receipt_tree_size"] is None
    _, roots = verify_transparent_statement(
        base64.b64decode(doc["scitt"]["transparent_statement"]), _verify_fn(_signer())
    )
    assert roots == []
    assert doc["trace_record"]["transparency"]["receipt_uri"] is None


def test_trace_record_is_signed_and_maps_the_verdict() -> None:
    record = _evidence_doc()["trace_record"]

    def verify(raw_key: bytes, signature: bytes, message: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, message)
        except InvalidSignature:
            return False
        return True

    assert verify_record(record, verify)
    assert record["eat_profile"] == EAT_PROFILE and record["iat"] == int(_NOW.timestamp())
    assert record["subject"] == "ski:ledger:plant-7:3"
    assert record["model"]["weights_digest"] == "sha256:" + "2" * 64
    assert record["policy"] == {
        "bundle_hash": "sha256:" + "1" * 64,
        "enforcement_mode": "enforce",
        "version": "kg-2026.11",
    }
    assert record["appraisal"]["status"] == "contraindicated"  # the verifier caught the LLM
    assert record["runtime"]["platform"] == "software-only"
    tampered = {**record, "data_class": "public"}
    assert not verify_record(tampered, verify)


def _bom() -> dict[str, Any]:
    return ml_bom(
        runtime_version="3.3.0",
        image_digest="sha256:" + "9" * 64,
        codebase_commit="abc123",
        backend={
            "backend": "vllm-v3",
            "model_id": "Qwen/Qwen2.5-7B-Instruct",
            "model_weight_hash": "sha256:" + "2" * 64,
            "model_hash_verified": True,
            "model_hash_source": "verified-file-digest",
        },
        model_signature={"signer_key_id": "sha256:" + "4" * 64, "root_digest": "sha256:" + "5" * 64},
        kg={
            "name": "energy",
            "version": "kg-1",
            "kg_version_hash": "sha256:" + "1" * 64,
            "kg_trust": "anchored",
        },
        now=_NOW,
    )


def test_ml_bom_is_valid_cyclonedx_1_6() -> None:
    validation = pytest.importorskip("cyclonedx.validation.json")
    from cyclonedx.schema import SchemaVersion

    errors = validation.JsonStrictValidator(SchemaVersion.V1_6).validate_str(json.dumps(_bom()))
    assert errors is None, errors


def test_ml_bom_describes_the_model_and_kg() -> None:
    bom = _bom()
    model, kg = bom["components"]
    assert model["type"] == "machine-learning-model"
    assert model["hashes"] == [{"alg": "SHA-256", "content": "2" * 64}]
    assert {"name": "ski:model_hash_verified", "value": "true"} in model["properties"]
    assert {"name": "ski:model_signature_signer", "value": "sha256:" + "4" * 64} in model["properties"]
    assert kg["type"] == "data" and kg["hashes"] == [{"alg": "SHA-256", "content": "1" * 64}]
    assert bom["serialNumber"] == _bom()["serialNumber"]  # content-derived, stable


class _EvidenceLedger:
    format5 = True
    tenant_id = "plant-7"
    signer = None

    async def evidence(self, sequence_number: int) -> Optional[dict[str, Any]]:
        return _evidence(seq=sequence_number) if sequence_number <= 4 else None


def test_evidence_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_test_state()
    saved = (server.state.ledger, server.state.transcript_signer)
    server.state.ledger = _EvidenceLedger()  # type: ignore[assignment]
    server.state.transcript_signer = _signer()
    try:
        client = TestClient(server.app)
        ok = client.get("/api/ledger/2/evidence")
        missing = client.get("/api/ledger/9/evidence")
        server.state.ledger.format5 = False  # type: ignore[union-attr]
        unmigrated = client.get("/api/ledger/2/evidence")
        bom = client.get("/api/mlbom")
    finally:
        server.state.ledger, server.state.transcript_signer = saved
        _EvidenceLedger.format5 = True
    assert ok.status_code == 200 and ok.json()["sequence_number"] == 2
    assert missing.status_code == 404 and unmigrated.status_code == 409
    assert bom.status_code == 200 and bom.json()["bomFormat"] == "CycloneDX"
