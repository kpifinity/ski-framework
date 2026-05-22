# SKI Framework — scripts

> **Status:** alpha. See the repo root `README.md` for the project-wide
> status banner.

Operational helpers for the SKI Framework reference implementation. The
scripts do not require any cloud API key.

## Available scripts

| Script | What it does |
|---|---|
| `setup.sh` | Generates strong random secrets, self-signed TLS certs, and a `.env` file (0600). Prereqs: docker, docker compose v2, python3, openssl. |
| `deploy.sh` | Wraps `docker compose` for `reference-implementation/` and waits for `/api/health`. |
| `cleanup.sh` | Removes Python caches and (with `--docker`) Docker resources. Refuses to delete `data/backups/` or `data/ledger/` — those are subject to your regulatory retention policy. |
| `send-telemetry.py` | Replays a JSONL telemetry file through the sidecar or directly to the SKI Model. Rejects records containing a `rule_id` (producers must not pre-route). |
| `check-verdicts.py` | Prints recent verdicts from `/api/verdicts`. |
| `verify-ledger.py` | Re-verifies the audit ledger end-to-end (chain linkage + entry-hash recomputation). |
| `validate-kg.py` | Static validation of a signed Knowledge Graph: signature, Tag Registry, `track` field, structured predicates, no `IMPLIED` rules, ISO-8601 dates. |
| `export-kg.py` | Dumps the currently-loaded KG via `/api/kg`. |
| `test-connection.py` | Verifies the SKI Model, sidecar, Ollama, and Postgres are reachable. |
| `load-kg.py` | (existing) Loads a KG via `/api/kg/load`. |
| `test-kg.py` | (existing) Local-file KG schema check. |
| `test-verdict.py` | (existing) Manual evaluation test against a sample telemetry record. |

## Common workflows

```bash
# First-time setup
./scripts/setup.sh

# Deploy the stack
./scripts/deploy.sh

# Smoke test
python scripts/test-connection.py --insecure
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure
python scripts/check-verdicts.py --insecure --limit 5

# Periodic integrity check
python scripts/verify-ledger.py
```

## Help & contributing

Every Python script accepts `--help`. New scripts should:

1. Live under `scripts/` with a descriptive name.
2. Use `argparse` for CLI flags.
3. Carry a top-level docstring describing inputs, outputs, and side effects.
4. Be added to the table above.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the broader contribution flow.
