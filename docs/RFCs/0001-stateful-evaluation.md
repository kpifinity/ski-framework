# RFC 0001 — Stateful Evaluation and Deterministic Replay

> **Status:** Accepted (v0.2.0).
> **Authors:** KpiFinity Inc.
> **License:** CC BY 4.0 — see [LICENSE-docs.md](../../LICENSE-docs.md).

## Summary

v0.1.0-alpha shipped a stateless reference implementation: every telemetry
record was evaluated in isolation, against the current Knowledge Graph,
with no notion of history or time windows. The verdict taxonomy reserved
`NULL_STALE` for "rule matched but its time-window predicate was not
satisfied," but the buffer that would have populated such a verdict did
not exist. Stateful predicates listed in the spec (B4.4) were stubs.

This RFC introduces a Postgres-backed **telemetry buffer**, a small
extension to the **Symbolic Evaluator predicate grammar** that consults
the buffer, and a **deterministic replay** primitive that re-evaluates
prior ledger entries against the recorded buffer state and Knowledge
Graph version. Together these close out Spec section B4.4 and produce the
deterministic-replay primitive that Level 3 conformance depends on.

## Goals

- Close the `NULL_STALE` gap end-to-end: stateful predicates produce real
  verdicts; the spec section B4.4 has a runnable reference.
- Preserve determinism: identical telemetry replayed against an identical
  buffer state and KG version produces identical verdicts.
- Preserve auditability: the buffer is append-only at the database layer,
  same as the ledger.
- Preserve sovereignty: no new outbound network calls. The buffer lives
  in the same Postgres instance as the ledger.
- Preserve open-core boundary: the buffer schema, the predicate grammar
  extensions, and the replay tool are all Apache 2.0.

## Non-goals

- High-throughput stream processing (deferred to v0.3 / Theme B).
- Cross-tenant queries on the buffer.
- Automatic time-travel correction of past verdicts (out of scope; v0.1
  remains the authority on what was decided at evaluation time).
- Replacing the audit ledger with the buffer; they are complementary
  artefacts.

## Design

### Authoritative clock

The telemetry record's own `timestamp` field is the **only** clock used
for stateful evaluation. Wall-clock-at-arrival is not consulted. This
choice has three consequences:

1. **Replay is deterministic.** The same record evaluated tomorrow
   produces the same result, because the predicate's "now" is the
   telemetry timestamp, not the system clock.
2. **Out-of-order arrival is permitted at the architectural level.** The
   buffer is keyed by `(subject, telemetry_timestamp)`, not arrival
   order. A late record correctly takes its temporal position.
3. **Clock-skew attacks are still possible at the producer.** This is
   inherent: if the producer lies about the timestamp, downstream
   evaluation is wrong. We document this as an operator responsibility
   and provide a `--max-clock-skew-seconds` rejection knob.

### Buffer storage

The buffer is a single Postgres table, partitioned by tenant and day:

```sql
CREATE TABLE telemetry_buffer (
    id              BIGSERIAL,
    tenant_id       TEXT NOT NULL,
    subject         TEXT NOT NULL,
    telemetry_id    TEXT NOT NULL,
    telemetry_ts    TIMESTAMPTZ NOT NULL,
    received_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    measurement     JSONB NOT NULL,
    measurement_hash CHAR(64) NOT NULL,
    schema_version  TEXT NOT NULL DEFAULT '0.2.0',
    PRIMARY KEY (tenant_id, telemetry_ts, id)
) PARTITION BY RANGE (telemetry_ts);
```

`measurement_hash` is the canonical SHA-256 of the measurement object,
so the buffer can be cross-referenced to the ledger's `telemetry_hash`
column for tamper detection.

Indexes:

```sql
CREATE INDEX idx_buffer_subject_ts
    ON telemetry_buffer (tenant_id, subject, telemetry_ts);
```

Append-only enforcement uses the same trigger pattern as
`ledger_entries`:

```sql
DROP TRIGGER IF EXISTS buffer_block_update ON telemetry_buffer;
CREATE TRIGGER buffer_block_update
    BEFORE UPDATE ON telemetry_buffer
    FOR EACH ROW EXECUTE FUNCTION ledger_block_update_delete();
-- Plus BEFORE DELETE and BEFORE TRUNCATE.
```

UPDATE/DELETE/TRUNCATE on `telemetry_buffer` raise an exception. Dropping
old partitions (the retention path) is explicitly excepted via a
trigger-disabling stored procedure that requires operator privileges.

### Per-tenant retention

There is no default retention window. The operator sets it per tenant:

```sql
CREATE TABLE tenants (
    tenant_id              TEXT PRIMARY KEY,
    display_name           TEXT NOT NULL,
    buffer_retention_days  INT NOT NULL CHECK (buffer_retention_days > 0),
    max_clock_skew_seconds INT NOT NULL DEFAULT 60,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Retention is enforced by a daily cron-style job that drops partitions
older than `buffer_retention_days`. The drop runs through the
trigger-disabling procedure and is itself logged to the ledger as a
`BUFFER_PARTITION_DROPPED` administrative entry (a new ledger entry type
to be added in PR 2).

### Predicate grammar extensions

Five new operators are added to the Symbolic Evaluator. Each fits the
existing `{operator, metric, ...}` predicate shape and is documented in
[docs/knowledge-graph.md](../knowledge-graph.md).

| Operator | Required fields | Semantics |
|---|---|---|
| `window_count` | `metric`, `seconds`, `op` ∈ {lte,gte,lt,gt,eq}, `value` | Count records for the subject in the last `seconds`; compare to `value`. |
| `window_sum` | `metric`, `seconds`, `op`, `value` | Sum `metric.value` over the window; compare. |
| `window_avg` | `metric`, `seconds`, `op`, `value` | Arithmetic mean over the window; compare. |
| `since_last` | `metric`, `op`, `value_seconds` | Seconds elapsed since the previous record for this subject; compare. |
| `debounce` | `metric`, `seconds` | If another record for this subject exists within the window, return `DISCRETIONARY` with reasoning; else evaluate `then` predicate. |

`requires_recent_within_seconds` (existing field) is wired: if the rule
has this property and the buffer has no record for `subject` within the
window, the verdict is `NULL_STALE` and evaluation of the rule body is
skipped.

### Evaluation locus

Stateful evaluation runs in the Symbolic Evaluator (Track 1) process. It
issues per-record Postgres queries against the buffer. The queries are
single-index lookups bounded by the predicate's window, expected to
complete in <2ms at typical buffer sizes.

Throughput ceiling: ~5,000 records/sec/shard before the buffer query
becomes the bottleneck. v0.3 / Theme B will introduce per-shard
horizontal scaling to lift this ceiling without changing the per-shard
correctness model.

Track 2 (LLM-backed) evaluation does not consume the buffer in v0.2.0.
This is a deliberate scope cut: introducing the buffer to the LLM
context risks non-determinism if not done carefully.

### Schema versioning and backwards compatibility

`ledger_entries` gets a new column:

```sql
ALTER TABLE ledger_entries
ADD COLUMN schema_version TEXT NOT NULL DEFAULT '0.2.0';
```

v0.1 entries get `schema_version = '0.1.0'` via migration backfill. The
SKI Model service treats `schema_version IS NULL` and `schema_version =
'0.1.0'` identically: those records pre-date the buffer and are
evaluated in stateless mode during replay (stateful predicates skipped
with a recorded note).

The `audit-ledger verify` command warns (not fails) when it encounters
mixed schema versions in the same ledger. Operators can choose to
re-evaluate v0.1 entries under v0.2 rules; if so, the result is recorded
as a NEW ledger entry with a `replays_sequence` pointer to the original.
Original entries are never modified.

### Deterministic replay

A new `audit-ledger replay` subcommand:

```
audit-ledger replay --from <seq> --to <seq>
                    [--kg-path <path-to-recorded-kg>]
                    [--strict]
                    [--output replay-report.json]
```

For each ledger entry in `[from, to]`:

1. Load the Knowledge Graph at the entry's `knowledge_graph_version`. If
   `--kg-path` is given, use that file; otherwise look up via the KG
   store (out of scope for v0.2; `--kg-path` is the supported path).
2. Reconstruct the buffer state at the entry's `telemetry_timestamp`
   (rows with `telemetry_ts <= entry.telemetry_ts`).
3. Re-evaluate using the in-process Symbolic Evaluator + SKI Model.
4. Compare the produced verdict to the recorded `verdict`. Record both
   in the replay report.
5. If `--strict`, exit non-zero on any divergence.

Replay is the foundation of Level 3 conformance testing. It is also a
standalone audit tool: a regulator can ask "show me your evaluation of
record X" and you can produce the deterministic re-evaluation alongside
the original ledger row.

## Deployment shapes

This design works identically for both supported v0.2 target shapes:

- **BYOC** (customer-controlled cloud): buffer table lives in the
  customer's Postgres. No additional infra dependency. Retention dropped
  via the customer's cron / Kubernetes CronJob.
- **Air-gapped on-premise**: identical to above. The retention job runs
  via systemd timer or cron. No outbound network traffic introduced.

## Open questions for v0.3 (deferred)

- Per-shard horizontal scaling (Theme B). Buffer queries currently
  ceiling at ~5k req/sec/shard.
- Buffer corrections via signed amendment rows (Theme D, "append-only
  + signed corrections" option).
- TPM-attested buffer hash sampling (Theme D).
- Cross-tenant aggregations for KpiFinity-level fleet reporting (commercial).

## Migration impact

- Existing v0.1 ledger rows continue to read without change. Stateful
  predicates encountered during replay of v0.1 rows are skipped with a
  recorded note.
- The Postgres role used by the SKI Model service must gain INSERT on
  `telemetry_buffer` and SELECT on `tenants`. This is handled by
  migration 002.
- Operators must declare at least one row in `tenants` before the first
  v0.2 evaluation. A default "single-tenant" bootstrap is provided by
  the migration with `tenant_id='default'` and `buffer_retention_days=30`
  so that existing single-customer deployments require no manual
  configuration.

## References

- SKI Framework Specification v2.1, section B4.4 (Stateful Evaluation).
- [docs/architecture.md](../architecture.md) — phase 2 runtime.
- [docs/conformance.md](../conformance.md) — Level 2 tests this enables.
- [tools/audit-ledger/src/audit_ledger/canonical.py](../../tools/audit-ledger/src/audit_ledger/canonical.py)
  — canonical entry hashing, unchanged.
