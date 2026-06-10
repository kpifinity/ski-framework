# SKI Framework reference implementation

> **STATUS:** pre-production reference for the **v3** architecture
> (current release line: v3.1.0-alpha). It demonstrates the full
> neuro-symbolic path — KG-grounded local LLM, independent Symbolic
> Verifier, signed transcripts, append-only ledger — and runs entirely
> on-premise with no outbound calls during evaluation. Treat it as the
> executable companion to the specification, not a turnkey product.
> The repository's top-level README explains the project status.

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
│   ├── ski_model/                 The runtime service
│   │   ├── server.py              FastAPI app (/api/evaluate, /api/canary, …)
│   │   ├── kg_loader.py           Ed25519 signature verification + v3 loading
│   │   ├── ledger_client.py       Append-only hash-chained writes
│   │   ├── ledger_migrations.py   Startup schema self-heal (SKI_AUTOMIGRATE)
│   │   └── v3/                    The v3 evaluation core
│   │       ├── evaluator.py       KG-grounded LLM evaluation (T=0, seeded,
│   │       │                      structured generation)
│   │       ├── verifier.py        Symbolic Verifier — independent check of
│   │       │                      every formalizable assertion
│   │       ├── envelope.py        V3VerdictEnvelope (spec §4)
│   │       ├── transcript.py      Signed LLM transcripts (Ed25519)
│   │       ├── agreement_monitor.py  Rolling LLM↔verifier agreement rate
│   │       ├── policies/risk_tier.py Risk-Tier Governor (strict, KG-declared)
│   │       └── backends/          V3LLMBackend protocol; Ollama + FakeLLM
│   ├── symbolic_evaluator/        Deterministic predicate evaluation
│   │                              (used by the Verifier; incl. stateful windows)
│   ├── tag_registry/              Governed subject→rule package + tier lookup
│   ├── telemetry_buffer/          Postgres-backed stateful-evaluation buffer
│   ├── ledger/
│   │   ├── schema.sql             v3 baseline (envelope + transcript columns)
│   │   ├── migrations/            0002_transcript_columns (idempotent)
│   │   └── append_only.sql        UPDATE/DELETE/TRUNCATE triggers
│   └── sidecar/                   Read-only telemetry intake
├── migrations/                    Alembic (telemetry buffer, baseline)
├── monitoring/
│   ├── prometheus.yml             Scrape config
│   ├── rules/ski-alerts.yml       Alert-rule contract (see file header note)
│   └── kafka_jaas.conf            Kafka SASL/SCRAM (kafka telemetry source)
└── docs/
    ├── DEPLOYMENT.md              How to deploy
    ├── CONCURRENCY.md             Why workers=1 is enforced
    ├── CUSTOMIZATION.md           Swap backends; bring your own KG
    ├── TROUBLESHOOTING.md
    ├── API.md                     /api/health, /api/kg/load, /api/evaluate, …
    └── KUBERNETES.md              Constraints + direction; Helm chart in v3.1
```

## Architecture (v3)

Every verdict takes the same path:

```
   ┌──────────┐  subject + measurement  ┌────────────────────────────────────┐
   │  Sidecar │ ──────────────────────▶ │             SKI Model              │
   └──────────┘                         │                                    │
                                        │  KG scoped to jurisdiction +       │
                                        │  effective date of the measurement │
                                        │              │                     │
                                        │              ▼                     │
                                        │  ┌─────────────────────────┐       │
                                        │  │  LLM Evaluator (local,  │       │
                                        │  │  T=0, structured gen)   │       │
                                        │  └───────────┬─────────────┘       │
                                        │     verdict, reasoning, citations, │
                                        │     formalizable assertions        │
                                        │              ▼                     │
                                        │  ┌─────────────────────────┐       │
                                        │  │  Symbolic Verifier      │       │
                                        │  │  (independent re-check) │       │
                                        │  └───────────┬─────────────┘       │
                                        │     AGREED / LLM_CONTRADICTION /   │
                                        │     DIVERGENCE / UNVERIFIABLE      │
                                        │              ▼                     │
                                        │   verdict envelope + signed LLM    │
                                        │   transcript + provenance hashes   │
                                        └──────────────┬─────────────────────┘
                                                       ▼
                                        ┌──────────────────────────────┐
                                        │  Append-only audit ledger    │
                                        │  (Postgres + triggers)       │
                                        └──────────────────────────────┘
```

Disagreement between the LLM and the Verifier is recorded as a
first-class signal and feeds the rolling **agreement monitor**
(`GET /api/canary`).

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

See [`QUICKSTART.md`](./QUICKSTART.md) for the full walkthrough,
including a no-Docker quick check that runs evaluate → verify through
the FakeLLM backend.

## Configuration

All runtime configuration is via environment variables documented in
[`.env.example`](./.env.example). Highlights:

| Variable | Default | Notes |
|---|---|---|
| `SKI_INFERENCE_BACKEND` | `ollama` | `anthropic` is an opt-in, NON-CONFORMANT demo mode. |
| `SKI_MODEL_NAME` | `qwen2.5:7b-instruct` | Must be pulled into the Ollama volume. |
| `SKI_MODEL_FILE_SHA256` | empty | Pin the exact model artifact; recorded in every envelope. |
| `SKI_MODEL_SEED` | `42` | Fixed decoder seed; recorded in every envelope. |
| `KG_REQUIRE_SIGNATURE` | `true` | `false` is non-conformant (demo KGs only). |
| `SKI_API_KEY` | required | `setup.sh` generates one. |
| `TLS_ENABLED` | `true` | Self-signed certs generated by `setup.sh`. |
| `SKI_MODEL_WORKERS` | `1` (enforced) | See [`docs/CONCURRENCY.md`](./docs/CONCURRENCY.md). |
| `SKI_AUTOMIGRATE` | `true` | Startup ledger-schema self-heal; set `false` for DBA-gated shops. |

## What's NOT yet here

- Kubernetes manifests / Helm chart (v3.1 — see [ROADMAP.md](../ROADMAP.md))
- vLLM / llama.cpp backends (v3.1)
- Prometheus `/metrics` instrumentation (the alert rules define the
  contract; see `monitoring/rules/ski-alerts.yml`)
- Horizontal scaling / shard router (v3.2)

## Test it

```bash
pip install -r ../requirements-dev.txt
pytest -q
pytest ../conformance -q -m "provenance or durability"
```

## Hardening

Before any production-track use, read
[`SECURITY_DEFAULTS.md`](./SECURITY_DEFAULTS.md). Replace the self-signed
certs from `setup.sh` with certs from your own CA, route secrets through
your secrets manager, and document your hardware baseline.

## Where to go next

- [`QUICKSTART.md`](./QUICKSTART.md) — walkthrough
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) — full deployment guide
- [`docs/API.md`](./docs/API.md) — REST surface
- [`docs/CUSTOMIZATION.md`](./docs/CUSTOMIZATION.md) — swapping backends,
  bringing your own KG, integrating with telemetry sources
- [`../conformance/README.md`](../conformance/README.md) — running the
  conformance suite against this deployment
