"""SKI Framework v3.0 §5.3 — Stateful predicate provenance.

``window_count``, ``window_sum``, and ``window_avg`` predicates must
produce correct verdicts against a fixed buffer state. Stateful
predicates participate in the verifier's mechanical cross-check (PR
11.6), so their correctness is a provenance-level concern: a wrong
window computation would silently corrupt the AGREED / CONTRADICTION
signal.

These tests use an in-memory fake buffer; the durability suite
exercises the live Postgres path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine

import pytest


def _setup_path() -> None:
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "reference-implementation" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@dataclass
class _Row:
    subject: str
    ts: datetime
    measurement: dict[str, Any]


class FakeBuffer:
    """Minimal BufferLike used by tests."""

    def __init__(self) -> None:
        self.rows: list[_Row] = []

    def add(self, subject: str, ts: datetime, measurement: dict[str, Any]) -> None:
        self.rows.append(_Row(subject=subject, ts=ts, measurement=measurement))

    async def window_query(self, *, subject, as_of, window_seconds, metric_path=None):
        cutoff = as_of - timedelta(seconds=window_seconds)
        rows = [r for r in self.rows if r.subject == subject and cutoff < r.ts <= as_of]
        count = len(rows)
        oldest = min((r.ts for r in rows), default=None)
        newest = max((r.ts for r in rows), default=None)
        sum_v = None
        avg_v = None
        if metric_path:
            vals: list[float] = []
            for r in rows:
                cur: Any = r.measurement
                for part in metric_path.split("."):
                    if isinstance(cur, dict) and part in cur:
                        cur = cur[part]
                    else:
                        cur = None
                        break
                if isinstance(cur, (int, float)):
                    vals.append(float(cur))
            if vals:
                sum_v = sum(vals)
                avg_v = sum_v / len(vals)
        return type(
            "WQ",
            (),
            {
                "count": count,
                "sum_value": sum_v,
                "avg_value": avg_v,
                "oldest_ts": oldest,
                "newest_ts": newest,
                "last_ts": newest,
            },
        )()

    async def last_record_ts(self, *, subject: str, as_of: datetime) -> datetime | None:
        rows = [r for r in self.rows if r.subject == subject and r.ts <= as_of]
        return max((r.ts for r in rows), default=None)

    async def has_fresh_sample(self, *, subject, as_of, within_seconds):
        last = await self.last_record_ts(subject=subject, as_of=as_of)
        if last is None:
            return False
        return (as_of - last).total_seconds() <= within_seconds


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.provenance
def test_window_count_correctness() -> None:
    _setup_path()
    from symbolic_evaluator import Verdict
    from symbolic_evaluator.evaluator import SymbolicEvaluator

    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf = FakeBuffer()
    for i in range(7):
        buf.add("alerts.flood", now - timedelta(seconds=i + 1), {"x": 1})

    rule = {
        "id": "r",
        "track": "symbolic",
        "predicate": {"operator": "window_count", "metric": "x", "seconds": 30, "op": "lte", "value": 5},
    }
    telemetry = {
        "subject": "alerts.flood",
        "telemetry_id": "t",
        "timestamp": now.isoformat(),
        "measurement": {"x": 1},
    }
    d = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert d.verdict == Verdict.FLAG, d.reasoning


@pytest.mark.provenance
def test_window_sum_handles_missing_metric_path() -> None:
    _setup_path()
    from symbolic_evaluator import Verdict
    from symbolic_evaluator.evaluator import SymbolicEvaluator

    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf = FakeBuffer()
    for i in range(3):
        buf.add("subj", now - timedelta(seconds=i + 1), {"x": 1})

    rule = {
        "id": "r",
        "track": "symbolic",
        "predicate": {"operator": "window_sum", "metric": "y.value", "seconds": 30, "op": "lte", "value": 10},
    }
    telemetry = {
        "subject": "subj",
        "telemetry_id": "t",
        "timestamp": now.isoformat(),
        "measurement": {"x": 1},
    }
    d = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    # Missing metric path → NULL_UNMAPPED, not silent CLEAR
    assert d.verdict == Verdict.NULL_UNMAPPED


@pytest.mark.provenance
def test_window_avg_at_boundary_is_clear() -> None:
    """Boundary case: avg exactly equal to limit with `lte` is CLEAR, not FLAG."""
    _setup_path()
    from symbolic_evaluator import Verdict
    from symbolic_evaluator.evaluator import SymbolicEvaluator

    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    buf = FakeBuffer()
    for v in (90, 100, 110):
        buf.add("subj", now - timedelta(seconds=v), {"so2": {"value": v}})

    rule = {
        "id": "r",
        "track": "symbolic",
        "predicate": {
            "operator": "window_avg",
            "metric": "so2.value",
            "seconds": 200,
            "op": "lte",
            "value": 100,
        },
    }
    telemetry = {
        "subject": "subj",
        "telemetry_id": "t",
        "timestamp": now.isoformat(),
        "measurement": {"so2": {"value": 110}},
    }
    d = _run(SymbolicEvaluator().aevaluate(rule, telemetry, buffer=buf, as_of=now))
    assert d.verdict == Verdict.CLEAR
