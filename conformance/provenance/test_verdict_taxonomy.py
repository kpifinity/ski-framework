"""SKI Framework v3.0 §4.1 — Verdict taxonomy.

The runtime MUST produce exactly five verdict types: CLEAR, FLAG,
NULL_UNMAPPED, NULL_STALE, DISCRETIONARY. The pre-v2.1 four-verdict
taxonomy (CLEAR / FLAG / NULL / DISCRETIONARY) is non-conformant.

The five-verdict taxonomy is preserved unchanged from v2.1; what changed
in v3 is the envelope around the verdict (see ``test_v3_envelope_shape.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


REQUIRED_VERDICTS = {"CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY"}
PROHIBITED_VERDICTS = {"NULL"}


@pytest.mark.provenance
def test_schema_has_all_five_verdicts(repo_root: Path) -> None:
    """The ledger SQL schema constrains ``verdict`` to the five-verdict set."""
    schema = (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    for verdict in REQUIRED_VERDICTS:
        assert f"'{verdict}'" in schema, f"schema.sql is missing verdict {verdict!r}"


@pytest.mark.provenance
def test_schema_does_not_admit_null_alone(repo_root: Path) -> None:
    """Pre-v2.1 ``NULL`` (without _UNMAPPED/_STALE) must NOT appear in the schema CHECK."""
    schema = (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()
    assert "'NULL'" not in schema, (
        "schema.sql still lists 'NULL' as a verdict — replace with NULL_UNMAPPED/NULL_STALE."
    )


@pytest.mark.provenance
def test_v3_verdict_enum_has_all_five(repo_root: Path) -> None:
    """The reference v3 ``V3Verdict`` enum lists all five canonical verdicts."""
    src = (repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "envelope.py").read_text()
    for verdict in REQUIRED_VERDICTS:
        assert f'{verdict} = "{verdict}"' in src, f"v3/envelope.py V3Verdict enum is missing {verdict}"


@pytest.mark.provenance
def test_v3_verdict_enum_does_not_define_bare_null(repo_root: Path) -> None:
    """The v3 ``V3Verdict`` enum must NOT define a bare ``NULL`` member."""
    src = (repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "envelope.py").read_text()
    for prohibited in PROHIBITED_VERDICTS:
        bare = f'{prohibited} = "{prohibited}"'
        assert bare not in src, (
            f"v3/envelope.py still defines bare {prohibited!r}; use NULL_UNMAPPED/NULL_STALE."
        )


@pytest.mark.provenance
def test_legacy_verdicts_module_is_removed(repo_root: Path) -> None:
    """The v2 ``verdicts.py`` module must be gone — v3 owns the taxonomy."""
    legacy = repo_root / "reference-implementation" / "src" / "ski_model" / "verdicts.py"
    assert not legacy.exists(), (
        "Legacy ski_model/verdicts.py still present. v3 cutover should have removed it; "
        "import V3Verdict from ski_model.v3.envelope instead."
    )
