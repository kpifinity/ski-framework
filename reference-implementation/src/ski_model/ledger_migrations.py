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
from sqlalchemy.exc import DBAPIError
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
            "Apply the migration manually, as the schema OWNER (POSTGRES_USER), "
            "before restarting -- not with the runtime's LEDGER_DSN, which uses the "
            "least-privilege ski_ledger_writer role since v3.2.0: "
            '`psql "<owner DSN>" -f '
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

    try:
        async with engine.begin() as conn:
            await conn.execute(text(_V3_LEDGER_MIGRATION_SQL))
    except DBAPIError as exc:
        # Expected when the runtime connects as ski_ledger_writer (v3.2.0
        # default): it has no DDL rights by design. Fail closed, with the fix.
        raise LedgerSchemaError(
            f"Ledger schema is missing v3 columns {list(missing)!r} and the runtime's "
            f"database role cannot add them ({exc.orig!r}). This is expected when "
            "LEDGER_DSN uses the least-privilege ski_ledger_writer role. Apply "
            "reference-implementation/src/ledger/migrations/0002_transcript_columns.sql "
            "as the schema OWNER, then restart."
        ) from exc

    # Re-probe to confirm the migration succeeded. Defensive against a
    # partial apply (e.g. the operator's role lacks DDL privileges).
    still_missing = await _missing_v3_columns(engine)
    if still_missing:
        raise LedgerSchemaError(
            f"Applied 0002 migration but {still_missing!r} are still missing. "
            "Apply the migration as the schema owner (the runtime's "
            "ski_ledger_writer role has no DDL rights by design)."
        )

    logger.info("Applied 0002_transcript_columns. Ledger schema is now at v3.")


# ----------------------------------------------------------------------------
# Ledger format 5 (v3.3.0): byte-for-byte the body of
# ``reference-implementation/src/ledger/migrations/0003_ledger_v5.sql`` below
# its header comment (pinned by test_ledger_migrations.py).
# ----------------------------------------------------------------------------
_V5_LEDGER_MIGRATION_SQL: Final[str] = """
ALTER TABLE ledger_entries
    ADD COLUMN IF NOT EXISTS tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS kg_version_hash CHAR(71),
    ADD COLUMN IF NOT EXISTS model_weight_hash CHAR(71),
    ADD COLUMN IF NOT EXISTS schema_version TEXT,
    ADD COLUMN IF NOT EXISTS verdict_signature TEXT,
    ADD COLUMN IF NOT EXISTS verdict_signing_key_id CHAR(71);

CREATE TABLE IF NOT EXISTS ledger_signing_keys (
    key_id CHAR(71) PRIMARY KEY,
    public_key_pem TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ledger_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    tree_size BIGINT NOT NULL CHECK (tree_size > 0),
    root_hash CHAR(64) NOT NULL,
    last_entry_hash CHAR(64) NOT NULL,
    created_at TEXT NOT NULL,
    signing_key_id CHAR(71) NOT NULL,
    signature TEXT NOT NULL,
    tsa_url TEXT,
    tsa_response BYTEA,
    UNIQUE (tenant_id, tree_size)
);

CREATE OR REPLACE FUNCTION ledger_block_update_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['ledger_signing_keys', 'ledger_checkpoints'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_update', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW '
                       'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_update', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_delete', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW '
                       'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_delete', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_truncate', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I '
                       'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_truncate', t);
    END LOOP;
END$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_ledger_writer') THEN
        REVOKE ALL ON ledger_signing_keys, ledger_checkpoints FROM ski_ledger_writer;
        GRANT SELECT, INSERT ON ledger_signing_keys, ledger_checkpoints TO ski_ledger_writer;
        REVOKE ALL ON SEQUENCE ledger_checkpoints_id_seq FROM ski_ledger_writer;
        GRANT USAGE ON SEQUENCE ledger_checkpoints_id_seq TO ski_ledger_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_audit_reader') THEN
        GRANT SELECT ON ledger_signing_keys, ledger_checkpoints TO ski_audit_reader;
    END IF;
END$$;
"""

_REQUIRED_V5_COLUMNS: Final[tuple[str, ...]] = (
    "tenant_id",
    "kg_version_hash",
    "model_weight_hash",
    "schema_version",
    "verdict_signature",
    "verdict_signing_key_id",
)
_V5_TABLES: Final[tuple[str, ...]] = ("ledger_signing_keys", "ledger_checkpoints")


async def _has_v5_schema(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        present = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ledger_entries'"
                    )
                )
            ).fetchall()
        }
        tables = [
            (await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar()
            for table in _V5_TABLES
        ]
    return all(col in present for col in _REQUIRED_V5_COLUMNS) and all(t is not None for t in tables)


async def ensure_v5_ledger_schema(engine: AsyncEngine) -> bool:
    """True when the ledger can take format-5 entries, applying 0003 if missing and allowed.

    Unlike the v3 columns, format 5 is not required to serve: without it the
    runtime keeps writing format-4 entries (still evidence-chained) and makes
    no checkpoints, and says so at WARN until 0003 is applied as the owner.
    """
    if await _has_v5_schema(engine):
        logger.info("Ledger schema is at format 5.")
        return True
    remedy = (
        "Apply reference-implementation/src/ledger/migrations/0003_ledger_v5.sql as the schema "
        "OWNER and restart. Until then entries are written in ledger format 4 (no spec §7.1 "
        "columns, no verdict signatures) and no checkpoints are made."
    )
    if os.getenv("SKI_AUTOMIGRATE", "true").lower() == "false":
        logger.warning("Ledger schema is not at format 5 and SKI_AUTOMIGRATE=false. %s", remedy)
        return False
    try:
        async with engine.begin() as conn:
            await conn.execute(text(_V5_LEDGER_MIGRATION_SQL))
    except DBAPIError as exc:
        logger.warning(
            "Ledger schema is not at format 5 and the runtime's role cannot migrate it (%r; expected "
            "for ski_ledger_writer). %s",
            exc.orig,
            remedy,
        )
        return False
    if not await _has_v5_schema(engine):
        logger.warning("Applied 0003_ledger_v5 but the schema is still not at format 5. %s", remedy)
        return False
    logger.info("Applied 0003_ledger_v5. Ledger schema is now at format 5.")
    return True


__all__ = [
    "LedgerSchemaError",
    "ensure_v3_ledger_schema",
    "ensure_v5_ledger_schema",
]
