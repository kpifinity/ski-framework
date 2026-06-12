-- ============================================================================
-- SKI Framework v3.0 — Migration 0002: signed LLM transcripts + envelope JSON
-- ============================================================================
-- PR 11 (spec v3.0 §6): expand the audit ledger so every verdict can be
-- independently replayed. Adds:
--
--   * envelope_json     -- the full V3VerdictEnvelope (jsonb)
--   * envelope_hash     -- sha256:<hex> over canonical envelope; extends the
--                          hash chain so an auditor can prove the envelope
--                          they received matches the envelope we stored.
--   * transcript_json   -- the LLMTranscript (jsonb)
--   * transcript_signature  -- detached ed25519 signature over the
--                              request_hash || "|" || response_hash bytes.
--   * signing_key_id    -- sha256:<hex> of the public key that signed; lets
--                          auditors look up the correct key during rotation.
--   * verifier_status   -- denormalised for fast querying / alerting.
--
-- Also relaxes the legacy ``track`` CHECK so v3 evaluator entries are
-- accepted. The v2 values ('symbolic', 'llm') remain valid; v3 introduces
-- ('v3-evaluator',). PR 12 will repurpose ``track`` entirely as part of the
-- agreement-monitor work; until then it stays string-valued.
--
-- Forward-only migration. The append-only triggers in append_only.sql
-- continue to block UPDATE/DELETE on this table.
--
-- IDEMPOTENT. As of PR 15, ``schema.sql`` (the fresh-deploy baseline) also
-- creates these columns and constraints. This migration is then mounted as
-- ``03-transcript-columns.sql`` in docker-compose so initdb runs it after
-- the baseline; every ALTER below is guarded with IF [NOT] EXISTS so it is
-- a no-op against a fresh v3 schema. The migration is still required for
-- operators upgrading an existing v0.2.x ledger that has only the v2.1
-- baseline columns.
-- ============================================================================

ALTER TABLE ledger_entries
    ADD COLUMN IF NOT EXISTS envelope_json JSONB,
    ADD COLUMN IF NOT EXISTS envelope_hash CHAR(71),               -- "sha256:" + 64 hex
    ADD COLUMN IF NOT EXISTS transcript_json JSONB,
    ADD COLUMN IF NOT EXISTS transcript_signature TEXT,
    ADD COLUMN IF NOT EXISTS signing_key_id CHAR(71),
    ADD COLUMN IF NOT EXISTS verifier_status TEXT;

-- Drop the old track CHECK; v3 uses richer track strings.
ALTER TABLE ledger_entries
    DROP CONSTRAINT IF EXISTS ledger_entries_track_check;

-- Add a permissive replacement that still rules out empty strings.
ALTER TABLE ledger_entries
    ADD CONSTRAINT ledger_entries_track_check
    CHECK (track IS NULL OR length(track) > 0);

-- Verifier-status enum at the SQL layer mirrors VerifierStatus from
-- ski_model.v3.envelope. Permits NULL so historical entries remain valid.
-- DROP-then-ADD makes the migration safe to re-run against a fresh v3
-- baseline (where schema.sql already declares this constraint inline).
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

-- Helpful index for verifier-status alerting (PR 12 builds on this).
CREATE INDEX IF NOT EXISTS idx_ledger_verifier_status
    ON ledger_entries (verifier_status, timestamp)
    WHERE verifier_status IS NOT NULL;

-- Helpful index for transcript audit lookups.
CREATE INDEX IF NOT EXISTS idx_ledger_signing_key_id
    ON ledger_entries (signing_key_id)
    WHERE signing_key_id IS NOT NULL;
