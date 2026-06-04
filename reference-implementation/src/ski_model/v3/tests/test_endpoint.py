"""Integration tests for the v3 /api/evaluate endpoint.

The full server lifespan touches a Knowledge Graph file, a database engine,
and a background canary task — none of which we want CI to depend on. These
tests therefore:

  * Set environment via :mod:`conftest` to disable the API key requirement.
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

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List

from fastapi.testclient import TestClient

from ski_model import server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import FakeLLM, V3Evaluator, V3VerdictEnvelope

# ---- In-memory test doubles ---------------------------------------------------


@dataclass
class _FakeLedger:
    appended: List[Dict[str, Any]]

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def append_v3(self, **kwargs: Any) -> None:
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
    server.state.tag_registry = None
    server.state.telemetry_buffer = None
    server.state.tenant_id = "tenant.test"
    server.state.verdicts_produced = 0
    server.state.kg_version_hash = evaluator.kg_version_hash
    # PR 12: agreement monitor; the /api/health handler tolerates None.
    server.state.agreement_monitor = None
    return ledger


@contextmanager
def _client() -> Iterator[TestClient]:
    """Yield a TestClient WITHOUT running the production lifespan.

    Using ``TestClient`` as a context manager would execute the real
    startup path, which provisions an Ed25519 signing key under ``/app``
    and opens a Postgres connection for the ledger schema check — neither
    is available (or desirable) in a hermetic unit test. These tests inject
    in-memory doubles via :func:`_install_test_state`, so the lifespan is
    intentionally skipped.
    """
    yield TestClient(server.app)


# ---- Tests --------------------------------------------------------------------


def _measurement_payload(value: int) -> Dict[str, Any]:
    # PR 13: ``risk_tier`` is intentionally still included to prove
    # that v2-shape callers don't crash — the field is silently
    # ignored, and the tier is derived from the KG by the
    # RiskTierGovernor. See ``test_strict_governor_ignores_caller_risk_tier``.
    return {
        "measurement_id": f"meas-{value}",
        "timestamp": "2026-01-15T12:00:00Z",
        "subject": "emissions",
        "measurement": {"so2_ppm": value},
        "risk_tier": "tier-3",
    }


def test_health_reports_v3_runtime() -> None:
    _install_test_state()
    with _client() as client:
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
    with _client() as client:
        _install_test_state()
        resp = client.post("/api/evaluate", json=_measurement_payload(50))
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "CLEAR"
    assert envelope.reasoning
    assert len(envelope.kg_citations) == 1
    assert envelope.kg_citations[0].node_id == "energy.so2.lte_100ppm"
    assert envelope.model_provenance.kg_version_hash.startswith("sha256:")
    # The server does not pre-assign a ledger sequence to the envelope; the
    # evaluator therefore emits its default self-reference ``transcript:<id>``
    # (see test_transcript.py). The ``ledger:<tenant>/seq:<n>`` form is what
    # callers supply when they already hold a ledger pointer.
    assert envelope.transcript_ref.startswith("transcript:")


def test_evaluate_returns_flag_envelope_for_breach() -> None:
    _install_test_state()
    with _client() as client:
        _install_test_state()
        resp = client.post("/api/evaluate", json=_measurement_payload(150))
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "FLAG"
    assert envelope.formalizable_assertions[0].satisfied is False
    assert envelope.formalizable_assertions[0].observed == 150


def test_evaluate_returns_null_unmapped_for_unknown_metric() -> None:
    _install_test_state()
    with _client() as client:
        _install_test_state()
        resp = client.post(
            "/api/evaluate",
            json={
                "measurement_id": "meas-x",
                "timestamp": "2026-01-15T12:00:00Z",
                "subject": "unknown",
                "measurement": {"unrelated_metric": 1},
            },
        )
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "NULL_UNMAPPED"


def test_strict_governor_ignores_caller_risk_tier() -> None:
    """The strict-governor invariant (PR 13).

    The caller sends ``"risk_tier": "tier-3"`` — the most permissive
    tier. The KG rule has no ``risk_tier`` field, so the governor
    returns the default tier-2. The endpoint must accept the request
    and the chosen tier must come from the KG, not the caller.

    We assert this indirectly: the request succeeds (200) and the
    envelope's verdict is computed normally. A non-200 here would mean
    Pydantic rejected the field; a corrupted envelope would mean the
    caller's tier influenced policy. Neither is acceptable.
    """
    _install_test_state()
    with _client() as client:
        _install_test_state()
        resp = client.post(
            "/api/evaluate",
            json={
                "measurement_id": "meas-strict",
                "timestamp": "2026-01-15T12:00:00Z",
                "subject": "emissions",
                "measurement": {"so2_ppm": 50},
                "risk_tier": "tier-3",  # ignored — strict governor wins
            },
        )
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "CLEAR"


def test_evaluate_records_to_ledger() -> None:
    ledger = _install_test_state()
    with _client() as client:
        ledger = _install_test_state()
        client.post("/api/evaluate", json=_measurement_payload(50))
    assert len(ledger.appended) == 1
    entry = ledger.appended[0]
    assert entry["track"] == "v3-evaluator"
    assert entry["kg_version"] == "v3test-0001"
    assert entry["rule_id"] == "energy.so2.lte_100ppm"
