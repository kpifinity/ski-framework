"""Tests for ``telemetry_buffer.TelemetryBuffer``.

The Symbolic Verifier's stateful predicates (``must_average_within``,
``must_not_exceed_in_window``) query this buffer via the ``BufferLike``
protocol in production; ``test_verifier_stateful.py`` covers the
verifier side against an in-memory fake. This file covers the buffer's
*own* SQL-construction and result-mapping logic, against a hand-rolled
fake async session (mirrors ``test_ledger_client.py`` /
``test_ledger_migrations.py`` — no live Postgres needed, since engine
construction is lazy and we swap in the fake session factory directly).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from telemetry_buffer.buffer import BufferError, TelemetryBuffer, canonical_measurement_hash

from ski_model.v3 import FormalizableAssertion, SymbolicVerifier, V3Verdict, VerifierStatus

_AS_OF = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---- Fake async session plumbing ------------------------------------------------


class _FakeResult:
    def __init__(self, row: Optional[Sequence[Any]] = None) -> None:
        self._row = row

    def one(self) -> Sequence[Any]:
        assert self._row is not None
        return self._row

    def first(self) -> Optional[Sequence[Any]]:
        return self._row


class _FakeSession:
    def __init__(self, results: Sequence[_FakeResult]) -> None:
        self._results = list(results)
        self.executed: List[tuple[str, Optional[Dict[str, Any]]]] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def begin(self) -> _FakeSession:
        return self

    async def execute(self, stmt: Any, params: Optional[Dict[str, Any]] = None) -> _FakeResult:
        self.executed.append((str(stmt), params))
        return self._results.pop(0)


def _buffer_with_session(session: _FakeSession, *, tenant_id: str = "tenant.test") -> TelemetryBuffer:
    # create_async_engine is lazy — no connection is opened at construction,
    # so a bogus DSN is safe here (same technique as test_ledger_client.py).
    engine = create_async_engine("postgresql+psycopg://user:pass@localhost:1/nonexistent")
    buf = TelemetryBuffer(engine, tenant_id=tenant_id)
    buf._sessions = lambda: session  # type: ignore[assignment]
    return buf


# ---- canonical_measurement_hash — pure function ---------------------------------


class TestCanonicalHash:
    def test_deterministic(self) -> None:
        m = {"so2_ppm": 50, "unit": "ppm"}
        assert canonical_measurement_hash(m) == canonical_measurement_hash(m)

    def test_key_order_does_not_affect_hash(self) -> None:
        assert canonical_measurement_hash({"a": 1, "b": 2}) == canonical_measurement_hash({"b": 2, "a": 1})

    def test_different_values_hash_differently(self) -> None:
        assert canonical_measurement_hash({"a": 1}) != canonical_measurement_hash({"a": 2})


# ---- append ----------------------------------------------------------------------


class TestConstruction:
    def test_tenant_id_property(self) -> None:
        buf = _buffer_with_session(_FakeSession([]), tenant_id="tenant.acme")
        assert buf.tenant_id == "tenant.acme"


class TestAppend:
    @pytest.mark.asyncio
    async def test_writes_measurement_with_hash(self) -> None:
        session = _FakeSession([_FakeResult()])
        buf = _buffer_with_session(session)
        await buf.append(
            subject="emissions",
            telemetry_id="t1",
            telemetry_ts=_AS_OF,
            measurement={"so2_ppm": 50},
        )
        assert len(session.executed) == 1
        params = session.executed[0][1]
        assert params is not None
        assert params["subject"] == "emissions"
        assert params["tenant_id"] == "tenant.test"
        assert params["measurement_hash"] == canonical_measurement_hash({"so2_ppm": 50})


# ---- window_query ------------------------------------------------------------------


class TestWindowQuery:
    @pytest.mark.asyncio
    async def test_rejects_non_positive_window(self) -> None:
        buf = _buffer_with_session(_FakeSession([]))
        with pytest.raises(BufferError, match="window_seconds must be positive"):
            await buf.window_query(subject="emissions", as_of=_AS_OF, window_seconds=0)

    @pytest.mark.asyncio
    async def test_count_and_bounds_without_metric_path(self) -> None:
        oldest = _AS_OF - timedelta(seconds=100)
        newest = _AS_OF - timedelta(seconds=10)
        session = _FakeSession([_FakeResult(row=(3, oldest, newest))])
        buf = _buffer_with_session(session)
        result = await buf.window_query(subject="emissions", as_of=_AS_OF, window_seconds=300)
        assert result.count == 3
        assert result.oldest_ts == oldest
        assert result.newest_ts == newest
        assert result.last_ts == newest
        assert result.sum_value is None
        assert result.avg_value is None
        assert len(session.executed) == 1  # no metric_path -> single query

    @pytest.mark.asyncio
    async def test_aggregates_metric_path_when_count_positive(self) -> None:
        session = _FakeSession(
            [
                _FakeResult(row=(2, _AS_OF - timedelta(seconds=50), _AS_OF - timedelta(seconds=10))),
                _FakeResult(row=(150.0, 75.0, 90.0)),  # SUM, AVG, MAX
            ]
        )
        buf = _buffer_with_session(session)
        result = await buf.window_query(
            subject="emissions", as_of=_AS_OF, window_seconds=300, metric_path="so2_ppm.value"
        )
        assert result.count == 2
        assert result.sum_value == 150.0
        assert result.avg_value == 75.0
        assert result.max_value == 90.0
        assert len(session.executed) == 2
        assert "MAX(" in session.executed[1][0]
        agg_params = session.executed[1][1]
        assert agg_params is not None
        assert agg_params["path"] == "{so2_ppm,value}"

    @pytest.mark.asyncio
    async def test_skips_aggregation_query_when_count_is_zero(self) -> None:
        session = _FakeSession([_FakeResult(row=(0, None, None))])
        buf = _buffer_with_session(session)
        result = await buf.window_query(
            subject="emissions", as_of=_AS_OF, window_seconds=300, metric_path="so2_ppm.value"
        )
        assert result.count == 0
        assert result.sum_value is None
        assert result.avg_value is None
        assert result.max_value is None
        assert len(session.executed) == 1  # aggregation query skipped

    @pytest.mark.asyncio
    async def test_null_aggregates_map_to_none(self) -> None:
        """All matched rows had non-numeric / missing values at the path."""
        session = _FakeSession(
            [
                _FakeResult(row=(1, _AS_OF, _AS_OF)),
                _FakeResult(row=(None, None, None)),
            ]
        )
        buf = _buffer_with_session(session)
        result = await buf.window_query(
            subject="emissions", as_of=_AS_OF, window_seconds=300, metric_path="status"
        )
        assert result.sum_value is None
        assert result.avg_value is None
        assert result.max_value is None


# ---- window_query -> SymbolicVerifier (production shape end to end) -----------------


def _stateful_assertion(predicate: str, value: Any, *, satisfied: bool) -> FormalizableAssertion:
    return FormalizableAssertion(
        predicate=predicate,
        metric="so2_ppm",
        value=value,
        observed=None,
        satisfied=satisfied,
        obligation_id="ob.x",
        window_seconds=300,
    )


class TestVerifierConsumesWindowQueryResult:
    """The verifier must consume the real buffer's aggregate result.

    Regression: ``SymbolicVerifier`` used to iterate ``window_query``'s result
    as a list of samples, so a ``WindowQueryResult`` raised ``TypeError`` and
    crashed any v3 evaluation carrying a stateful assertion.
    """

    @staticmethod
    def _buffer(sum_avg_max: Sequence[Any]) -> TelemetryBuffer:
        oldest, newest = _AS_OF - timedelta(seconds=100), _AS_OF - timedelta(seconds=10)
        return _buffer_with_session(
            _FakeSession([_FakeResult(row=(3, oldest, newest)), _FakeResult(row=tuple(sum_avg_max))])
        )

    @pytest.mark.asyncio
    async def test_must_average_within_uses_avg_value(self) -> None:
        result = await SymbolicVerifier().averify(
            [_stateful_assertion("must_average_within", [50.0, 100.0], satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=self._buffer((210.0, 70.0, 150.0)),
        )
        assert result.status == VerifierStatus.AGREED.value

    @pytest.mark.asyncio
    async def test_must_not_exceed_in_window_uses_max_value(self) -> None:
        # Average 70 is under the cap; the 150 peak is not.
        result = await SymbolicVerifier().averify(
            [_stateful_assertion("must_not_exceed_in_window", 100, satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=self._buffer((210.0, 70.0, 150.0)),
        )
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value
        assert any("peak(so2_ppm, 300s)=150" in d for d in result.divergences)

    @pytest.mark.asyncio
    async def test_no_numeric_samples_is_unverifiable(self) -> None:
        result = await SymbolicVerifier().averify(
            [_stateful_assertion("must_not_exceed_in_window", 100, satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
            subject="emissions",
            as_of=_AS_OF,
            buffer=self._buffer((None, None, None)),
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value


# ---- last_record_ts / has_fresh_sample ---------------------------------------------


class TestLastRecordTs:
    @pytest.mark.asyncio
    async def test_returns_the_timestamp(self) -> None:
        ts = _AS_OF - timedelta(seconds=30)
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=(ts,))]))
        result = await buf.last_record_ts(subject="emissions", as_of=_AS_OF)
        assert result == ts

    @pytest.mark.asyncio
    async def test_returns_none_for_unseen_subject(self) -> None:
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=(None,))]))
        result = await buf.last_record_ts(subject="unseen", as_of=_AS_OF)
        assert result is None


class TestHasFreshSample:
    @pytest.mark.asyncio
    async def test_rejects_non_positive_within_seconds(self) -> None:
        buf = _buffer_with_session(_FakeSession([]))
        with pytest.raises(BufferError, match="within_seconds must be positive"):
            await buf.has_fresh_sample(subject="emissions", as_of=_AS_OF, within_seconds=0)

    @pytest.mark.asyncio
    async def test_false_when_never_seen(self) -> None:
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=(None,))]))
        assert await buf.has_fresh_sample(subject="unseen", as_of=_AS_OF, within_seconds=60) is False

    @pytest.mark.asyncio
    async def test_true_when_sample_within_window(self) -> None:
        ts = _AS_OF - timedelta(seconds=30)
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=(ts,))]))
        assert await buf.has_fresh_sample(subject="emissions", as_of=_AS_OF, within_seconds=60) is True

    @pytest.mark.asyncio
    async def test_false_when_sample_outside_window(self) -> None:
        ts = _AS_OF - timedelta(seconds=120)
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=(ts,))]))
        assert await buf.has_fresh_sample(subject="emissions", as_of=_AS_OF, within_seconds=60) is False


# ---- fetch_at (replay helper) -------------------------------------------------------


class TestFetchAt:
    @pytest.mark.asyncio
    async def test_returns_matching_row_as_dict(self) -> None:
        row = ("emissions", "t1", _AS_OF, {"so2_ppm": 50})
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=row)]))
        result = await buf.fetch_at(telemetry_hash="sha256:abc")
        assert result == {
            "subject": "emissions",
            "telemetry_id": "t1",
            "telemetry_ts": _AS_OF,
            "measurement": {"so2_ppm": 50},
        }

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self) -> None:
        buf = _buffer_with_session(_FakeSession([_FakeResult(row=None)]))
        result = await buf.fetch_at(telemetry_hash="sha256:doesnotexist")
        assert result is None
