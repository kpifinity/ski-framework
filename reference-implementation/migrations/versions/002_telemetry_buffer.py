"""v0.2 telemetry buffer + tenants + schema_version

Revision ID: 002_telemetry_buffer
Revises: 001_baseline
Create Date: 2026-05-23 00:01:00.000000

Introduces the stateful-evaluation primitives described in
docs/RFCs/0001-stateful-evaluation.md:

  * `tenants` table — per-tenant retention configuration.
  * `telemetry_buffer` table — append-only, partitioned by telemetry_ts.
  * `schema_version` column on `ledger_entries` — distinguishes v0.1
    (no buffer reference) from v0.2 (buffer-aware) entries.
  * A 'default' tenant row so single-tenant v0.1 deployments upgrade
    without manual configuration.
  * A 'today' partition on telemetry_buffer so the table is immediately
    writable.
  * Backfill: existing ledger rows tagged schema_version='0.1.0'.

DOWNGRADE WARNING: rolling back this migration DROPS telemetry_buffer
and tenants. Snapshot the database first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alembic import op


revision: str = "002_telemetry_buffer"
down_revision: str | None = "001_baseline"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


TENANTS_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id              TEXT PRIMARY KEY,
    display_name           TEXT NOT NULL,
    buffer_retention_days  INT  NOT NULL CHECK (buffer_retention_days > 0),
    max_clock_skew_seconds INT  NOT NULL DEFAULT 60 CHECK (max_clock_skew_seconds >= 0),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tenants IS
    'Per-tenant configuration. There is no default buffer_retention_days; '
    'operators declare retention explicitly.';
"""

BUFFER_DDL = """
CREATE TABLE IF NOT EXISTS telemetry_buffer (
    id               BIGSERIAL,
    tenant_id        TEXT        NOT NULL REFERENCES tenants(tenant_id),
    subject          TEXT        NOT NULL,
    telemetry_id     TEXT        NOT NULL,
    telemetry_ts     TIMESTAMPTZ NOT NULL,
    received_ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    measurement      JSONB       NOT NULL,
    measurement_hash CHAR(64)    NOT NULL,
    schema_version   TEXT        NOT NULL DEFAULT '0.2.0',
    PRIMARY KEY (tenant_id, telemetry_ts, id)
) PARTITION BY RANGE (telemetry_ts);

CREATE INDEX IF NOT EXISTS idx_buffer_subject_ts
    ON telemetry_buffer (tenant_id, subject, telemetry_ts);

CREATE INDEX IF NOT EXISTS idx_buffer_measurement_hash
    ON telemetry_buffer (tenant_id, measurement_hash);
"""

BUFFER_TRIGGERS_DDL = """
DROP TRIGGER IF EXISTS buffer_block_update ON telemetry_buffer;
CREATE TRIGGER buffer_block_update
    BEFORE UPDATE ON telemetry_buffer
    FOR EACH ROW EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS buffer_block_delete ON telemetry_buffer;
CREATE TRIGGER buffer_block_delete
    BEFORE DELETE ON telemetry_buffer
    FOR EACH ROW EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS buffer_block_truncate ON telemetry_buffer;
CREATE TRIGGER buffer_block_truncate
    BEFORE TRUNCATE ON telemetry_buffer
    EXECUTE FUNCTION ledger_block_update_delete();
"""

BUFFER_HELPERS_DDL = """
CREATE OR REPLACE VIEW buffer_summary AS
SELECT
    tenant_id,
    COUNT(*)                       AS row_count,
    MIN(telemetry_ts)              AS oldest_record,
    MAX(telemetry_ts)              AS newest_record,
    COUNT(DISTINCT subject)        AS distinct_subjects
FROM telemetry_buffer
GROUP BY tenant_id;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_buffer_admin') THEN
        CREATE ROLE ski_buffer_admin NOLOGIN;
    END IF;
END$$;

GRANT SELECT ON tenants, telemetry_buffer, buffer_summary TO ski_audit_reader;
"""

LEDGER_SCHEMA_VERSION_DDL = """
ALTER TABLE ledger_entries
    ADD COLUMN IF NOT EXISTS schema_version TEXT;

UPDATE ledger_entries SET schema_version = '0.1.0' WHERE schema_version IS NULL;

ALTER TABLE ledger_entries
    ALTER COLUMN schema_version SET NOT NULL,
    ALTER COLUMN schema_version SET DEFAULT '0.2.0';

CREATE INDEX IF NOT EXISTS idx_ledger_schema_version
    ON ledger_entries (schema_version);
"""

# Bootstrap a 'default' tenant + a partition covering today so a fresh
# deployment is immediately writable. Operators who care about per-tenant
# isolation will rename / add tenants manually.
def _bootstrap_partition_today() -> str:
    today = datetime.now(timezone.utc).date()
    start = today.replace(day=1)
    # Cover the rest of the month plus the next month, to allow time for
    # operators to wire up the rotation job.
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=2)
    elif start.month == 11:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 2)
    name = f"telemetry_buffer_{start.year}_{start.month:02d}"
    return (
        f"CREATE TABLE IF NOT EXISTS {name} "
        f"PARTITION OF telemetry_buffer "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
    )


BOOTSTRAP_DML = """
INSERT INTO tenants (tenant_id, display_name, buffer_retention_days)
VALUES ('default', 'Default (single-tenant bootstrap)', 30)
ON CONFLICT (tenant_id) DO NOTHING;
"""


def upgrade() -> None:
    op.execute(TENANTS_DDL)
    op.execute(BUFFER_DDL)
    op.execute(BUFFER_TRIGGERS_DDL)
    op.execute(BUFFER_HELPERS_DDL)
    op.execute(LEDGER_SCHEMA_VERSION_DDL)
    op.execute(BOOTSTRAP_DML)
    op.execute(_bootstrap_partition_today())


def downgrade() -> None:
    # DROPS USER DATA. Snapshot first.
    op.execute("DROP VIEW IF EXISTS buffer_summary")
    op.execute("DROP TABLE IF EXISTS telemetry_buffer CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_ledger_schema_version")
    op.execute("ALTER TABLE ledger_entries DROP COLUMN IF EXISTS schema_version")
    # ski_buffer_admin role is intentionally retained.
