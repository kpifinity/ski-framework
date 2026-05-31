"""Integration tests for the v3 /api/evaluate endpoint.

The full server lifespan touches a Knowledge Graph file, a database engine,
and a background canary task — none of which we want CI to depend on. These
tests therefore:

  * Set environment to disable the API key requirement.
  * Patch :class:`ski_model.server.state` with hand-rolled in-memory
    substitutes (KG, evaluator, ledger).
  * Drive the FastAPI handler directly via :class:`fastapi.testclient.TestClient`.

What we cover:

  * /api/evaluate returns a fully formed V3VerdictEnvelope on a known
    CLEAR-path measurement.
  * The response shape validates against the V3VerdictEnvelope model.
  * /api/health reports runtime_version="v3".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _enable_no_auth_mode() -> None:
    """Disable the API-key requirement BEFORE importing the server module."""
    os.environ["API_KEY_REQUIRED"] = "false"
    os.environ["SKI_V3_LLM_BACKEND"] = "fake"


_enable_no_auth_mode()

# Import AFTER the env vars are set so the module-level constants pick them up.
from fastapi.testclient import TestClient  # noqa: E402

from ski_model import server  # noqa: E402
from ski_model.kg_loader import KnowledgeGraph  # noqa: E402
from ski_model.v3 import FakeLLM, V3Evaluator, V3VerdictEnvelope  # noqa: E402


# ---- In-memory test doubles ---------------------------------------------------


@dataclass
class _FakeLedger:
    appended: List[Dict[str, Any]]

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def append(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)

    async def list(self, *, limit: int, offset: int) -> List[Dict[str, Any]]:
        return self.appended[offset : offset + limit]


def _build_test_kg() -> KnowledgeGraph:
    return KnowledgeGraph(
        version="v3test-0001",
        rules=[
            {
                "id": "energy.so2.lte_100ppm",
                "metric": "so2_ppm",
                "predicate": "must_not_exceed",
                "value": 100,
            }
        ],
        tag_registry={"emissions": "energy.so2.lte_100ppm"},
        metadata={"version": "v3test-0001"},
        signature_verified=True,
    )


def _install_test_state() -> _FakeLedger:
    """Inject in-memory test doubles into server.state."""
    kg = _build_test_kg()
    ledger = _FakeLedger(appended=[])
    fake_llm = FakeLLM()
    evaluator = V3Evaluator(
        llm=fake_llm,
        kg_version_hash="sha256:" + "c" * 64,
        decoder_seed=0,
    )

    server.state.knowledge_graph = kg
    server.state.ledger = ledger  # type: ignore[assignment]
    server.state.llm_backend = fake_llm
    server.state.evaluator = evaluator
    server.state.canary = None  # the /api/health handler tolerates this
    server.state.tag_registry = None
    server.state.telemetry_buffer = None
    server.state.tenant_id = "tenant.test"
    server.state.verdicts_produced = 0
    server.state.kg_version_hash = evaluator.kg_version_hash
    return ledger


# ---- Tests --------------------------------------------------------------------


def _measurement_payload(value: int) -> Dict[str, Any]:
    return {
        "measurement_id": f"meas-{value}",
        "timestamp": "2026-01-15T12:00:00Z",
        "subject": "emissions",
        "measurement": {"so2_ppm": value},
        "risk_tier": "standard",
    }


def test_health_reports_v3_runtime() -> None:
    _install_test_state()
    with TestClient(server.app) as client:
        # Bypass the lifespan-driven init by re-installing state inside the
        # context (TestClient triggers lifespan, which would otherwise reset).
        _install_test_state()
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runtime_version"] == "v3"
    assert body["kg_loaded"] is True


def test_evaluate_returns_clear_envelope_for_compliant_measurement() -> None:
    _install_test_state()
    with TestClient(server.app) as client:
        _install_test_state()
        resp = client.post("/api/evaluate", json=_measurement_payload(50))
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "CLEAR"
    assert envelope.reasoning
    assert len(envelope.kg_citations) == 1
    assert envelope.kg_citations[0].node_id == "energy.so2.lte_100ppm"
    assert envelope.model_provenance.kg_version_hash.startswith("sha256:")
    assert envelope.transcript_ref.startswith("ledger:tenant.test/seq:")


def test_evaluate_returns_flag_envelope_for_breach() -> None:
    _install_test_state()
    with TestClient(server.app) as client:
        _install_test_state()
        resp = client.post("/api/evaluate", json=_measurement_payload(150))
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "FLAG"
    assert envelope.formalizable_assertions[0].satisfied is False
    assert envelope.formalizable_assertions[0].observed == 150


def test_evaluate_returns_null_unmapped_for_unknown_metric() -> None:
    _install_test_state()
    with TestClient(server.app) as client:
        _install_test_state()
        resp = client.post(
            "/api/evaluate",
            json={
                "measurement_id": "meas-x",
                "timestamp": "2026-01-15T12:00:00Z",
                "subject": "unknown",
                "measurement": {"unrelated_metric": 1},
                "risk_tier": "standard",
            },
        )
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "NULL_UNMAPPED"


def test_evaluate_records_to_ledger() -> None:
    ledger = _install_test_state()
    with TestClient(server.app) as client:
        ledger = _install_test_state()
        client.post("/api/evaluate", json=_measurement_payload(50))
    assert len(ledger.appended) == 1
    entry = ledger.appended[0]
    assert entry["track"] == "v3-evaluator"
    assert entry["kg_version"] == "v3test-0001"
    assert entry["rule_id"] == "energy.so2.lte_100ppm"
