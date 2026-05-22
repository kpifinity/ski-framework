# SKI Framework reference implementation

> **⚠ STATUS: EARLY ALPHA (v0.1.0-alpha).** This is a proof-of-scaffold
> reference, not a production deployment. The repository's top-level
> README explains the project status; this document explains what's
> inside the reference implementation specifically.

This directory contains a **working, sovereign-by-default** reference
implementation of SKI Framework v2.1. It demonstrates how the Symbolic
Evaluator, SKI Model wrapper, Tag Registry, audit ledger, and sidecar
fit together. It runs entirely on-premise (Ollama backend) and makes
no outbound network calls during inference in its default configuration.

## What's inside

```
reference-implementation/
├── docker-compose.yml             Ollama + SKI Model + sidecar + Postgres +
│                                  postgres_exporter + Prometheus + Grafana
├── Dockerfile.ski-model           Runs as non-root (UID 10001)
├── Dockerfile.sidecar             Runs as non-root (UID 10002)
├── .env.example                   No defaults for secrets; stack refuses to
│                                  start without operator-supplied values
├── SECURITY_DEFAULTS.md           What is hardened vs. deferred
├── src/
│   ├── ski_model/                 SKI Model service (Track 2 wrapper)
│   │   ├── server.py              FastAPI app with lifespan handler
│   │   ├── backends.py            Ollama (default); Anthropic demo backend
│   │   ├── kg_loader.py           Ed25519 signature verification
│   │   ├── ledger_client.py       Append-only hash-chained writes
│   │   ├── canary.py              Determinism canary (B3.4)
│   │   └── verdicts.py            Five-verdict taxonomy (v2.1)
│   ├── symbolic_evaluator/        Track 1 — deterministic predicate evaluation
│   ├── tag_registry/              Subject→rule lookup (B4.3)
│   ├── ledger/
│   │   ├── schema.sql             ledger_entries (no confidence_level)
│   │   └── append_only.sql        UPDATE/DELETE/TRUNCATE triggers
│   └── sidecar/                   Read-only telemetry intake (httpx.AsyncClient)
├── monitoring/
│   ├── prometheus.yml             Scrapes postgres_exporter (not Postgres)
│   ├── rules/ski-alerts.yml       SKI-specific alert rules
│   └── kafka_jaas.conf            Kafka SASL/SCRAM
├── examples/
│   ├── knowledge-graphs/          Demo KG (unsigned; non-conformant)
│   └── telemetry/                 Demo telemetry (no rule_id)
└── docs/
    ├── DEPLOYMENT.md              How to deploy
    ├── QUICKSTART.md
    ├── CONCURRENCY.md             Why workers=1 is enforced
    ├── CUSTOMIZATION.md           Swap backends; bring your own KG
    ├── TROUBLESHOOTING.md
    ├── API.md                     /api/health, /api/kg/load, /api/evaluate, …
    └── KUBERNETES.md              Notes; manifests planned for v0.2
```

## Architecture

```
   ┌──────────┐   subject + measurement   ┌─────────────────────────────┐
   │  Sidecar │ ────────────────────────▶ │        SKI Model            │
   └──────────┘                           │ ┌─────────────────────────┐ │
                                          │ │      Tag Registry       │ │ pure lookup
                                          │ └────────────┬────────────┘ │
                                          │              │              │
                                          │  ┌───────────┴───────────┐  │
                                          │  ▼                       ▼  │
                                          │ ┌──────────────┐  ┌─────────┴────────┐
                                          │ │  Symbolic    │  │  Ollama-backed   │
                                          │ │  Evaluator   │  │  SKI Model       │
                                          │ │  (Track 1)   │  │  (Track 2, T=0)  │
                                          │ └──────┬───────┘  └────────┬─────────┘
                                          │        │                   │         │
                                          │        ▼                   ▼         │
                                          │   verdict ∈ {CLEAR, FLAG, NULL_*,    │
                                          │              DISCRETIONARY}          │
                                          └─────────────┬────────────────────────┘
                                                        │
                                                        ▼
                                         ┌──────────────────────────────┐
                                         │  Append-only audit ledger    │
                                         │  (Postgres + triggers)       │
                                         └──────────────────────────────┘
```

## Quick start

```bash
# 1. Generate secrets and TLS certs, write .env (0600).
./scripts/setup.sh

# 2. Pull the local LLM weights into Ollama.
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct

# 3. Start the full stack.
./scripts/deploy.sh

# 4. Smoke test.
python scripts/test-connection.py --insecure
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure
python scripts/check-verdicts.py --insecure --limit 5
```

See [`docs/QUICKSTART.md`](./QUICKSTART.md) for the full walkthrough.

## Configuration

All runtime configuration is via environment variables documented in
[`.env.example`](./.env.example). Highlights:

| Variable | Default | Notes |
|---|---|---|
| `SKI_INFERENCE_BACKEND` | `ollama` | Use `anthropic` only as opt-in non-conformant demo. |
| `SKI_MODEL_NAME` | `qwen2.5:7b-instruct` | Must be pulled into the Ollama volume. |
| `SKI_MODEL_FILE_SHA256` | empty | Set to pin a specific model artefact (B3.4). |
| `SKI_MODEL_SEED` | `42` | Deterministic decoding requires a fixed seed. |
| `KG_REQUIRE_SIGNATURE` | `true` | Setting to `false` is non-conformant. |
| `SKI_API_KEY` | required | Generate via `openssl rand -hex 32`; `setup.sh` does this for you. |
| `TLS_ENABLED` | `true` | Self-signed certs generated by `setup.sh`. |
| `SKI_MODEL_WORKERS` | `1` (enforced) | See [`docs/CONCURRENCY.md`](./docs/CONCURRENCY.md). |
| `DETERMINISM_CANARY_INTERVAL` | `300` (s) | Set to `0` only in tests. |

## Components

### SKI Model (`src/ski_model/`)
The runtime inference service. Routes telemetry through the Tag Registry,
then either the Symbolic Evaluator or the Ollama-backed bounded LLM.
Writes every verdict to the audit ledger. Refuses to load unsigned KGs by
default. Single-worker by enforcement.

### Symbolic Evaluator (`src/symbolic_evaluator/`)
Deterministic predicate evaluator for Track 1 rules: `lte`, `gte`, `lt`,
`gt`, `eq`, `range`, `in_set`, `not_in_set`, `exists`. No LLM. Unit
mismatches surface as `DISCRETIONARY` rather than silently coerced.

### Tag Registry (`src/tag_registry/`)
Immutable mapping from normalised subject string → KG rule, compiled from
the signed KG. Runtime tag inference is architecturally impossible: this
is a dict lookup. Missing subjects → `NULL_UNMAPPED`.

### Audit ledger (`src/ledger/`)
Postgres-backed, append-only at the database layer via `BEFORE UPDATE`,
`BEFORE DELETE`, and `BEFORE TRUNCATE` triggers. Hash-chained entries.
Canonical serialization documented in
`tools/audit-ledger/src/audit_ledger/canonical.py` so third parties can
verify integrity without our code.

### Sidecar (`src/sidecar/`)
Read-only telemetry intake. Uses `httpx.AsyncClient` with retries, the
FastAPI lifespan context manager (no deprecated `@app.on_event`), and
emits a heartbeat for gap detection.

## What's NOT yet in this release

- Stateful evaluation buffer / `NULL_STALE` routing (Block 3 #12 partial)
- Production Kubernetes manifests
- Vault / AWS Secrets Manager integration code
- Additional backends (vLLM, llama.cpp) — Ollama only today

These are tracked in the project [CHANGELOG](../CHANGELOG.md) under
`[Unreleased]`.

## Test it

```bash
pip install -r ../requirements-dev.txt
pytest -q
pytest ../conformance -q -m level1
```

## Hardening

Before any production-track use, read
[`SECURITY_DEFAULTS.md`](./SECURITY_DEFAULTS.md). Replace the self-signed
certs from `setup.sh` with certs from your own CA, route secrets through
your secrets manager, and document your hardware baseline.

## Where to go next

- [`QUICKSTART.md`](./QUICKSTART.md) — 5-minute walkthrough
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) — full deployment guide
- [`docs/API.md`](./docs/API.md) — REST surface
- [`docs/CUSTOMIZATION.md`](./docs/CUSTOMIZATION.md) — swapping backends,
  bringing your own KG, integrating with telemetry sources
- [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md)
- [`../conformance/README.md`](../conformance/README.md) — running the
  conformance suite against this deployment
