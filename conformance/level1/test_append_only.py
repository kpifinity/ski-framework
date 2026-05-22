"""SKI Framework v2.1 § B5.2 — Append-only audit ledger.

The audit ledger MUST refuse UPDATE, DELETE, and TRUNCATE on
`ledger_entries`. Enforcement at the application layer alone is
insufficient — the spec requires DB-level enforcement so that an
insider with INSERT/SELECT privileges cannot rewrite history.

This test asserts the triggers ship in the schema. If a live ledger is
available, it also attempts an UPDATE and confirms it fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.level1
def test_append_only_triggers_present_in_schema(repo_root: Path) -> None:
    sql = (repo_root / "reference-implementation" / "src" / "ledger" / "append_only.sql").read_text()
    for op in ("BEFORE UPDATE", "BEFORE DELETE", "BEFORE TRUNCATE"):
        assert op in sql, f"append_only.sql is missing a {op} trigger."
    assert "ledger_block_update_delete" in sql, "Append-only trigger function missing."


@pytest.mark.level1
@pytest.mark.requires_ledger
def test_live_update_is_refused(require_ledger: str) -> None:
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine, text

    engine = create_engine(require_ledger)
    with engine.begin() as conn:
        # Ensure at least one row exists for the UPDATE attempt.
        rows = conn.execute(text("SELECT id FROM ledger_entries ORDER BY id LIMIT 1")).all()
        if not rows:
            pytest.skip("Ledger is empty; cannot test UPDATE refusal without a row.")
        try:
            conn.execute(text("UPDATE ledger_entries SET verdict='CLEAR' WHERE id = :id"), {"id": rows[0][0]})
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            assert "append-only" in msg or "insufficient_privilege" in msg, (
                f"UPDATE failed but for the wrong reason: {exc}"
            )
            return
        pytest.fail(
            "UPDATE on ledger_entries succeeded — the append-only trigger is not installed."
        )
