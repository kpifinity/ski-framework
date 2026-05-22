-- ============================================================================
-- SKI Framework v2.1 — Append-Only Enforcement
-- ============================================================================
-- The audit ledger must be append-only. We refuse UPDATE and DELETE on
-- ledger_entries at the database level via triggers. The application is
-- permitted to INSERT only.
--
-- A read-only "audit_reader" role is also created — operators should grant
-- SELECT to BI/reporting users via that role rather than the writer.
-- ============================================================================

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

-- Read-only role for reporting consumers.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_audit_reader') THEN
        CREATE ROLE ski_audit_reader NOLOGIN;
    END IF;
END$$;

GRANT USAGE ON SCHEMA public TO ski_audit_reader;
GRANT SELECT ON ledger_entries, coverage_register, ledger_summary,
    ledger_chain_linkage TO ski_audit_reader;
