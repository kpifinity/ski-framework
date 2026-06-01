"""SKI Framework v3.0 §6 — Coverage Register.

When NULL_UNMAPPED is produced, the entry must be queryable via the
``coverage_register`` view. This is the audit story for "what did we
receive that we couldn't evaluate" — and is therefore a durability
concern: the provenance trail for unmapped subjects must be
durable and queryable, not silently lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.durability
def test_schema_has_coverage_register_view() -> None:
    schema = (REPO_ROOT / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    assert "CREATE OR REPLACE VIEW coverage_register" in schema
    assert "NULL_UNMAPPED" in schema and "NULL_STALE" in schema


@pytest.mark.durability
def test_coverage_register_only_selects_null_verdicts() -> None:
    schema = (REPO_ROOT / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    block = schema[schema.find("coverage_register") :]
    block_lines = block.splitlines()[:30]
    block_text = "\n".join(block_lines)
    assert "WHERE verdict IN ('NULL_UNMAPPED', 'NULL_STALE')" in block_text
