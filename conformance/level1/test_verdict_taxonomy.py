"""SKI Framework v2.1 § B3 + Axiom 2 — Verdict taxonomy.

The runtime must produce exactly five verdict types: CLEAR, FLAG,
NULL_UNMAPPED, NULL_STALE, DISCRETIONARY. The old four-verdict
taxonomy (CLEAR / FLAG / NULL / DISCRETIONARY) is non-conformant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


REQUIRED_VERDICTS = {"CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY"}
PROHIBITED_VERDICTS = {"NULL"}


@pytest.mark.level1
def test_schema_has_all_five_verdicts(repo_root: Path) -> None:
    """The ledger SQL schema constrains `verdict` to the five-verdict set."""
    schema = (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    for verdict in REQUIRED_VERDICTS:
        assert f"'{verdict}'" in schema, f"schema.sql is missing verdict {verdict!r}"


@pytest.mark.level1
def test_schema_does_not_admit_null_alone(repo_root: Path) -> None:
    """Pre-v2.1 `NULL` (without _UNMAPPED/_STALE) must NOT appear in the schema CHECK."""
    schema = (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    # We grep for a CHECK that lists 'NULL' as a verdict value. Match
    # against a tight pattern so we don't trip on SQL nullability.
    assert "'NULL'" not in schema, (
        "schema.sql still lists 'NULL' as a verdict — replace with NULL_UNMAPPED/NULL_STALE."
    )


@pytest.mark.level1
def test_reference_verdict_enum_has_all_five(repo_root: Path) -> None:
    """The reference implementation's Verdict enum lists all five and only these."""
    src = (repo_root / "reference-implementation" / "src" / "ski_model" / "verdicts.py").read_text()
    for verdict in REQUIRED_VERDICTS:
        assert f'{verdict} = "{verdict}"' in src, f"verdicts.py is missing {verdict}"
    for prohibited in PROHIBITED_VERDICTS:
        bare = f'{prohibited} = "{prohibited}"'
        assert bare not in src, f"verdicts.py still defines bare {prohibited!r}"
