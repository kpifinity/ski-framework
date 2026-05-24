-- ============================================================================
-- SKI Framework v0.2.0 — Telemetry buffer schema (RFC 0001)
-- ============================================================================
-- The telemetry buffer stores recent telemetry records so the Symbolic
-- Evaluator can answer time-window predicates (window_count, window_sum,
-- window_avg, since_last, debounce, requires_recent_within_seconds).
--
-- Design choices (see docs/RFCs/0001-stateful-evaluation.md):
--   * Postgres-native; no new infra dependency.
--   * Partitioned by telemetry_ts (RANGE) so retention is a partition drop,
--     not a row-by-row DELETE (DELETE would be blocked by the append-only
--     trigger anyway).
--   * Append-only enforced by triggers reused from append_only.sql.
--   * Per-tenant retention via the `tenants` table; no hard-coded default.
--   * `telemetry_ts` is the authoritative clock — never wall-clock at
--     arrival. Replay depends on this.
-- ============================================================================

-- Tenants registry. Operators MUST insert at least one row before any
-- v0.2 evaluation runs. Migration 002 inserts a 'default' row for
-- backwards compatibility with single-tenant v0.1 deployments.
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
    'operators declare retention explicitly. See docs/RFCs/0001-stateful-evaluation.md.';

-- ----------------------------------------------------------------------------
-- Telemetry buffer — partitioned by telemetry_ts.
-- ----------------------------------------------------------------------------

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

COMMENT ON TABLE telemetry_buffer IS
    'Append-only telemetry buffer used by the Symbolic Evaluator for '
    'stateful predicates. telemetry_ts is the authoritative clock for '
    'replay determinism.';

-- Primary lookup index for window queries.
CREATE INDEX IF NOT EXISTS idx_buffer_subject_ts
    ON telemetry_buffer (tenant_id, subject, telemetry_ts);

-- Secondary index for cross-referencing to the ledger via measurement_hash.
CREATE INDEX IF NOT EXISTS idx_buffer_measurement_hash
    ON telemetry_buffer (tenant_id, measurement_hash);

-- ----------------------------------------------------------------------------
-- Default partitions covering the next year, monthly.
-- Operators are expected to add new partitions via the retention/rotation job.
-- (Migration 002 will create today's partition explicitly; this DDL is
--  illustrative of the rotation pattern.)
-- ----------------------------------------------------------------------------

-- Example partition for 2026-05 (creation deferred to the migration).
-- CREATE TABLE telemetry_buffer_2026_05 PARTITION OF telemetry_buffer
--     FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

-- ----------------------------------------------------------------------------
-- Append-only enforcement (same function as ledger_entries).
-- ----------------------------------------------------------------------------

DROP TRIGGER IF EXISTS buffer_block_update ON telemetry_buffer;
CREATE TRIGGER buffer_block_update
    BEFORE UPDATE ON telemetry_buffer
    FOR EACH ROW
    EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS buffer_block_delete ON telemetry_buffer;
CREATE TRIGGER buffer_block_delete
    BEFORE DELETE ON telemetry_buffer
    FOR EACH ROW
    EXECUTE FUNCTION ledger_block_update_delete();

DROP TRIGGER IF EXISTS buffer_block_truncate ON telemetry_buffer;
CREATE TRIGGER buffer_block_truncate
    BEFORE TRUNCATE ON telemetry_buffer
    EXECUTE FUNCTION ledger_block_update_delete();

-- ----------------------------------------------------------------------------
-- Retention helper — drops partitions older than the tenant's retention.
--
-- This is the ONLY supported way to remove data from the buffer. It works by
-- dropping whole partitions, which bypasses the per-row append-only trigger.
-- It is restricted to a dedicated role so operators can audit who invoked it.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION drop_buffer_partitions_older_than(cutoff TIMESTAMPTZ)
RETURNS INT AS $$
DECLARE
    part RECORD;
    dropped INT := 0;
BEGIN
    -- Audit: every partition drop emits a NOTICE so log scrapers catch it.
    FOR part IN
        SELECT inhrelid::regclass AS partition_name,
               pg_get_expr(c.relpartbound, c.oid) AS partition_bound
        FROM pg_inherits
        JOIN pg_class c ON c.oid = inhrelid
        WHERE inhparent = 'telemetry_buffer'::regclass
    LOOP
        -- Parse partition upper bound from the bound expression.
        -- Naive parse — operators should review before relying on prod.
        IF part.partition_bound ~* 'TO \(''([^'']+)''\)'
           AND substring(part.partition_bound from 'TO \(''([^'']+)''\)')::TIMESTAMPTZ <= cutoff
        THEN
            RAISE NOTICE 'Dropping buffer partition: %', part.partition_name;
            EXECUTE format('DROP TABLE %s', part.partition_name);
            dropped := dropped + 1;
        END IF;
    END LOOP;
    RETURN dropped;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

REVOKE EXECUTE ON FUNCTION drop_buffer_partitions_older_than(TIMESTAMPTZ) FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_buffer_admin') THEN
        CREATE ROLE ski_buffer_admin NOLOGIN;
    END IF;
END$$;

GRANT EXECUTE ON FUNCTION drop_buffer_partitions_older_than(TIMESTAMPTZ) TO ski_buffer_admin;

-- ----------------------------------------------------------------------------
-- Read-only access for reporting (existing ski_audit_reader role).
-- ----------------------------------------------------------------------------

GRANT SELECT ON tenants, telemetry_buffer TO ski_audit_reader;

-- ----------------------------------------------------------------------------
-- View: per-tenant buffer summary for dashboards.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW buffer_summary AS
SELECT
    tenant_id,
    COUNT(*)                                    AS row_count,
    MIN(telemetry_ts)                           AS oldest_record,
    MAX(telemetry_ts)                           AS newest_record,
    COUNT(DISTINCT subject)                     AS distinct_subjects,
    pg_size_pretty(SUM(pg_column_size(measurement))) AS total_measurement_bytes
FROM telemetry_buffer
GROUP BY tenant_id;

GRANT SELECT ON buffer_summary TO ski_audit_reader;
