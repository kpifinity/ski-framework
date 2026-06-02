-- ============================================================================
-- SKI Framework v3.0 — Audit Ledger Schema
-- ============================================================================
-- Append-only, hash-chained ledger of evaluation verdicts.
--
-- This file is the **fresh-deployment baseline** for the v3 ledger. It is
-- mounted at /docker-entrypoint-initdb.d/01-schema.sql by docker-compose, so
-- every Postgres instance brought up against a clean volume initialises with
-- the v3 column set. Existing v0.2.x ledgers are upgraded via
-- ``migrations/0002_transcript_columns.sql`` (idempotent — see the migration
-- header).
--
-- Notes:
--  * Confidence scoring is REMOVED in v3 (and was already gone in v2.1) —
--    confidence scores are architecturally prohibited (Axiom 2).
--  * Verdicts use the five-verdict taxonomy:
--      CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE, DISCRETIONARY.
--  * Append-only enforcement lives in append_only.sql (triggers).
--  * The canonical entry hash is computed by the SKI Model client over the
--    canonical serialization documented in
--    src/ski_model/ledger_client.py::canonical_entry_payload.
--  * The v3 envelope (V3VerdictEnvelope) and the signed LLM transcript
--    (LLMTranscript) are persisted alongside the row so any auditor can
--    independently reconstruct the verdict from the recorded provenance
--    (spec v3.0 §6).
-- ============================================================================

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
    -- ``track`` is permissive in v3 — v2 values ('symbolic', 'llm') remain
    -- valid for historical rows; v3 evaluator entries use 'v3-evaluator'.
    -- The check is just "non-empty if present".
    track TEXT CHECK (track IS NULL OR length(track) > 0),
    escalation_status TEXT,
    escalation_notes TEXT,
    -- v3 audit-trail columns (spec v3.0 §6).
    --   envelope_json     -- the full V3VerdictEnvelope (jsonb)
    --   envelope_hash     -- sha256:<hex> over canonical envelope; lets an
    --                        auditor prove the envelope they received matches
    --                        the envelope stored here.
    --   transcript_json   -- the LLMTranscript (jsonb)
    --   transcript_signature -- detached ed25519 signature over the
    --                           request_hash || "|" || response_hash bytes.
    --   signing_key_id    -- sha256:<hex> of the public key that signed.
    --                        Supports key rotation: auditors look up the
    --                        correct verification key by this ID.
    --   verifier_status   -- denormalised SymbolicVerifier outcome for fast
    --                        querying / agreement-monitor alerting.
    envelope_json JSONB,
    envelope_hash CHAR(71),               -- "sha256:" + 64 hex
    transcript_json JSONB,
    transcript_signature TEXT,
    signing_key_id CHAR(71),
    verifier_status TEXT CHECK (
        verifier_status IS NULL
        OR verifier_status IN (
            'AGREED',
            'LLM_CONTRADICTION',
            'NEURO_SYMBOLIC_DIVERGENCE',
            'UNVERIFIABLE'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sequence-number monotonic ordering enforced by application; index ensures
-- the gap-detection query is fast.
CREATE INDEX IF NOT EXISTS idx_ledger_sequence ON ledger_entries (sequence_number);
CREATE INDEX IF NOT EXISTS idx_ledger_verdict_timestamp ON ledger_entries (verdict, timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_telemetry_id ON ledger_entries (telemetry_id);
CREATE INDEX IF NOT EXISTS idx_ledger_rule_id ON ledger_entries (rule_id);
CREATE INDEX IF NOT EXISTS idx_ledger_kg_version ON ledger_entries (knowledge_graph_version);

-- v3 indexes for audit-trail querying.
CREATE INDEX IF NOT EXISTS idx_ledger_verifier_status
    ON ledger_entries (verifier_status, timestamp)
    WHERE verifier_status IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_signing_key_id
    ON ledger_entries (signing_key_id)
    WHERE signing_key_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Coverage Register — NULL_UNMAPPED / NULL_STALE entries denormalised for
-- compliance reporting.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW coverage_register AS
SELECT
    sequence_number,
    timestamp,
    verdict,
    telemetry_id,
    rule_id,
    knowledge_graph_version,
    reasoning
FROM ledger_entries
WHERE verdict IN ('NULL_UNMAPPED', 'NULL_STALE');

-- ----------------------------------------------------------------------------
-- Daily verdict roll-up — useful for Grafana dashboards.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ledger_summary AS
SELECT
    DATE_TRUNC('day', timestamp) AS day,
    verdict,
    COUNT(*) AS count,
    COUNT(*) FILTER (WHERE escalation_status IS NOT NULL) AS escalated
FROM ledger_entries
GROUP BY DATE_TRUNC('day', timestamp), verdict
ORDER BY day DESC;

-- ----------------------------------------------------------------------------
-- Chain-integrity helper view.  This view ONLY checks the previous-hash
-- linkage; full integrity verification (recomputing entry hashes from
-- canonical payloads) must use the audit-ledger CLI.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ledger_chain_linkage AS
SELECT
    sequence_number,
    entry_hash,
    previous_hash,
    LAG(entry_hash) OVER (ORDER BY sequence_number) AS expected_previous_hash,
    (
        sequence_number = 1
        OR LAG(entry_hash) OVER (ORDER BY sequence_number) = previous_hash
    ) AS chain_link_valid,
    timestamp
FROM ledger_entries
ORDER BY sequence_number;
