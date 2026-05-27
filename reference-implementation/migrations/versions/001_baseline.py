"""v0.1 baseline — ledger_entries + append_only triggers

Revision ID: 001_baseline
Revises:
Create Date: 2026-05-23 00:00:00.000000

This migration captures the v0.1.0-alpha schema exactly as it shipped.
On greenfield deployments it creates the ledger schema. On v0.1
deployments upgrading to v0.2 it is a no-op (the tables already exist;
the CREATE TABLE IF NOT EXISTS / DROP TRIGGER IF EXISTS / CREATE
TRIGGER pattern is idempotent).

The SQL is identical to what shipped in
reference-implementation/src/ledger/schema.sql and append_only.sql in
v0.1.0-alpha. Keeping the canonical text inline here (rather than
sourcing the .sql files at migration time) makes the migration
self-contained and reviewable in isolation.
"""

from __future__ import annotations

from alembic import op

revision: str = "001_baseline"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


LEDGER_ENTRIES_DDL = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id BIGSERIAL PRIMARY KEY,
    sequence_number BIGINT UNIQUE NOT NULL,
    previous_hash CHAR(64) NOT NULL,
    entry_hash CHAR(64) NOT NULL UNIQUE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verdict TEXT NOT NULL CHECK (
        verdict IN ('CLEAR', 'FLAG', 'NULL_UNMAPPED', 'NULL_STALE', 'DISCRETIONARY')
    ),
    telemetry_id TEXT NOT NULL,
    telemetry_hash CHAR(64) NOT NULL,
    rule_id TEXT,
    knowledge_graph_version TEXT,
    ski_model_version TEXT NOT NULL,
    reasoning TEXT,
    track TEXT CHECK (track IS NULL OR track IN ('symbolic', 'llm')),
    escalation_status TEXT,
    escalation_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_ledger_sequence ON ledger_entries (sequence_number);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_verdict_timestamp ON ledger_entries (verdict, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_telemetry_id ON ledger_entries (telemetry_id);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_rule_id ON ledger_entries (rule_id);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_kg_version ON ledger_entries (knowledge_graph_version);",
]

VIEWS_DDL = """
CREATE OR REPLACE VIEW coverage_register AS
SELECT
    sequence_number, timestamp, verdict, telemetry_id,
    rule_id, knowledge_graph_version, reasoning
FROM ledger_entries
WHERE verdict IN ('NULL_UNMAPPED', 'NULL_STALE');

CREATE OR REPLACE VIEW ledger_summary AS
SELECT
    DATE_TRUNC('day', timestamp) AS day,
    verdict,
    COUNT(*) AS count,
    COUNT(*) FILTER (WHERE escalation_status IS NOT NULL) AS escalated
FROM ledger_entries
GROUP BY DATE_TRUNC('day', timestamp), verdict
ORDER BY day DESC;

CREATE OR REPLACE VIEW ledger_chain_linkage AS
SELECT
    sequence_number, entry_hash, previous_hash,
    LAG(entry_hash) OVER (ORDER BY sequence_number) AS expected_previous_hash,
    (sequence_number = 1 OR LAG(entry_hash) OVER (ORDER BY sequence_number) = previous_hash) AS chain_link_valid,
    timestamp
FROM ledger_entries
ORDER BY sequence_number;
"""

APPEND_ONLY_DDL = """
CREATE OR REPLACE FUNCTION ledger_block_update_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries is append-only; % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ledger_block_update ON ledger_entries;
CREATE TRIGGER ledger_block_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW
    EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS ledger_block_delete ON ledger_entries;
CREATE TRIGGER ledger_block_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW
    EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS ledger_block_truncate ON ledger_entries;
CREATE TRIGGER ledger_block_truncate
    BEFORE TRUNCATE ON ledger_entries
    EXECUTE FUNCTION ledger_block_update_delete();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_audit_reader') THEN
        CREATE ROLE ski_audit_reader NOLOGIN;
    END IF;
END$$;

GRANT USAGE ON SCHEMA public TO ski_audit_reader;
GRANT SELECT ON ledger_entries, coverage_register, ledger_summary, ledger_chain_linkage TO ski_audit_reader;
"""


def upgrade() -> None:
    op.execute(LEDGER_ENTRIES_DDL)
    for sql in INDEXES_DDL:
        op.execute(sql)
    op.execute(VIEWS_DDL)
    op.execute(APPEND_ONLY_DDL)


def downgrade() -> None:
    # Downgrading the baseline drops the entire ledger. This is an
    # irreversible operation and should only be used on dev databases.
    op.execute("DROP VIEW IF EXISTS ledger_chain_linkage")
    op.execute("DROP VIEW IF EXISTS ledger_summary")
    op.execute("DROP VIEW IF EXISTS coverage_register")
    op.execute("DROP TABLE IF EXISTS ledger_entries CASCADE")
    op.execute("DROP FUNCTION IF EXISTS ledger_block_update_delete() CASCADE")
    # Note: ski_audit_reader role is intentionally NOT dropped (might be in use).
