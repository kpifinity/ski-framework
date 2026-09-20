"""Tests for the telemetry clock-skew guard on /api/evaluate.

Wires ``max_clock_skew_seconds`` (previously an unenforced column in the
``tenants`` schema — see docs/threat-model.md "Assumption 2") into the
runtime. A telemetry record whose own ``timestamp`` deviates from arrival
wall-clock by more than the bound must never be evaluated as fresh: it is
routed to DISCRETIONARY and ledgered (default mode), or rejected outright
with 422 (``SKI_CLOCK_SKEW_MODE=reject``).

Uses the same in-memory-double + ``TestClient`` harness as
``test_endpoint.py`` — no live KG file, database, or signing key.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from ski_model import metrics, server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import FakeLLM, V3Evaluator, V3VerdictEnvelope

# ---- In-memory test doubles (mirrors test_endpoint.py) ------------------------


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
        version="v3test-skew-0001",
        rules=[
            {
                "id": "energy.so2.lte_100ppm",
                "metric": "so2_ppm",
                "predicate": "must_not_exceed",
                "value": 100,
            }
        ],
        tag_registry={"emissions": "energy.so2.lte_100ppm"},
        metadata={"version": "v3test-skew-0001"},
        signature_verified=True,
    )


def _install_test_state(*, max_clock_skew_seconds: int = 60) -> _FakeLedger:
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
    server.state.agreement_monitor = None
    server.state.max_clock_skew_seconds = max_clock_skew_seconds
    return ledger


@contextmanager
def _client() -> Iterator[TestClient]:
    """Yield a TestClient without running the production lifespan (see test_endpoint.py)."""
    yield TestClient(server.app, raise_server_exceptions=False)


def _measurement_payload(
    *, timestamp: str, value: int = 50, measurement_id: str = "meas-skew"
) -> Dict[str, Any]:
    return {
        "measurement_id": measurement_id,
        "timestamp": timestamp,
        "subject": "emissions",
        "measurement": {"so2_ppm": value},
    }


_FAR_PAST_TIMESTAMP = "2020-01-01T00:00:00Z"  # always >60s from "now" in this repo's lifetime


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Unit-level: the pure helpers ----------------------------------------------


class TestClockSkewHelpers:
    def test_delta_is_symmetric_absolute_seconds(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        later = t0 + timedelta(seconds=90)
        assert server._clock_skew_delta_seconds(t0, later) == 90.0
        assert server._clock_skew_delta_seconds(later, t0) == 90.0

    def test_default_mode_is_discretionary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_CLOCK_SKEW_MODE", raising=False)
        assert server._clock_skew_mode() == "discretionary"

    def test_mode_reads_env_case_insensitively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_CLOCK_SKEW_MODE", "REJECT")
        assert server._clock_skew_mode() == "reject"

    def test_skew_envelope_is_discretionary_and_unverifiable(self) -> None:
        envelope = server._build_clock_skew_envelope(
            skew_note="clock_skew: telemetry Δ999.0s exceeds max_clock_skew_seconds=60",
            kg_version_hash="sha256:" + "a" * 64,
        )
        assert envelope.verdict == "DISCRETIONARY"
        assert envelope.verifier_result.status == "UNVERIFIABLE"
        assert envelope.human_attestation == {"required": True, "fulfilled": False}
        assert any("clock_skew" in n for n in envelope.notes)


class TestResolveMaxClockSkewSeconds:
    @pytest.mark.asyncio
    async def test_no_engine_no_env_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_MAX_CLOCK_SKEW_SECONDS", raising=False)
        resolved = await server._resolve_max_clock_skew_seconds(None, "tenant.test")
        assert resolved == server._DEFAULT_MAX_CLOCK_SKEW_SECONDS

    @pytest.mark.asyncio
    async def test_env_override_used_when_no_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_MAX_CLOCK_SKEW_SECONDS", "120")
        resolved = await server._resolve_max_clock_skew_seconds(None, "tenant.test")
        assert resolved == 120

    @pytest.mark.asyncio
    async def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_MAX_CLOCK_SKEW_SECONDS", "not-a-number")
        resolved = await server._resolve_max_clock_skew_seconds(None, "tenant.test")
        assert resolved == server._DEFAULT_MAX_CLOCK_SKEW_SECONDS


# ---- End-to-end: /api/evaluate ---------------------------------------------------


class TestEvaluateEnforcesClockSkew:
    def test_within_window_evaluates_normally(self) -> None:
        _install_test_state(max_clock_skew_seconds=60)
        with _client() as client:
            _install_test_state(max_clock_skew_seconds=60)
            resp = client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_now_iso()),
            )
        assert resp.status_code == 200, resp.text
        envelope = V3VerdictEnvelope.model_validate(resp.json())
        assert envelope.verdict == "CLEAR"

    def test_over_skew_short_circuits_to_discretionary(self) -> None:
        ledger = _install_test_state(max_clock_skew_seconds=60)
        with _client() as client:
            ledger = _install_test_state(max_clock_skew_seconds=60)
            resp = client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_FAR_PAST_TIMESTAMP),
            )
        assert resp.status_code == 200, resp.text
        envelope = V3VerdictEnvelope.model_validate(resp.json())
        assert envelope.verdict == "DISCRETIONARY"
        assert envelope.verifier_result.status == "UNVERIFIABLE"
        assert any("clock_skew" in n for n in envelope.notes)
        # Ledgered — never silently dropped.
        assert len(ledger.appended) == 1
        assert ledger.appended[0]["track"] == "v3-clock-skew-guard"

    def test_over_skew_does_not_reach_evaluator_or_buffer(self) -> None:
        """The rejected record must never be written into the buffer as fresh,
        and the LLM/evaluator must never see it (short-circuit, not a
        post-hoc downgrade)."""

        calls: List[str] = []

        class _RecordingBuffer:
            async def append(self, **_: Any) -> None:
                calls.append("buffer.append")

        class _RecordingEvaluator:
            async def aevaluate_with_transcript(self, **_: Any) -> Any:
                calls.append("evaluator.aevaluate_with_transcript")
                raise AssertionError("evaluator must not be called for an over-skew record")

        _install_test_state(max_clock_skew_seconds=60)
        server.state.telemetry_buffer = _RecordingBuffer()
        server.state.evaluator = _RecordingEvaluator()  # type: ignore[assignment]
        with _client() as client:
            resp = client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_FAR_PAST_TIMESTAMP),
            )
        assert resp.status_code == 200, resp.text
        assert calls == []

    def test_reject_mode_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_CLOCK_SKEW_MODE", "reject")
        _install_test_state(max_clock_skew_seconds=60)
        with _client() as client:
            ledger = _install_test_state(max_clock_skew_seconds=60)
            resp = client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_FAR_PAST_TIMESTAMP),
            )
        assert resp.status_code == 422, resp.text
        # Reject mode bounces the request outright -- no verdict, nothing ledgered.
        assert ledger.appended == []

    def test_zero_skew_disables_the_guard(self) -> None:
        """A tenant/operator can opt out entirely via max_clock_skew_seconds=0."""
        _install_test_state(max_clock_skew_seconds=0)
        with _client() as client:
            _install_test_state(max_clock_skew_seconds=0)
            resp = client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_FAR_PAST_TIMESTAMP),
            )
        assert resp.status_code == 200, resp.text
        envelope = V3VerdictEnvelope.model_validate(resp.json())
        # Evaluated normally (CLEAR from FakeLLM), not short-circuited.
        assert envelope.verdict == "CLEAR"

    def test_clock_skew_metric_increments_on_violation(self) -> None:
        before = metrics.TELEMETRY_CLOCK_SKEW._value.get()
        _install_test_state(max_clock_skew_seconds=60)
        with _client() as client:
            _install_test_state(max_clock_skew_seconds=60)
            client.post(
                "/api/evaluate",
                json=_measurement_payload(timestamp=_FAR_PAST_TIMESTAMP),
            )
        after = metrics.TELEMETRY_CLOCK_SKEW._value.get()
        assert after == before + 1
