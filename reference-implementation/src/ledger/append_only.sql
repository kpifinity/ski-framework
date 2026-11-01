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
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
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

-- Ledger format 5 (v3.3.0): signing keys and checkpoints are append-only too.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['ledger_signing_keys', 'ledger_checkpoints'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_update', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW '
                           'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_update', t);
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_delete', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW '
                           'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_delete', t);
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_block_truncate', t);
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I '
                           'EXECUTE FUNCTION ledger_block_update_delete()', t || '_block_truncate', t);
        END IF;
    END LOOP;
END$$;

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
DO $$
BEGIN
    IF to_regclass('ledger_checkpoints') IS NOT NULL THEN
        GRANT SELECT ON ledger_signing_keys, ledger_checkpoints TO ski_audit_reader;
    END IF;
END$$;

-- ----------------------------------------------------------------------------
-- Least-privilege runtime role (v3.2.0). The SKI Model connects as
-- ski_ledger_writer, never as the schema owner / bootstrap superuser:
-- it may append (INSERT) and read (SELECT) the ledger, and nothing else.
-- No UPDATE, DELETE, TRUNCATE, REFERENCES or TRIGGER privilege, and it does
-- not own the table, so it cannot ALTER TABLE ... DISABLE TRIGGER, drop the
-- append-only triggers or change the schema. Schema and migrations run as
-- the owner (POSTGRES_USER), as this file does.
--
-- Created with LOGIN but WITHOUT a password, so it cannot authenticate until
-- one is set: docker-compose / Helm do that on first init via
-- ledger_writer_login.sh (from SKI_LEDGER_WRITER_PASSWORD); elsewhere run
--   ALTER ROLE ski_ledger_writer PASSWORD '<secret>';
-- as the owner. Re-running this file is idempotent and resets the writer's
-- table privileges to exactly the set below.
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ski_ledger_writer') THEN
        CREATE ROLE ski_ledger_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
END$$;

GRANT USAGE ON SCHEMA public TO ski_ledger_writer;
REVOKE ALL ON ledger_entries FROM ski_ledger_writer;
GRANT SELECT, INSERT ON ledger_entries TO ski_ledger_writer;

-- nextval() for the BIGSERIAL id. USAGE only (no UPDATE => no setval()).
DO $$
DECLARE
    seq TEXT := pg_get_serial_sequence('ledger_entries', 'id');
BEGIN
    IF seq IS NOT NULL THEN
        EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM ski_ledger_writer', seq);
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO ski_ledger_writer', seq);
    END IF;
END$$;

-- Format 5: the writer registers its public key and appends checkpoints.
DO $$
BEGIN
    IF to_regclass('ledger_checkpoints') IS NOT NULL THEN
        REVOKE ALL ON ledger_signing_keys, ledger_checkpoints FROM ski_ledger_writer;
        GRANT SELECT, INSERT ON ledger_signing_keys, ledger_checkpoints TO ski_ledger_writer;
        REVOKE ALL ON SEQUENCE ledger_checkpoints_id_seq FROM ski_ledger_writer;
        GRANT USAGE ON SEQUENCE ledger_checkpoints_id_seq TO ski_ledger_writer;
    END IF;
END$$;

-- PostgreSQL 15+ already denies CREATE on schema public to PUBLIC; make
-- older servers match, so the writer cannot create objects there either.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
