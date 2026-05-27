"""Unit tests for the v0.2 stateful predicates in the Symbolic Evaluator.

These tests use an in-memory fake buffer that implements the
``BufferLike`` Protocol. No Postgres required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine, Optional

import pytest

from symbolic_evaluator import Verdict
from symbolic_evaluator.evaluator import SymbolicEvaluator

# --------------------------------------------------------------------------
# Fake buffer that satisfies the BufferLike Protocol
# --------------------------------------------------------------------------


@dataclass
class _Row:
    subject: str
    ts: datetime
    measurement: dict[str, Any]


class FakeBuffer:
    def __init__(self) -> None:
        self._rows: list[_Row] = []

    def add(self, subject: str, ts: datetime, measurement: dict[str, Any]) -> None:
        self._rows.append(_Row(subject=subject, ts=ts, measurement=measurement))

    async def window_query(
        self,
        *,
        subject: str,
        as_of: datetime,
        window_seconds: int,
        metric_path: Optional[str] = None,
    ) -> Any:
        window_start = as_of - timedelta(seconds=window_seconds)
        rows = [r for r in self._rows if r.subject == subject and window_start < r.ts <= as_of]
        count = len(rows)
        oldest = min((r.ts for r in rows), default=None)
        newest = max((r.ts for r in rows), default=None)

        sum_value: Optional[float] = None
        avg_value: Optional[float] = None
        if metric_path:
            numeric_values: list[float] = []
            for r in rows:
                cur: Any = r.measurement
                for part in metric_path.split("."):
                    if isinstance(cur, dict) and part in cur:
                        cur = cur[part]
                    else:
                        cur = None
                        break
                if isinstance(cur, (int, float)):
                    numeric_values.append(float(cur))
            if numeric_values:
                sum_value = sum(numeric_values)
                avg_value = sum_value / len(numeric_values)

        return type(
            "WQ",
            (),
            {
                "count": count,
                "sum_value": sum_value,
                "avg_value": avg_value,
                "oldest_ts": oldest,
                "newest_ts": newest,
                "last_ts": newest,
            },
        )()

    async def last_record_ts(self, *, subject: str, as_of: datetime) -> Optional[datetime]:
        rows = [r for r in self._rows if r.subject == subject and r.ts <= as_of]
        return max((r.ts for r in rows), default=None)

    async def has_fresh_sample(self, *, subject: str, as_of: datetime, within_seconds: int) -> bool:
        last = await self.last_record_ts(subject=subject, as_of=as_of)
        if last is None:
            return False
        return (as_of - last).total_seconds() <= within_seconds


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


def _telemetry(subject: str, ts: datetime, measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": subject,
        "telemetry_id": f"tel_{int(ts.timestamp())}",
        "timestamp": ts.isoformat(),
        "measurement": measurement,
    }


def _rule(rule_id: str, predicate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return {
        "id": rule_id,
        "track": "symbolic",
        "predicate": predicate,
        **kwargs,
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_window_count_clear_when_under_limit() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        buf.add("emissions.so2", now - timedelta(seconds=10 * (i + 1)), {"x": 1})

    rule = _rule(
        "r.window.count",
        {"operator": "window_count", "metric": "x", "seconds": 60, "op": "lte", "value": 5},
    )
    telemetry = _telemetry("emissions.so2", now, {"x": 1})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.CLEAR, decision.reasoning


def test_window_count_flag_when_over_limit() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(10):
        buf.add("emissions.so2", now - timedelta(seconds=i + 1), {"x": 1})

    rule = _rule(
        "r.window.count",
        {"operator": "window_count", "metric": "x", "seconds": 60, "op": "lte", "value": 5},
    )
    telemetry = _telemetry("emissions.so2", now, {"x": 1})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.FLAG


def test_window_avg_uses_metric_path() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    for i, value in enumerate([90, 100, 110]):
        buf.add(
            "emissions.so2",
            now - timedelta(seconds=10 * (i + 1)),
            {"so2_ppm": {"value": value, "unit": "ppm"}},
        )
    rule = _rule(
        "r.window.avg",
        {
            "operator": "window_avg",
            "metric": "so2_ppm.value",
            "seconds": 60,
            "op": "lte",
            "value": 100,
        },
    )
    telemetry = _telemetry("emissions.so2", now, {"so2_ppm": {"value": 110, "unit": "ppm"}})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    # avg of {90, 100, 110} = 100 → exactly lte 100 → CLEAR
    assert decision.verdict == Verdict.CLEAR, decision.reasoning


def test_null_stale_when_no_fresh_sample() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    # Last sample is 2 hours old
    buf.add("emissions.so2", now - timedelta(hours=2), {"x": 1})

    rule = _rule(
        "r.fresh",
        {
            "operator": "lte",
            "metric": "so2_ppm",
            "value": 100,
            "requires_recent_within_seconds": 60,
        },
    )
    telemetry = _telemetry("emissions.so2", now, {"so2_ppm": 85})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.NULL_STALE, decision.reasoning


def test_since_last_gte_returns_clear() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf.add("login.priv", now - timedelta(seconds=120), {})

    rule = _rule(
        "r.since",
        {"operator": "since_last", "metric": "n/a", "op": "gte", "value_seconds": 60},
    )
    telemetry = _telemetry("login.priv", now, {})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.CLEAR


def test_since_last_returns_null_unmapped_when_no_prior() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)

    rule = _rule(
        "r.since",
        {"operator": "since_last", "metric": "n/a", "op": "gte", "value_seconds": 60},
    )
    telemetry = _telemetry("login.priv", now, {})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.NULL_UNMAPPED


def test_debounce_clear_when_no_recent_event() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf.add("alert", now - timedelta(seconds=120), {})

    rule = _rule(
        "r.deb",
        {"operator": "debounce", "metric": "n/a", "seconds": 60},
    )
    telemetry = _telemetry("alert", now, {})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.CLEAR


def test_debounce_discretionary_when_event_in_window() -> None:
    buf = FakeBuffer()
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf.add("alert", now - timedelta(seconds=30), {})

    rule = _rule(
        "r.deb",
        {"operator": "debounce", "metric": "n/a", "seconds": 60},
    )
    telemetry = _telemetry("alert", now, {})
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert decision.verdict == Verdict.DISCRETIONARY


def test_sync_evaluate_rejects_stateful_predicate() -> None:
    rule = _rule(
        "r.window.count",
        {"operator": "window_count", "metric": "x", "seconds": 60, "op": "lte", "value": 5},
    )
    telemetry = _telemetry("anything", datetime.now(timezone.utc), {"x": 1})
    decision = SymbolicEvaluator().evaluate(rule, telemetry)
    assert decision.verdict == Verdict.DISCRETIONARY
    assert "stateful" in decision.reasoning.lower()


def test_aevaluate_falls_back_to_stateless_for_simple_lte() -> None:
    """Existing v0.1 stateless rules still work through aevaluate."""
    rule = _rule(
        "r.lte",
        {"operator": "lte", "metric": "so2_ppm", "value": 100, "unit": "ppm"},
    )
    telemetry = _telemetry(
        "emissions.so2",
        datetime.now(timezone.utc),
        {"so2_ppm": {"value": 85, "unit": "ppm"}},
    )
    decision = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=None, as_of=None))
    assert decision.verdict == Verdict.CLEAR
