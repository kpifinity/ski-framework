# Quick start

> **⚠ STATUS: EARLY ALPHA.** Reference implementation only; not production ready.

This walks you through running the SKI Framework reference implementation
on a single machine. No cloud API key is required. Total time: ~10 minutes
the first time, ~2 minutes thereafter.

## First verdict in 5 minutes (demo mode — not conformant)

No model download, no GPU: the deterministic FakeLLM backend exercises
the full v3 pipeline — evaluator, Symbolic Verifier, signed transcripts,
append-only ledger, /metrics — so you can see a real verdict envelope
immediately. **Not conformant** (no real language model); use the full
stack below for anything beyond a demo.

```bash
./scripts/setup.sh          # secrets + TLS + signed demo KG (once, from repo root)
cd reference-implementation
docker compose -f docker-compose.demo.yml up -d --build

# Health — expect kg_loaded:true, kg_signature_verified:true
curl -k https://localhost:8000/api/health

# Your first verdict (use the API key setup.sh wrote to .env):
source .env
curl -k -X POST https://localhost:8000/api/evaluate \
  -H "X-API-Key: $SKI_API_KEY" -H "Content-Type: application/json" \
  -d '{"measurement_id":"demo-001","timestamp":"2026-06-15T12:00:00Z",
       "subject":"facility.so2","jurisdiction":"us.federal",
       "measurement":{"so2_ppm":142}}'
```

You get back a full `V3VerdictEnvelope`: `"verdict": "FLAG"` (142 ppm
breaches the 100 ppm cap), the KG citation, the formalizable assertion,
the Symbolic Verifier's `AGREED` cross-check, six provenance hash
anchors, and a `transcript_ref` into the signed audit trail. Then:
`curl -k https://localhost:8000/metrics` to watch the verdict counters
move, and `python ../scripts/verify-ledger.py` to verify the hash chain.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Engine | 24+ | |
| Docker Compose | v2 | `docker compose version` must succeed |
| Python | 3.10 – 3.12 | for the helper scripts |
| openssl | any | used to generate strong secrets and self-signed certs |
| 8 GB free disk | | Ollama model files |
| 8 GB RAM | | for the 7B model; less if you swap to phi3.5 |

## Quick check (no Docker)

To confirm the core works before standing up the full stack, the deterministic
`FakeLLM` backend exercises the whole evaluate → verify → sign path with no
Docker, no model download, and no secrets:

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Acceptance gate — verifiable-provenance + durability conformance (no infra):
pytest conformance/ -m "provenance or durability" -q          # -> 56 passed

# Or drive one evaluation directly:
PYTHONPATH=reference-implementation/src python - <<'EOF'
import asyncio
from ski_model.v3 import V3Evaluator, FakeLLM
snap = {"version": "demo", "obligations": [
    {"id": "energy.so2.lte_100ppm", "metric": "so2_ppm",
     "predicate": "must_not_exceed", "value": 100}]}
ev = V3Evaluator(llm=FakeLLM(), kg_version_hash="sha256:" + "0" * 64, decoder_seed=0)
env = asyncio.run(ev.aevaluate(measurement={"so2_ppm": 150}, kg_snapshot=snap))
print(env.verdict, "->", [c.node_id for c in env.kg_citations])  # FLAG -> ['energy.so2.lte_100ppm']
EOF
```

The full Docker-based stack below adds a real local LLM (Ollama), the Postgres
audit ledger, and TLS — but the evaluation logic is identical.

## Step 1 — Generate secrets and TLS certs

```bash
./scripts/setup.sh
```

This:

- writes `reference-implementation/.env` with mode 0600 (no defaults);
- generates a 32-byte random `SKI_API_KEY`;
- generates strong Postgres and Grafana passwords;
- generates a self-signed CA and per-service certs under
  `reference-implementation/tls/`.

The secrets exist only in the `.env` file. They are not echoed to your
terminal and won't be regenerated unless you delete `.env`.

## Step 2 — Pull the local LLM weights

```bash
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct
```

Other small open-weights options:

- `mistral:7b-instruct`
- `phi3.5:3.8b-mini-instruct` (smallest; lower quality)

Update `SKI_MODEL_NAME` in `.env` if you change models, and refresh
`SKI_MODEL_FILE_SHA256` to pin the exact artefact.

## Step 3 — Start the stack

```bash
./scripts/deploy.sh
```

The script waits up to 90s for `/api/health` to return 200. The default
profile starts:

- `ollama` (local LLM runtime)
- `ski-model` (the SKI Model service, port 8000 / TLS)
- `sidecar` (telemetry intake)
- `postgres` + `postgres-exporter`
- `prometheus` (port 9090)
- `grafana` (port 3000 / TLS)

Kafka and pgAdmin are opt-in via compose profiles `kafka` and `pgadmin`.

## Step 4 — Smoke test

```bash
# All four checks should report OK.
python scripts/test-connection.py --insecure

# Replay the demo telemetry. (The KG is unsigned for demo purposes, so
# either set KG_REQUIRE_SIGNATURE=false on the ski-model container or
# sign it with your own Ed25519 key.)
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure

# Inspect the verdicts.
python scripts/check-verdicts.py --insecure --limit 10

# Verify the audit ledger end-to-end (recomputes every entry hash).
python scripts/verify-ledger.py
```

Expected verdict mix for the energy demo:

- `CLEAR` for in-range measurements
- `FLAG` for breaches (SO₂ above 100 ppm, pH outside 6.0–8.5)
- `NULL_UNMAPPED` for the `facility.unknown.metric` record

## Step 5 — Dashboards

- Grafana: <https://localhost:3000> (user/password from `.env`)
- Prometheus: <http://localhost:9090>

Self-signed certs will trigger a browser warning. For non-local use,
replace `reference-implementation/tls/` with certs from your own CA.

## Common commands

```bash
# Tail logs
docker compose -f reference-implementation/docker-compose.yml logs -f ski-model sidecar

# Stop the stack (state preserved in volumes)
docker compose -f reference-implementation/docker-compose.yml down

# Stop and remove all volumes (DESTROYS the audit ledger — confirm policy)
docker compose -f reference-implementation/docker-compose.yml down -v
```

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md). Common gotchas:

- *SKI Model refuses to start with "KG signature verification FAILED"* —
  expected for the demo KG. Either sign your KG or set
  `KG_REQUIRE_SIGNATURE=false` (non-conformant; demo only).
- *`/api/canary` reports `degraded`* — the neuro-symbolic agreement
  monitor's LLM↔verifier agreement rate has dropped below threshold.
  Inspect recent verdicts for `LLM_CONTRADICTION` /
  `NEURO_SYMBOLIC_DIVERGENCE` statuses before processing more telemetry.
- *Sidecar can't reach the SKI Model* — TLS verification with the
  self-signed cert. Either set `SKI_MODEL_CA_CERT` to the path of
  `tls/ca.crt` (already wired in the compose file), or use `--insecure`
  in your own client.

## Next steps

- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) — full deployment guide
- [`docs/CUSTOMIZATION.md`](./docs/CUSTOMIZATION.md) — bring your own KG,
  swap backends, wire to your telemetry source
- [`../conformance/README.md`](../conformance/README.md) — run the
  conformance suite against this deployment
