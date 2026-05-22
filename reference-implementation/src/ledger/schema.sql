-- ============================================================================
-- SKI Framework v2.1 — Audit Ledger Schema
-- ============================================================================
-- Append-only, hash-chained ledger of evaluation verdicts.
--
-- Notes:
--  * `confidence_level` was REMOVED in v2.1 — confidence scores are
--    architecturally prohibited (B3.1 + Axiom 2 Bounded Determinism).
--  * Verdicts use the five-verdict taxonomy:
--      CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE, DISCRETIONARY.
--  * Append-only enforcement lives in 02-append-only.sql (triggers).
--  * The canonical entry hash is computed by the SKI Model client over the
--    canonical serialization documented in
--    src/ski_model/ledger_client.py::canonical_entry_payload.
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
    track TEXT CHECK (track IS NULL OR track IN ('symbolic', 'llm')),
    escalation_status TEXT,
    escalation_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sequence-number monotonic ordering enforced by application; index ensures
-- the gap-detection query is fast.
CREATE INDEX IF NOT EXISTS idx_ledger_sequence ON ledger_entries (sequence_number);
CREATE INDEX IF NOT EXISTS idx_ledger_verdict_timestamp ON ledger_entries (verdict, timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_telemetry_id ON ledger_entries (telemetry_id);
CREATE INDEX IF NOT EXISTS idx_ledger_rule_id ON ledger_entries (rule_id);
CREATE INDEX IF NOT EXISTS idx_ledger_kg_version ON ledger_entries (knowledge_graph_version);

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
