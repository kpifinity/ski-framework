"""SKI Framework v2.1 § B4.3 — Coverage Register.

When NULL_UNMAPPED is produced, the entry must be queryable via the
coverage_register view. This is the audit story for "what did we
receive that we couldn't evaluate."
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.level2
def test_schema_has_coverage_register_view() -> None:
    schema = (REPO_ROOT / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    assert "CREATE OR REPLACE VIEW coverage_register" in schema
    assert "NULL_UNMAPPED" in schema and "NULL_STALE" in schema


@pytest.mark.level2
def test_coverage_register_only_selects_null_verdicts() -> None:
    schema = (REPO_ROOT / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    # The view must scope to NULL verdicts only; CLEAR / FLAG / DISCRETIONARY
    # belong in the main ledger, not the coverage register.
    block = schema[schema.find("coverage_register") :]
    block_lines = block.splitlines()[:30]
    block_text = "\n".join(block_lines)
    assert "WHERE verdict IN ('NULL_UNMAPPED', 'NULL_STALE')" in block_text
