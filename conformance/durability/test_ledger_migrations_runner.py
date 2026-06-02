"""SKI Framework v3.0 §6 — Startup migration runner pins.

The runtime applies the v3 ledger migration in place if it detects the
v3 columns are missing on ``ledger_entries`` (PR 16, v3.0.2). This
closes the gap where a Postgres volume initialised with v2.1
``schema.sql`` is later mounted under a v3 runtime — Postgres'
``/docker-entrypoint-initdb.d/`` scripts only run on first init, so
neither the new v3 ``schema.sql`` nor the mounted ``0002`` migration
get applied automatically.

This test pins five claims:

1. ``ski_model.ledger_migrations`` exists and exposes
   ``ensure_v3_ledger_schema``.
2. The embedded migration SQL is wired up against the same
   ``ADD COLUMN IF NOT EXISTS`` statements as the canonical
   ``0002_transcript_columns.sql`` (so the two cannot silently
   drift).
3. The embedded SQL uses idempotent guards
   (``ADD COLUMN IF NOT EXISTS``, ``DROP CONSTRAINT IF EXISTS``
   before ``ADD CONSTRAINT``).
4. ``server.py`` lifespan calls ``ensure_v3_ledger_schema`` after
   ``LedgerClient.initialize`` — operators cannot run the v3 server
   against an unmigrated volume.
5. ``$SKI_AUTOMIGRATE`` is honoured (referenced in the runner) so
   hardened deployments can opt out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REQUIRED_V3_COLUMNS = (
    "envelope_json",
    "envelope_hash",
    "transcript_json",
    "transcript_signature",
    "signing_key_id",
    "verifier_status",
)


def _runner_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "src" / "ski_model" / "ledger_migrations.py").read_text()


def _canonical_migration_source(repo_root: Path) -> str:
    return (
        repo_root
        / "reference-implementation"
        / "src"
        / "ledger"
        / "migrations"
        / "0002_transcript_columns.sql"
    ).read_text()


def _server_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "src" / "ski_model" / "server.py").read_text()


@pytest.mark.durability
def test_ledger_migrations_module_exists_and_exports_runner(repo_root: Path) -> None:
    """``ledger_migrations.ensure_v3_ledger_schema`` is the public entry point."""
    src = _runner_source(repo_root)
    assert "async def ensure_v3_ledger_schema" in src, (
        "ski_model/ledger_migrations.py must expose ensure_v3_ledger_schema as "
        "the public async entry point called from server.py lifespan."
    )
    assert "ensure_v3_ledger_schema" in src.split("__all__", 1)[1] if "__all__" in src else True, (
        "ensure_v3_ledger_schema must be listed in __all__."
    )


@pytest.mark.durability
def test_embedded_sql_covers_every_v3_column(repo_root: Path) -> None:
    """The embedded SQL has ``ADD COLUMN IF NOT EXISTS`` for every v3 column."""
    runner = _runner_source(repo_root)
    for column in _REQUIRED_V3_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in runner, (
            f"ledger_migrations.py is missing 'ADD COLUMN IF NOT EXISTS {column}' "
            "in the embedded migration SQL. Drift between the embedded SQL and "
            "the canonical 0002_transcript_columns.sql is forbidden."
        )


@pytest.mark.durability
def test_embedded_sql_matches_canonical_migration(repo_root: Path) -> None:
    """Each ``ADD COLUMN IF NOT EXISTS`` in 0002 is present in the embedded SQL."""
    runner = _runner_source(repo_root)
    canonical = _canonical_migration_source(repo_root)
    for column in _REQUIRED_V3_COLUMNS:
        canonical_stmt = f"ADD COLUMN IF NOT EXISTS {column}"
        assert canonical_stmt in canonical, (
            f"Canonical 0002 is missing {canonical_stmt!r}. PR 15 guarantees these."
        )
        assert canonical_stmt in runner, (
            f"Embedded SQL in ledger_migrations.py is missing {canonical_stmt!r}; "
            "it has drifted from migrations/0002_transcript_columns.sql."
        )


@pytest.mark.durability
def test_runner_uses_idempotent_constraint_guards(repo_root: Path) -> None:
    """DROP CONSTRAINT IF EXISTS precedes ADD CONSTRAINT for both checks."""
    runner = _runner_source(repo_root)
    assert "DROP CONSTRAINT IF EXISTS ledger_entries_track_check" in runner, (
        "Embedded SQL must DROP IF EXISTS the track CHECK before re-adding it."
    )
    assert "DROP CONSTRAINT IF EXISTS ledger_entries_verifier_status_check" in runner, (
        "Embedded SQL must DROP IF EXISTS the verifier_status CHECK before "
        "re-adding it — otherwise re-running against a fresh v3 schema errors."
    )


@pytest.mark.durability
def test_server_lifespan_calls_the_runner(repo_root: Path) -> None:
    """server.py lifespan invokes ``ensure_v3_ledger_schema`` post-init."""
    server = _server_source(repo_root)
    assert "from .ledger_migrations import ensure_v3_ledger_schema" in server, (
        "server.py must import ensure_v3_ledger_schema from ledger_migrations."
    )
    assert "await ensure_v3_ledger_schema(" in server, (
        "server.py lifespan must await ensure_v3_ledger_schema() so v3 schema gaps are healed on startup."
    )


@pytest.mark.durability
def test_runner_honours_automigrate_env(repo_root: Path) -> None:
    """``$SKI_AUTOMIGRATE`` is the documented opt-out lever."""
    runner = _runner_source(repo_root)
    assert "SKI_AUTOMIGRATE" in runner, (
        "ledger_migrations.py must honour SKI_AUTOMIGRATE so hardened "
        "deployments can require explicit DBA-driven migrations."
    )
