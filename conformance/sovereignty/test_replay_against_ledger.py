"""Spec §8.1 — deterministic replay of v3 ledger entries against a live ledger.

Entries are written by the runtime's own ``/api/evaluate`` handler into a
Postgres provisioned from the shipped SQL, then ``audit-ledger replay``
re-runs each one from its signed transcript and must reproduce the recorded
verdict and verifier status. Replay against the wrong KG, or a buffer row
that no longer matches the transcript, must be reported, not passed.

Requires ``SKI_L3_LEDGER_DSN`` (a throwaway Postgres; destructive).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

DSN = os.environ.get("SKI_L3_LEDGER_DSN")
REPO = Path(__file__).resolve().parent.parent.parent
LEDGER_SQL = REPO / "reference-implementation" / "src" / "ledger"
_RUNTIME_SRC = str(REPO / "reference-implementation" / "src")
if _RUNTIME_SRC not in sys.path:
    sys.path.insert(0, _RUNTIME_SRC)

pytestmark = pytest.mark.sovereignty

_AS_OF = "2026-06-15T12:00:00Z"

# (measurement_id, measurement, expected verdict)
_WORKLOAD = [
    ("replay-001", {"so2_ppm": 85}, "CLEAR"),
    ("replay-002", {"so2_ppm": 142}, "FLAG"),
    ("replay-003", {"co2_ppm": 410}, "NULL_UNMAPPED"),
    ("replay-004", {"pm25_ppm": 12}, "CLEAR"),  # freshness-gated: needs the buffer
]


def _obligation(ob_id: str, metric: str, limit: int, **extra: Any) -> Dict[str, Any]:
    return {
        "id": ob_id,
        "type": "Obligation",
        "version": "r-1",
        "obligation_type": "must_not_exceed",
        "metric": metric,
        "value": limit,
        "effective_date_start": "2026-01-01T00:00:00Z",
        **extra,
    }


def _graph(so2_limit: int = 100) -> Dict[str, Any]:
    obligations = [
        _obligation("ob.so2", "so2_ppm", so2_limit),
        _obligation("ob.pm25", "pm25_ppm", 35, requires_recent_within_seconds=600),
    ]
    return {
        "metadata": {"name": "Replay conformance KG", "schema_version": "3.0", "version": "replay-1"},
        "nodes": {
            "rules": [
                {"id": "r.air", "type": "Rule", "version": "r-1", "name": "Air", "risk_tier": "medium"}
            ],
            "obligations": obligations,
        },
        "edges": [{"type": "consists_of", "from": "r.air", "to": ob["id"]} for ob in obligations],
    }


def _write_signed(path: Path, graph: Dict[str, Any], key: Any) -> None:
    from cryptography.hazmat.primitives import serialization
    from ski_model.kg_loader import signing_bytes

    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signed = {
        **graph,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": pem.decode("ascii"),
            "value_hex": key.sign(signing_bytes(graph)).hex(),
        },
    }
    path.write_text(json.dumps(signed), encoding="utf-8")


@pytest.fixture(scope="module")
def ledger(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """A fresh ledger holding the workload, written by /api/evaluate; returns paths and DSN."""
    if not DSN:
        pytest.skip("SKI_L3_LEDGER_DSN not set; the replay rig needs a throwaway Postgres.")
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ski_model import server
    from ski_model.kg_loader import KGTrustPolicy, TrustAnchor, load_signed_kg
    from ski_model.ledger_client import LedgerClient
    from ski_model.v3 import FakeLLM, V3Evaluator
    from ski_model.v3.signing import TranscriptSigner
    from ski_schemas.measurement import MeasurementRecord

    engine = sqlalchemy.create_engine(DSN)
    with engine.begin() as cx:
        cx.exec_driver_sql("DROP TABLE IF EXISTS telemetry_buffer, tenants, ledger_entries CASCADE")
        for name in (
            "schema.sql",
            "append_only.sql",
            "migrations/0002_transcript_columns.sql",
            "telemetry_buffer.sql",
        ):
            cx.exec_driver_sql((LEDGER_SQL / name).read_text(encoding="utf-8").replace("%", "%%"))
    engine.dispose()

    workdir = tmp_path_factory.mktemp("replay")
    kg_key = Ed25519PrivateKey.generate()
    anchors = workdir / "anchors.pem"
    anchors.write_bytes(
        kg_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    kg_path, wrong_kg_path = workdir / "kg.json", workdir / "kg-other.json"
    _write_signed(kg_path, _graph(), kg_key)
    _write_signed(wrong_kg_path, _graph(so2_limit=150), kg_key)
    policy = KGTrustPolicy(anchors=(TrustAnchor.from_public_key(kg_key.public_key()),))

    async def _write() -> None:
        kg = load_signed_kg(kg_path, require_signature=True, trust=policy)
        signing_key = Ed25519PrivateKey.generate()
        client = LedgerClient(DSN)
        await client.initialize()
        assert client._engine is not None
        state = server.state
        state.knowledge_graph = kg
        state.kg_version_hash = server._compute_kg_version_hash(kg)
        state.ledger = client
        state.evaluator = V3Evaluator(
            llm=FakeLLM(),
            kg_version_hash=state.kg_version_hash,
            decoder_seed=0,
            signer=TranscriptSigner(signing_key, signing_key.public_key()),
        )
        state.telemetry_buffer = await server._init_telemetry_buffer(client._engine, "default")
        assert state.telemetry_buffer is not None
        state.tenant_id, state.max_clock_skew_seconds = "default", 0
        state.egress_guard = state.agreement_monitor = state.tag_registry = None
        try:
            for measurement_id, measurement, expected in _WORKLOAD:
                envelope = await server.evaluate(
                    MeasurementRecord(
                        measurement_id=measurement_id,
                        timestamp=_AS_OF,
                        subject=f"stack.{next(iter(measurement))}",
                        measurement=measurement,
                    )
                )
                assert str(getattr(envelope.verdict, "value", envelope.verdict)) == expected, measurement_id
            # One entry the model never sees: the clock-skew guard path (no transcript).
            state.max_clock_skew_seconds = 60
            await server.evaluate(
                MeasurementRecord(
                    measurement_id="replay-skewed",
                    timestamp=_AS_OF,
                    subject="stack.so2",
                    measurement={"so2_ppm": 1},
                )
            )
        finally:
            state.ledger = state.evaluator = state.telemetry_buffer = state.knowledge_graph = None
            await client.close()

    asyncio.run(_write())
    return {"kg": str(kg_path), "wrong_kg": str(wrong_kg_path), "anchors": str(anchors)}


def _replay(ledger: Dict[str, Any], monkeypatch: pytest.MonkeyPatch, kg_key: str = "kg") -> Any:
    from audit_ledger.replay import replay

    monkeypatch.setenv("SKI_KG_TRUST_ANCHORS", ledger["anchors"])
    assert DSN is not None
    return replay(dsn=DSN, from_sequence=1, to_sequence=10**9, kg_path=ledger[kg_key])


def _reasons(report: Any) -> List[str]:
    return [m.reason for m in report.mismatches]


def test_replay_reproduces_every_model_evaluated_entry(
    ledger: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _replay(ledger, monkeypatch)
    assert report.total_entries == len(_WORKLOAD) + 1
    assert report.replayed_entries == len(_WORKLOAD), report.notes
    assert report.matched_entries == len(_WORKLOAD), report.to_dict()
    assert report.skipped_entries == 1 and any("no transcript" in n for n in report.notes)
    assert report.is_clean


def test_replay_against_a_different_kg_is_reported(
    ledger: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _replay(ledger, monkeypatch, kg_key="wrong_kg")
    assert not report.is_clean
    assert set(_reasons(report)) == {"kg_version_mismatch"}


def test_buffer_row_that_no_longer_matches_the_transcript_is_reported(
    ledger: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlalchemy = pytest.importorskip("sqlalchemy")
    engine = sqlalchemy.create_engine(DSN)
    with engine.begin() as cx:  # the superuser attack: disable the append-only triggers, edit a reading
        cx.exec_driver_sql("ALTER TABLE telemetry_buffer_default DISABLE TRIGGER USER")
        cx.exec_driver_sql(
            "UPDATE telemetry_buffer_default SET measurement = '{\"so2_ppm\": 99}' WHERE telemetry_id = 'replay-002'"
        )
        cx.exec_driver_sql("ALTER TABLE telemetry_buffer_default ENABLE TRIGGER USER")
    engine.dispose()
    report = _replay(ledger, monkeypatch)
    assert _reasons(report) == ["telemetry_divergence"]
    assert report.mismatches[0].telemetry_id == "replay-002"
