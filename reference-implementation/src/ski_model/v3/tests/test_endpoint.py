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

from ski_model import metrics, server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import AgreementMonitor, FakeLLM, V3Evaluator, V3VerdictEnvelope

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
    # These tests exercise evaluator/governor/ledger behaviour with a fixed
    # measurement timestamp, not clock-skew enforcement (see
    # test_clock_skew_guard.py for that) -- disable the guard so a fixture
    # timestamp aging past the skew bound doesn't produce a false failure.
    server.state.max_clock_skew_seconds = 0
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


def test_unverifiable_increments_the_by_tier_metric() -> None:
    """A5 observability: NULL_UNMAPPED with zero assertions is UNVERIFIABLE
    (see test_evaluate_returns_null_unmapped_for_unknown_metric); the KG
    rule declares no risk_tier, so the governor's default tier-2 is what
    the metric should be labelled with."""
    before = metrics.UNVERIFIABLE_BY_TIER.labels(tier="tier-2")._value.get()
    _install_test_state()
    with _client() as client:
        _install_test_state()
        resp = client.post(
            "/api/evaluate",
            json={
                "measurement_id": "meas-metric",
                "timestamp": "2026-01-15T12:00:00Z",
                "subject": "unknown",
                "measurement": {"unrelated_metric": 1},
            },
        )
    assert resp.status_code == 200, resp.text
    after = metrics.UNVERIFIABLE_BY_TIER.labels(tier="tier-2")._value.get()
    assert after == before + 1


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


def test_evaluate_returns_5xx_and_no_verdict_when_ledger_append_fails() -> None:
    """A verdict must never reach the caller unless it was durably recorded.

    The endpoint has no try/except around ``ledger.append_v3`` — that is
    deliberate fail-closed behaviour, not a gap: FastAPI's default
    exception handling turns the unhandled error into a 500 with no
    body matching ``V3VerdictEnvelope``, so a caller can never observe a
    verdict that was computed but not persisted to the audit ledger.
    """

    @dataclass
    class _RaisingLedger:
        async def initialize(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def append_v3(self, **kwargs: Any) -> None:
            raise RuntimeError("simulated ledger append failure (e.g. DB connection lost)")

        async def list(self, *, limit: int, offset: int) -> List[Dict[str, Any]]:
            return []

    _install_test_state()
    # raise_server_exceptions=False so we can assert on the actual HTTP
    # response FastAPI sends a real caller, instead of TestClient
    # re-raising the exception into the test itself.
    client = TestClient(server.app, raise_server_exceptions=False)
    _install_test_state()
    server.state.ledger = _RaisingLedger()  # type: ignore[assignment]
    resp = client.post("/api/evaluate", json=_measurement_payload(50))
    assert resp.status_code >= 500, resp.text
    # No partial / unpersisted verdict body — the response must NOT be a
    # valid V3VerdictEnvelope (which always carries a "verdict" key).
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        assert "verdict" not in body


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


def test_risk_policy_downgrade_persists_valid_verdict_through_real_ledger_client() -> None:
    """Regression: a risk-policy downgrade must produce a ledger row that
    satisfies ``ledger_entries.verdict CHECK (verdict IN (...))``.

    Mirrors golden case ``flag-flow-just-under`` in
    ``evals/datasets/energy``: FakeLLM misreads the ``must_be_at_least``
    breach, the verifier reports NEURO_SYMBOLIC_DIVERGENCE, and the tier-2
    policy downgrades to DISCRETIONARY via ``model_copy``. The real
    :class:`LedgerClient` (over a fake session) is used so the actual
    INSERT parameters are asserted, not just the kwargs the endpoint passes.
    """
    from ski_model.ledger_client import LedgerClient

    from .test_ledger_client import _FakeResult, _FakeSession

    _install_test_state()
    server.state.knowledge_graph = KnowledgeGraph(
        version="v3test-flow",
        rules=[
            {
                "id": "energy.flow.min",
                "metric": "flow_m3h",
                "predicate": "must_be_at_least",
                "value": 10,
            }
        ],
        tag_registry={"facility.flow_m3h": "energy.flow.min"},
        metadata={"version": "v3test-flow"},
        signature_verified=True,
    )
    session = _FakeSession([_FakeResult(first_row=None), _FakeResult()])
    ledger = LedgerClient("postgresql://user:pass@localhost/ski")
    ledger._session_factory = lambda: session  # type: ignore[assignment]
    server.state.ledger = ledger  # type: ignore[assignment]

    client = TestClient(server.app)
    resp = client.post(
        "/api/evaluate",
        json={
            "measurement_id": "meas-flow",
            "timestamp": "2026-01-15T12:00:00Z",
            "subject": "facility.flow_m3h",
            "measurement": {"flow_m3h": 9.9},
        },
    )
    assert resp.status_code == 200, resp.text
    envelope = V3VerdictEnvelope.model_validate(resp.json())
    assert envelope.verdict == "DISCRETIONARY"
    assert envelope.verifier_result.status == "NEURO_SYMBOLIC_DIVERGENCE"

    insert_params = session.executed[1][1]
    assert insert_params is not None
    assert insert_params["verdict"] == "DISCRETIONARY"
    assert insert_params["verifier_status"] == "NEURO_SYMBOLIC_DIVERGENCE"


def test_list_verdicts_reads_through_to_ledger() -> None:
    ledger = _install_test_state()
    with _client() as client:
        ledger = _install_test_state()
        client.post("/api/evaluate", json=_measurement_payload(50))
        resp = client.get("/api/verdicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["verdicts"]) == 1
    assert ledger.appended  # sanity: same entries the ledger actually holds


def test_canary_reports_not_started_before_any_evaluation() -> None:
    _install_test_state()
    with _client() as client:
        _install_test_state()
        server.state.agreement_monitor = None
        resp = client.get("/api/canary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "not_started"


def test_canary_reports_healthy_snapshot_after_agreed_evaluations() -> None:
    _install_test_state()
    with _client() as client:
        _install_test_state()
        server.state.agreement_monitor = AgreementMonitor(window_size=100, threshold=0.95)
        client.post("/api/evaluate", json=_measurement_payload(50))  # AGREED verifier status
        resp = client.get("/api/canary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["is_healthy"] is True
