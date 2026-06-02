# Schema migrations

The SKI Framework reference implementation uses Alembic to manage
Postgres schema changes. Migrations live under
[`reference-implementation/migrations/`](../reference-implementation/migrations/)
and are versioned alongside the spec.

## Why we use migrations

- **Reproducible deployments.** Every deployment ends up at a known
  schema version.
- **Audit-grade upgrade paths.** Every schema change has an `upgrade()`
  and (where safe) a `downgrade()` function. Auditors can read the
  exact transformation that was applied.
- **Forwards / backwards compatibility.** v0.1 ledger entries continue
  to read after the v0.2 migration runs, because the migration only
  adds nullable columns and new tables.

## Versions

| Revision | Spec version | What it does |
|---|---|---|
| `001_baseline` | v2.0 / v0.1.0-alpha | Captures the v0.1 baseline (already-deployed `ledger_entries` + append-only triggers) without modification |
| `002_telemetry_buffer` | v2.1 / v0.2.0 | Adds `tenants`, `telemetry_buffer` (RANGE-partitioned), buffer append-only triggers, `schema_version` column on `ledger_entries`, default `tenant` row, default daily partition |
| `0002_transcript_columns` | v3.0 / v3.0.0 | Adds the v3 audit-trail columns to `ledger_entries`: `envelope_json`, `envelope_hash`, `transcript_json`, `transcript_signature`, `signing_key_id`, `verifier_status`. Relaxes the legacy `track` CHECK so v3 evaluator entries (`'v3-evaluator'`) are accepted. Idempotent (every ALTER guarded with IF [NOT] EXISTS). Required for any v0.2.x ledger being upgraded to v3.0. **Fresh v3.0.1+ deployments** get these columns directly from `schema.sql` (rewritten to the v3 baseline in PR 15) and docker-compose also mounts this migration as `03-transcript-columns.sql` for defence-in-depth — both paths end at the same column set. |

## Running migrations

### First-time setup on an empty database

```bash
cd reference-implementation
alembic -c migrations/alembic.ini upgrade head
```

### Upgrading an existing v0.1 deployment to v0.2

```bash
# Back up first.
audit-ledger backup --source "$LEDGER_DSN" --output ledger-pre-v0.2.dump

# Run migrations.
cd reference-implementation
alembic -c migrations/alembic.ini upgrade head

# Verify.
audit-ledger verify --ledger-db "$LEDGER_DSN"
```

### Upgrading an existing v0.2 deployment to v3.0

The v3 runtime expects six new columns on `ledger_entries`
(`envelope_json`, `envelope_hash`, `transcript_json`,
`transcript_signature`, `signing_key_id`, `verifier_status`) plus a
relaxed `track` CHECK. The fresh-deploy baseline `schema.sql` has these
inline as of v3.0.1.

**v3.0.2 and later: nothing to do.** On startup the runtime probes
`ledger_entries`; if the v3 columns are missing it applies the
`0002_transcript_columns` migration in place. Operators upgrading
from v3.0.0 / v3.0.1 / v0.2.x against an existing Postgres volume
simply pull the new image and restart the stack. The behaviour is
idempotent and on by default. Set `SKI_AUTOMIGRATE=false` in hardened
deployments where schema changes require an explicit DBA gate — the
runtime will then refuse to start if the v3 columns are absent and
log the exact `psql` command an operator should run.

**v3.0.0 / v3.0.1 only (no auto-apply yet):** existing v0.2 ledgers
must run the migration explicitly before the v3 runtime can `INSERT`:

```bash
# Back up first.
audit-ledger backup --source "$LEDGER_DSN" --output ledger-pre-v3.dump

# Apply the v3 transcript-columns migration. It is idempotent — safe to
# re-run against a clean v3 schema.
psql "$LEDGER_DSN" -f reference-implementation/src/ledger/migrations/0002_transcript_columns.sql

# Verify chain integrity (no v3 columns are required for existing rows
# to verify; the new columns are nullable on historical rows).
audit-ledger verify --ledger-db "$LEDGER_DSN"
```

Symptom if you forget this step: `/api/evaluate` returns 500 with
`column "envelope_json" of relation "ledger_entries" does not exist`.

The v0.2 migration:

- Adds a `schema_version` column to `ledger_entries`, defaulting to
  `'0.1.0'` for existing rows and `'0.2.0'` for new rows.
- Creates the `tenants` table with a single `'default'` row
  (`buffer_retention_days = 30`).
- Creates the partitioned `telemetry_buffer` table with append-only
  triggers and today's partition.

No existing data is modified. The migration is safe to run on a live
ledger with concurrent writers (Postgres handles the locking).

## Rolling back

```bash
alembic -c migrations/alembic.ini downgrade -1
```

The v0.2 downgrade drops the buffer table and the `schema_version`
column. The `tenants` table is preserved (downgrades are not allowed to
destroy customer-supplied configuration). Pre-v0.2 ledger entries are
unaffected.

## Operator tasks

### Adjusting a tenant's buffer retention

```sql
UPDATE tenants
SET buffer_retention_days = 90
WHERE tenant_id = 'default';
```

The change takes effect on the next retention cron run.

### Adding a new partition

Daily partitions are created automatically by the retention job. To
pre-create one manually:

```sql
CREATE TABLE telemetry_buffer_2026_06
  PARTITION OF telemetry_buffer
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

### Dropping old partitions

```sql
SELECT drop_buffer_partitions_older_than(NOW() - INTERVAL '30 days');
```

This is the only supported way to remove data from the buffer; the
per-row append-only trigger refuses everything else.
