"""SKI Framework v2.1 § B4.4 — NULL_STALE routing.

A rule with `requires_recent_within_seconds` must produce a NULL_STALE
verdict when the buffer has no record for the subject within the
window. This is the freshness path that v0.1 stubbed and v0.2 wires.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.level2
def test_evaluator_returns_null_stale_when_no_fresh_sample(repo_root: Path) -> None:
    """Symbolic Evaluator returns NULL_STALE when the freshness gate fails."""
    import sys

    src = repo_root / "reference-implementation" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from symbolic_evaluator.evaluator import SymbolicEvaluator
    from symbolic_evaluator import Verdict  # type: ignore

    # An in-memory buffer with one very old sample.
    class _EmptyBuffer:
        async def window_query(self, **_: object):
            class _R:
                count = 0
                sum_value = None
                avg_value = None
                oldest_ts = None
                newest_ts = None
                last_ts = None
            return _R()

        async def last_record_ts(self, **_: object):
            return None

        async def has_fresh_sample(self, **_: object) -> bool:
            return False

    rule = {
        "id": "test.fresh",
        "track": "symbolic",
        "predicate": {
            "operator": "lte",
            "metric": "x",
            "value": 100,
            "requires_recent_within_seconds": 60,
        },
    }
    telemetry = {
        "subject": "test.subj",
        "telemetry_id": "tel_1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "measurement": {"x": 50},
    }
    decision = asyncio.get_event_loop().run_until_complete(
        SymbolicEvaluator().aevaluate(rule, telemetry, buffer=_EmptyBuffer(), as_of=datetime.now(timezone.utc))
    )
    assert decision.verdict == Verdict.NULL_STALE, decision.reasoning


@pytest.mark.level2
def test_schema_has_telemetry_buffer_with_append_only(repo_root: Path) -> None:
    """B5.2 extension — the buffer must be append-only at the DB layer."""
    sql = (repo_root / "reference-implementation" / "src" / "ledger" / "telemetry_buffer.sql").read_text()
    assert "PARTITION BY RANGE (telemetry_ts)" in sql, "Buffer must be partitioned by telemetry_ts for retention."
    for op in ("BEFORE UPDATE", "BEFORE DELETE", "BEFORE TRUNCATE"):
        assert op in sql and "telemetry_buffer" in sql, f"telemetry_buffer must have a {op} trigger."
    assert "ledger_block_update_delete" in sql, "Buffer triggers must reuse the ledger append-only function."


@pytest.mark.level2
def test_rfc_documents_authoritative_clock(repo_root: Path) -> None:
    """The design must commit to using telemetry timestamps as the clock."""
    rfc = (repo_root / "docs" / "RFCs" / "0001-stateful-evaluation.md").read_text()
    assert "authoritative clock" in rfc.lower()
    assert "wall-clock" in rfc.lower()
