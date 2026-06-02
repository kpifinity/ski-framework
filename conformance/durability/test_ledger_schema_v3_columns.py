"""SKI Framework v3.0 §6 — Ledger schema v3 baseline.

The fresh-deployment ledger schema MUST declare the six v3 audit-trail
columns directly so a clean Postgres instance can persist a
``V3VerdictEnvelope`` and its signed ``LLMTranscript`` without an
out-of-band migration step.

This is the regression guard for the PR 15 fix-forward. Before PR 15
the runtime would fail at evaluation time with
``column "envelope_json" of relation "ledger_entries" does not exist``
because docker-compose's ``/docker-entrypoint-initdb.d/01-schema.sql``
mount carried only the v2.1 baseline; the v3 migration
``0002_transcript_columns.sql`` was never executed on fresh deployments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REQUIRED_V3_LEDGER_COLUMNS = {
    "envelope_json",
    "envelope_hash",
    "transcript_json",
    "transcript_signature",
    "signing_key_id",
    "verifier_status",
}

_REQUIRED_VERIFIER_STATUSES = {
    "AGREED",
    "LLM_CONTRADICTION",
    "NEURO_SYMBOLIC_DIVERGENCE",
    "UNVERIFIABLE",
}


def _schema_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "src" / "ledger" / "schema.sql").read_text()


def _compose_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "docker-compose.yml").read_text()


@pytest.mark.durability
def test_schema_declares_all_v3_audit_trail_columns(repo_root: Path) -> None:
    """Every v3 audit-trail column is declared on ``ledger_entries`` (spec §6)."""
    schema = _schema_source(repo_root)
    missing = {col for col in _REQUIRED_V3_LEDGER_COLUMNS if col not in schema}
    assert not missing, (
        f"schema.sql is missing v3 audit-trail columns: {sorted(missing)!r}. "
        "PR 15 added these to the fresh-deploy baseline; if they reappear "
        "as 'missing', the v2.1 schema was restored by accident — fresh "
        "deployments will fail to persist V3VerdictEnvelopes."
    )


@pytest.mark.durability
def test_schema_constrains_verifier_status_to_spec_enum(repo_root: Path) -> None:
    """``verifier_status`` is restricted to the four spec §4.5 values (or NULL)."""
    schema = _schema_source(repo_root)
    for status in _REQUIRED_VERIFIER_STATUSES:
        assert f"'{status}'" in schema, (
            f"schema.sql verifier_status CHECK is missing {status!r}; "
            "the four-status taxonomy per spec §4.5 must be exhaustively "
            "constrained at the DB layer."
        )


@pytest.mark.durability
def test_schema_header_is_v3(repo_root: Path) -> None:
    """The schema header reads v3.0, not v2.1. Header drift is a smell."""
    schema = _schema_source(repo_root)
    head = "\n".join(schema.splitlines()[:5])
    assert "v3.0" in head, f"schema.sql header does not mention 'v3.0'. Current header:\n{head}"
    assert "v2.1" not in head, (
        "schema.sql header still mentions 'v2.1' — the fresh-deploy "
        "baseline is now v3.0; the v2.1 label is misleading."
    )


@pytest.mark.durability
def test_docker_compose_mounts_transcript_columns_migration(repo_root: Path) -> None:
    """docker-compose mounts the 0002 migration into initdb (belt-and-braces)."""
    compose = _compose_source(repo_root)
    assert "0002_transcript_columns.sql" in compose, (
        "docker-compose.yml no longer mounts migrations/0002_transcript_columns.sql "
        "into /docker-entrypoint-initdb.d. PR 15 added this as a defence-in-depth "
        "mount so initdb runs the migration even if schema.sql drifts. The "
        "migration is idempotent on a clean v3 schema; remove only with a "
        "replacement plan."
    )


@pytest.mark.durability
def test_transcript_columns_migration_is_idempotent(repo_root: Path) -> None:
    """The 0002 migration uses IF [NOT] EXISTS so re-running is safe."""
    migration = (
        repo_root
        / "reference-implementation"
        / "src"
        / "ledger"
        / "migrations"
        / "0002_transcript_columns.sql"
    ).read_text()
    assert "ADD COLUMN IF NOT EXISTS" in migration, (
        "0002 must use ADD COLUMN IF NOT EXISTS so it is safe to re-run "
        "against a fresh v3 baseline that already has the columns."
    )
    # The verifier_status CHECK must be drop-then-add or the migration errors
    # when re-applied against a fresh schema that already declared it inline.
    assert "DROP CONSTRAINT IF EXISTS ledger_entries_verifier_status_check" in migration, (
        "0002 must DROP IF EXISTS the verifier_status check before adding it "
        "so re-running against a fresh v3 schema is a no-op, not a conflict."
    )
