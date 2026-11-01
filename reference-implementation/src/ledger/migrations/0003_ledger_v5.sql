-- ============================================================================
-- SKI Framework v3.3.0 — ledger format 5
-- ============================================================================
-- Upgrades a v3.2.x ledger in place. Idempotent; run as the schema OWNER
-- (POSTGRES_USER), never as ski_ledger_writer:
--
--   psql "<owner DSN>" -f reference-implementation/src/ledger/migrations/0003_ledger_v5.sql
--
-- Adds the spec §7.1 columns and the verdict signature to ledger_entries, and
-- the append-only ledger_signing_keys and ledger_checkpoints tables. Existing
-- rows are not modified: they keep their v3/v4 hashes and verify as before;
-- new rows are written in format 5. The runtime applies this itself on
-- startup when its role may (SKI_AUTOMIGRATE), and otherwise keeps writing
-- format 4 with a warning until it is applied.
--
-- The runtime embeds this SQL (ski_model/ledger_migrations.py); a test pins
-- the two together.
-- ============================================================================

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
