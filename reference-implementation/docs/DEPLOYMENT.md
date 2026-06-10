# Deployment guide

> **⚠ STATUS: EARLY ALPHA.** Production deployment guidance is preliminary.

This document covers the docker-compose deployment in detail. For
Kubernetes, see [`KUBERNETES.md`](./KUBERNETES.md). For local laptop
exploration, the [`../QUICKSTART.md`](../QUICKSTART.md) is faster.

## Prerequisites

See [`../QUICKSTART.md#prerequisites`](../QUICKSTART.md#prerequisites).
The reference implementation does **not** require an Anthropic, OpenAI,
or any other vendor API key. Inference is local.

## Deployment modes

| Mode | Status | Use for |
|---|---|---|
| Single-node docker-compose | supported | Demo, PoC, single-team production |
| Air-gapped docker-compose | supported, requires pre-staged image+model | Classified / sovereign deployments |
| Kubernetes | Helm chart planned for v3.1 — see [ROADMAP.md](../../ROADMAP.md) | Multi-node production |
| Managed (BYOC) | planned | Customer-controlled cloud account, not KpiFinity-hosted |

The previously-documented "KpiFinity hosts your data" managed mode was
removed in v0.1.0-alpha because it contradicts the Sovereignty pillar.

## Single-node docker-compose

```bash
./scripts/setup.sh
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct
./scripts/deploy.sh
```

To enable optional services:

```bash
# Kafka telemetry source (default is file)
docker compose -f reference-implementation/docker-compose.yml --profile kafka up -d

# pgAdmin (NOT recommended outside dev)
docker compose -f reference-implementation/docker-compose.yml --profile pgadmin up -d
```

## Loading your Knowledge Graph

For non-conformant local demos:

```bash
cp /path/to/your-kg.json reference-implementation/examples/knowledge-graphs/kg.json
docker compose -f reference-implementation/docker-compose.yml restart ski-model
```

For real (signed) Knowledge Graphs, use `ski-model-deploy`:

```bash
ski-model-deploy load-kg \
  --kg /path/to/signed-kg.json \
  --endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY"
```

`ski-model-deploy` will refuse to upload an unsigned KG. There is no
flag to override this; if you need to test with an unsigned KG, set
`KG_REQUIRE_SIGNATURE=false` on the server side (and accept that this
disqualifies the deployment from any conformance level).

## Telemetry sources

### File (default)

`TELEMETRY_SOURCE=file`. The sidecar reads JSONL from
`/data/sample.jsonl` (mounted from `examples/telemetry/`).

### HTTP

`TELEMETRY_SOURCE=http`. POST records to `http://localhost:8001/api/telemetry`:

```bash
curl -sS http://localhost:8001/api/telemetry -H 'content-type: application/json' -d '{
  "id": "tel_1",
  "timestamp": "2026-05-22T10:00:00Z",
  "subject": "facility.so2.discharge_ppm",
  "measurement": {"so2_ppm": {"value": 85, "unit": "ppm"}}
}'
```

Records containing a `rule_id` field are rejected — producers must not
pre-route.

### Kafka

`TELEMETRY_SOURCE=kafka` and bring up the Kafka profile. SASL/SCRAM is
enabled. Update `monitoring/kafka_jaas.conf` with strong credentials
before any non-local use.

## Monitoring

| Surface | URL | Notes |
|---|---|---|
| Grafana | <https://localhost:3000> | TLS by default; admin password in `.env` |
| Prometheus | <http://localhost:9090> | Includes SKI alert rules |
| SKI Model health | <https://localhost:8000/api/health> | Requires `x-api-key` |
| Determinism canary | <https://localhost:8000/api/canary> | Requires `x-api-key` |

The SKI-specific alerts shipped under `monitoring/rules/ski-alerts.yml`:

- `SKIDeterminismCanaryFailed` (critical)
- `SKIKnowledgeGraphSignatureFailed` (critical)
- `SKILedgerSequenceGap` (critical)
- `SKISidecarHeartbeatLost` (warning)

Wire these to Alertmanager / PagerDuty / OpsGenie via your standard
operational tooling.

## Audit ledger

The ledger is append-only at the database layer. To explore it:

```bash
docker exec -it ski-ledger-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

\d ledger_entries
SELECT verdict, count(*) FROM ledger_entries GROUP BY verdict;
SELECT * FROM coverage_register LIMIT 10;
```

To verify integrity end-to-end (chain linkage + entry-hash recomputation):

```bash
python scripts/verify-ledger.py --strict
```

To back the ledger up (real `pg_dump`, not a stub):

```bash
audit-ledger backup --dsn "$LEDGER_DSN" --out ledger-2026-05-22.dump --verify
```

Retention is **your responsibility under documented policy**. The
included `scripts/cleanup.sh` refuses to touch `data/backups/` or
`data/ledger/`.

## Running the conformance suite against this deployment

```bash
pytest ../conformance/ -q -m level1 \
  --ski-endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY" \
  --ledger-dsn "$LEDGER_DSN"
```

A green run means this deployment satisfies SKI Level 1 conformance. See
[`../conformance/README.md`](../../conformance/README.md) for the full
test scope and how to publish a result badge.

## Production-track checklist

- [ ] Replace self-signed `tls/` certs with certs from your own CA.
- [ ] Move `SKI_API_KEY`, `POSTGRES_PASSWORD`, `GRAFANA_PASSWORD` into
      your secrets manager (Vault, AWS SM, GCP SM, …).
- [ ] Set `SKI_MODEL_FILE_SHA256` to the SHA-256 of the model file you
      actually run.
- [ ] Document your hardware baseline (CPU model, instruction set
      extensions, OS/kernel, Ollama version, model version).
- [ ] Sign your KG with your production Ed25519 key.
- [ ] Configure Alertmanager / PagerDuty for the SKI alert rules.
- [ ] Decide retention policy for the audit ledger and document it.
- [ ] Wire `audit-ledger backup` into a scheduled job.
- [ ] Run the conformance suite as part of every deployment promotion.
