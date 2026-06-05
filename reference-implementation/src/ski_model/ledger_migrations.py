"""Idempotent startup migration runner for the v3 audit ledger.

Probes ``ledger_entries`` for the v3 audit-trail columns; if any are
missing, applies the ``0002_transcript_columns`` migration in-place.

**Why this exists.** Postgres' ``/docker-entrypoint-initdb.d/`` scripts
only run on first init (when the data directory is empty). PR 15
rewrote ``schema.sql`` to the v3 baseline and added the migration as a
defence-in-depth mount, but neither path helps an operator who:

1. Brought up v3.0.0 with the v2.1 ``schema.sql`` (the bug PR 15
   fixed for fresh deployments).
2. Pulled v3.0.1+ and rebuilt the stack.
3. Kept the existing Postgres volume.

Postgres remembers that volume as "already initialised" and skips
every init script, so the new ``schema.sql`` and the mounted migration
never run. The runtime then fails at evaluation time with
``column "envelope_json" of relation "ledger_entries" does not exist``.

This module closes that gap. The runtime probes the schema on startup
and applies the migration if needed. The migration SQL is embedded
here (single source of truth at the Python layer; the canonical
``.sql`` file is mounted into Postgres for fresh installs). A
durability conformance test pins the two against each other so they
cannot drift.

**Operator controls.** The check is on by default. Set
``SKI_AUTOMIGRATE=false`` to opt out — in that mode, if the v3 columns
are missing the server logs a loud error pointing at
``docs/migrations.md`` and refuses to serve.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# The v3 audit-trail columns the runtime requires on ``ledger_entries``.
# Source of truth: ``reference-implementation/src/ledger/schema.sql`` (PR 15
# v3 baseline) and ``migrations/0002_transcript_columns.sql``.
# ----------------------------------------------------------------------------

_REQUIRED_V3_COLUMNS: Final[tuple[str, ...]] = (
    "envelope_json",
    "envelope_hash",
    "transcript_json",
    "transcript_signature",
    "signing_key_id",
    "verifier_status",
)

# ----------------------------------------------------------------------------
# Embedded migration SQL. This is byte-for-byte equivalent to
# ``reference-implementation/src/ledger/migrations/0002_transcript_columns.sql``
# (excluding leading comment block). The durability conformance test
# ``test_ledger_migrations_runner.py`` greps both for the same
# ``ADD COLUMN IF NOT EXISTS`` statements so they cannot drift.
# ----------------------------------------------------------------------------

_V3_LEDGER_MIGRATION_SQL: Final[str] = """
ALTER TABLE ledger_entries
    ADD COLUMN IF NOT EXISTS envelope_json JSONB,
    ADD COLUMN IF NOT EXISTS envelope_hash CHAR(71),
    ADD COLUMN IF NOT EXISTS transcript_json JSONB,
    ADD COLUMN IF NOT EXISTS transcript_signature TEXT,
    ADD COLUMN IF NOT EXISTS signing_key_id CHAR(71),
    ADD COLUMN IF NOT EXISTS verifier_status TEXT;

ALTER TABLE ledger_entries
    DROP CONSTRAINT IF EXISTS ledger_entries_track_check;
ALTER TABLE ledger_entries
    ADD CONSTRAINT ledger_entries_track_check
    CHECK (track IS NULL OR length(track) > 0);

ALTER TABLE ledger_entries
    DROP CONSTRAINT IF EXISTS ledger_entries_verifier_status_check;
ALTER TABLE ledger_entries
    ADD CONSTRAINT ledger_entries_verifier_status_check
    CHECK (
        verifier_status IS NULL
        OR verifier_status IN (
            'AGREED',
            'LLM_CONTRADICTION',
            'NEURO_SYMBOLIC_DIVERGENCE',
            'UNVERIFIABLE'
        )
    );

CREATE INDEX IF NOT EXISTS idx_ledger_verifier_status
    ON ledger_entries (verifier_status, timestamp)
    WHERE verifier_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ledger_signing_key_id
    ON ledger_entries (signing_key_id)
    WHERE signing_key_id IS NOT NULL;
"""


class LedgerSchemaError(RuntimeError):
    """Raised when the ledger schema is incompatible and auto-migrate is off."""


async def _missing_v3_columns(engine: AsyncEngine) -> tuple[str, ...]:
    """Return the v3 columns that are NOT present on ``ledger_entries``."""
    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'ledger_entries'
        """
    )
    async with engine.connect() as conn:
        result = await conn.execute(query)
        present = {row[0] for row in result.fetchall()}
    return tuple(col for col in _REQUIRED_V3_COLUMNS if col not in present)


async def ensure_v3_ledger_schema(engine: AsyncEngine) -> None:
    """Probe ``ledger_entries`` and apply 0002 if v3 columns are missing.

    Idempotent: a no-op against a schema that already has the columns.
    Guarded by ``$SKI_AUTOMIGRATE`` — set to ``false`` to disable; if
    disabled and columns are missing, raises :class:`LedgerSchemaError`
    so the server refuses to start with a broken ledger.
    """
    missing = await _missing_v3_columns(engine)
    if not missing:
        logger.info("Ledger schema is at v3; no migration required.")
        return

    automigrate = os.getenv("SKI_AUTOMIGRATE", "true").lower() != "false"

    if not automigrate:
        msg = (
            "Ledger schema is missing v3 columns "
            f"{list(missing)!r} and SKI_AUTOMIGRATE=false. "
            "Apply the migration manually before restarting: "
            '`psql "$LEDGER_DSN" -f '
            "reference-implementation/src/ledger/migrations/"
            "0002_transcript_columns.sql`. "
            "See docs/migrations.md for the full upgrade procedure."
        )
        logger.error(msg)
        raise LedgerSchemaError(msg)

    logger.info(
        "Ledger schema missing v3 columns %r — applying 0002_transcript_columns "
        "in place. Set SKI_AUTOMIGRATE=false to disable this behaviour.",
        list(missing),
    )

    async with engine.begin() as conn:
        await conn.execute(text(_V3_LEDGER_MIGRATION_SQL))

    # Re-probe to confirm the migration succeeded. Defensive against a
    # partial apply (e.g. the operator's role lacks DDL privileges).
    still_missing = await _missing_v3_columns(engine)
    if still_missing:
        raise LedgerSchemaError(
            f"Applied 0002 migration but {still_missing!r} are still missing. "
            "Check the database role has CREATE / ALTER privileges on "
            "ledger_entries, or apply the migration as a privileged user."
        )

    logger.info("Applied 0002_transcript_columns. Ledger schema is now at v3.")


__all__ = [
    "LedgerSchemaError",
    "ensure_v3_ledger_schema",
]
