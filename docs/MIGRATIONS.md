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
| `001_baseline` | v2.1 / v0.1.0-alpha | Captures the v0.1 baseline (already-deployed `ledger_entries` + append-only triggers) without modification |
| `002_telemetry_buffer` | v2.1 / v0.2.0 | Adds `tenants`, `telemetry_buffer` (RANGE-partitioned), buffer append-only triggers, `schema_version` column on `ledger_entries`, default `tenant` row, default daily partition |

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
