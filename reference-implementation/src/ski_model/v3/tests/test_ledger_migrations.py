"""Tests for ``ski_model.ledger_migrations`` — the startup schema probe.

Exercised against a hand-rolled fake ``AsyncEngine`` so no live Postgres
is required (mirrors the fake-session approach in
``test_ledger_client.py``): ``engine.connect()`` returns canned column
lists, ``engine.begin()`` records the migration SQL that was executed.
"""

from __future__ import annotations

from typing import Any, List, Sequence

import pytest

from ski_model.ledger_migrations import (
    _REQUIRED_V3_COLUMNS,
    LedgerSchemaError,
    ensure_v3_ledger_schema,
)

_ALL_PRESENT = [*_REQUIRED_V3_COLUMNS, "sequence_number", "verdict"]  # plus ordinary columns
_MISSING_SOME = ["sequence_number", "verdict"]  # none of the v3 columns present


class _ColumnResult:
    def __init__(self, columns: Sequence[str]) -> None:
        self._columns = columns

    def fetchall(self) -> List[tuple[str]]:
        return [(c,) for c in self._columns]


class _FakeConn:
    def __init__(self, columns: Sequence[str], executed: List[str]) -> None:
        self._columns = columns
        self._executed = executed

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, stmt: Any) -> _ColumnResult:
        self._executed.append(str(stmt))
        return _ColumnResult(self._columns)


class _FakeEngine:
    """Returns a queued column-list on each successive ``connect()`` call.

    ``ensure_v3_ledger_schema`` probes once up front and (on the
    migrate path) again afterward to confirm success, so tests supply
    one entry per expected probe.
    """

    def __init__(self, column_snapshots: Sequence[Sequence[str]]) -> None:
        self._snapshots = list(column_snapshots)
        self.executed: List[str] = []

    def connect(self) -> _FakeConn:
        columns = self._snapshots.pop(0)
        return _FakeConn(columns, self.executed)

    def begin(self) -> _FakeConn:
        # begin() vs connect() distinguishes the DDL-apply step in the
        # executed log below; behaviourally identical for our purposes.
        return _FakeConn([], self.executed)


class TestAlreadyAtV3:
    @pytest.mark.asyncio
    async def test_no_migration_when_columns_already_present(self) -> None:
        engine = _FakeEngine([_ALL_PRESENT])
        await ensure_v3_ledger_schema(engine)  # type: ignore[arg-type]
        # Only the probe ran; no ALTER TABLE / begin() was issued.
        assert len(engine.executed) == 1
        assert "information_schema.columns" in engine.executed[0]


class TestAutomigrate:
    @pytest.mark.asyncio
    async def test_missing_columns_triggers_migration_and_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SKI_AUTOMIGRATE", "true")
        # First probe: missing. Migration applied. Second probe: all present.
        engine = _FakeEngine([_MISSING_SOME, _ALL_PRESENT])
        await ensure_v3_ledger_schema(engine)  # type: ignore[arg-type]
        assert len(engine.executed) == 3  # probe, ALTER TABLE, re-probe
        assert "ALTER TABLE ledger_entries" in engine.executed[1]

    @pytest.mark.asyncio
    async def test_automigrate_defaults_to_true_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_AUTOMIGRATE", raising=False)
        engine = _FakeEngine([_MISSING_SOME, _ALL_PRESENT])
        await ensure_v3_ledger_schema(engine)  # type: ignore[arg-type]
        assert len(engine.executed) == 3

    @pytest.mark.asyncio
    async def test_automigrate_false_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fail-closed branch: auto-migrate disabled and the schema is
        behind -- refuse to serve rather than run with a broken ledger."""
        monkeypatch.setenv("SKI_AUTOMIGRATE", "false")
        engine = _FakeEngine([_MISSING_SOME])
        with pytest.raises(LedgerSchemaError, match="SKI_AUTOMIGRATE=false"):
            await ensure_v3_ledger_schema(engine)  # type: ignore[arg-type]
        # Only the probe ran; the migration must never be attempted.
        assert len(engine.executed) == 1

    @pytest.mark.asyncio
    async def test_partial_apply_still_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defence-in-depth: if the migration ran but columns are STILL
        missing afterward (e.g. the DB role lacks DDL privileges), refuse
        to report success."""
        monkeypatch.setenv("SKI_AUTOMIGRATE", "true")
        engine = _FakeEngine([_MISSING_SOME, _MISSING_SOME])  # still missing post-migration
        with pytest.raises(LedgerSchemaError, match="still missing"):
            await ensure_v3_ledger_schema(engine)  # type: ignore[arg-type]
        assert len(engine.executed) == 3
