-- SKI Framework Audit Ledger Schema
-- Immutable, hash-chained ledger for recording verdicts

CREATE TABLE IF NOT EXISTS ledger_entries (
    id SERIAL PRIMARY KEY,
    sequence_number BIGINT UNIQUE NOT NULL,
    previous_hash VARCHAR(256),
    entry_hash VARCHAR(256) NOT NULL UNIQUE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verdict VARCHAR(50) NOT NULL,  -- CLEAR, FLAG, NULL, DISCRETIONARY
    telemetry_id VARCHAR(255) NOT NULL,
    telemetry_hash VARCHAR(256),
    rule_id VARCHAR(255),
    knowledge_graph_version VARCHAR(50),
    milm_version VARCHAR(50),
    confidence_level VARCHAR(50),
    reasoning TEXT,
    escalation_status VARCHAR(50),
    escalation_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient queries
CREATE INDEX idx_verdict_timestamp ON ledger_entries(verdict, timestamp);
CREATE INDEX idx_telemetry_id ON ledger_entries(telemetry_id);
CREATE INDEX idx_rule_id ON ledger_entries(rule_id);
CREATE INDEX idx_sequence ON ledger_entries(sequence_number);

-- View for compliance reporting
CREATE VIEW ledger_summary AS
SELECT
    DATE_TRUNC('day', timestamp) as date,
    verdict,
    COUNT(*) as count,
    COUNT(CASE WHEN escalation_status IS NOT NULL THEN 1 END) as escalated
FROM ledger_entries
GROUP BY DATE_TRUNC('day', timestamp), verdict
ORDER BY date DESC;

-- View for integrity verification
CREATE VIEW ledger_integrity AS
SELECT
    sequence_number,
    entry_hash,
    previous_hash,
    (
        LAG(entry_hash) OVER (ORDER BY sequence_number) = previous_hash
    ) as chain_valid,
    timestamp
FROM ledger_entries
ORDER BY sequence_number;
