# SKI Framework v3.0.2 — Auto-apply v3 ledger migration on startup

**Released:** 2026-06-02

The last patch in the v3.0.0 ledger-schema saga. v3.0.1 fixed the
schema bootstrap for **fresh** deployments. v3.0.2 fixes it for
**existing** deployments: the runtime now probes the ledger on startup
and applies the v3 migration in place if it detects v2.1 columns. No
operator intervention required — pull the new image, restart, the
schema heals itself.

## The bug v3.0.1 didn't catch

PR 15 (v3.0.1) rewrote `schema.sql` to the v3 baseline and added the
`0002_transcript_columns.sql` migration as a defence-in-depth mount in
`/docker-entrypoint-initdb.d/`. That helped any fresh
`docker compose up` against an **empty** Postgres volume.

What it *didn't* help: operators upgrading on top of an **existing**
Postgres volume. Postgres' init scripts only run once, when the data
directory is empty. An operator who:

1. Brought up v3.0.0 (which init'd the v2.1 schema), then
2. Pulled v3.0.1 and restarted,

...still hit the same `column "envelope_json" of relation
"ledger_entries" does not exist` error at evaluation time — because
Postgres remembers the volume as "already initialised" and skips every
init script, including the v3 baseline and the mounted migration.

## What's in v3.0.2

- **`ski_model.ledger_migrations.ensure_v3_ledger_schema`** — new
  module called from `server.py` lifespan after the ledger client
  connects. Probes `ledger_entries` for the six v3 audit-trail
  columns (`envelope_json`, `envelope_hash`, `transcript_json`,
  `transcript_signature`, `signing_key_id`, `verifier_status`). If
  any are missing, applies `0002_transcript_columns` in place.
  Idempotent: a no-op on a schema already at v3.
- **`SKI_AUTOMIGRATE` environment variable** (default `true`).
  Hardened deployments where schema changes require an explicit DBA
  gate can set `SKI_AUTOMIGRATE=false`. The runtime then logs the
  exact `psql` command and refuses to start if v3 columns are
  missing — fail-fast instead of failing at first evaluation.
- **Embedded migration SQL.** The migration SQL is embedded in
  `ledger_migrations.py` (the ski-model container doesn't ship the
  `src/ledger/` files). A durability conformance test
  (`test_ledger_migrations_runner.py`) pins the embedded string
  against the canonical `migrations/0002_transcript_columns.sql` so
  the two cannot silently drift.

## Upgrading

### From v3.0.1 (or v3.0.0, or v0.2.x)

```bash
docker compose pull
docker compose up -d
```

That's it. The first startup against your existing volume will probe
the schema, apply the migration if needed, and log:

```
INFO  Ledger schema missing v3 columns [...] — applying 0002_transcript_columns in place.
INFO  Applied 0002_transcript_columns. Ledger schema is now at v3.
```

If you've already manually applied `0002_transcript_columns.sql`
against your database (per the v3.0.1 upgrade procedure), the
auto-apply is a no-op:

```
INFO  Ledger schema is at v3; no migration required.
```

### Opt-out for hardened deployments

If your compliance posture forbids the runtime mutating the schema:

```bash
docker compose pull
SKI_AUTOMIGRATE=false docker compose up -d
```

If v3 columns are missing, the server will exit at startup with a
clear error pointing at `docs/MIGRATIONS.md` and the exact `psql`
command to run. Apply the migration manually with your DBA-blessed
procedure, then restart.

## What's unchanged

- v3 runtime behaviour, public API, verdict envelope shape.
- Conformance Provenance and Durability suites pass.
- Tools (`kg-extractor`, `kg-validator`, `ski-model-deploy`,
  `audit-ledger`) are version-bumped to `3.0.2` for alignment but
  carry no behavioural changes.

## Credit

Same tester who caught the v3.0.0 ledger gap. They upgraded to v3.0.1
against an existing volume and reported the symptom + correct
diagnosis (Postgres initdb only runs once) within an hour. v3.0.2
exists because of clean repros like that.

## Full ship log

See [`CHANGELOG.md`](CHANGELOG.md#302--2026-06-02) for the complete
list of changes.
