# Database migrations

Alembic migrations for the SKI Framework reference implementation Postgres
schema (ledger + telemetry buffer + tenants).

## Why Alembic

v0.2 introduces stateful evaluation (RFC 0001), which adds the
`telemetry_buffer` and `tenants` tables and a `schema_version` column on
`ledger_entries`. Schema changes from now on go through Alembic so:

- Every change is reviewable in a single commit.
- Upgrades are reversible (`alembic downgrade`).
- Operators can stage migrations against a copy of production before
  promoting.
- The conformance suite can assert that the live schema matches a
  pinned migration revision.

## Layout

```
reference-implementation/migrations/
├── alembic.ini           Alembic config
├── env.py                Alembic env (reads LEDGER_DSN)
├── script.py.mako        Template for new migrations
├── versions/
│   ├── 001_baseline.py        v0.1 schema baseline
│   └── 002_telemetry_buffer.py  v0.2 buffer + tenants + schema_version
└── README.md             this file
```

## Running

```bash
# From the repo root
export LEDGER_DSN='postgresql://ski:...@localhost:5432/ski_ledger'

# Apply all pending migrations
alembic -c reference-implementation/migrations/alembic.ini upgrade head

# Show current revision
alembic -c reference-implementation/migrations/alembic.ini current

# Roll back one migration
alembic -c reference-implementation/migrations/alembic.ini downgrade -1

# Generate a new migration (after editing models or schema SQL)
alembic -c reference-implementation/migrations/alembic.ini revision \
    -m "short description"
```

The SKI Model service refuses to start at boot if the live schema is
behind the migration head. Operators must either run the migration or
explicitly opt into "schema-ahead-of-app" mode with `SKI_ALLOW_SCHEMA_DRIFT=true`
(non-conformant; testing only).

## Backwards compatibility

The migrations are written so that:

- v0.1 ledger entries are preserved untouched. They are tagged
  `schema_version='0.1.0'` by migration 002.
- Downgrade from 002 → 001 drops `telemetry_buffer`, `tenants`, and the
  `schema_version` column. **Downgrade destroys data in
  `telemetry_buffer` and `tenants`.** This is documented in the
  migration's docstring; operators must snapshot first.

## CI

CI runs `alembic upgrade head` against an ephemeral Postgres in the
conformance test suite. Any change that makes the head migration
unreachable from baseline fails CI.
