# Customization

Common customisations for the SKI Framework reference implementation.

## 1. Bring your own Knowledge Graph

```bash
# Validate locally before uploading (pip install ski-kg-validator)
kg-validator validate -i /path/to/your-signed-kg.json

# Upload via the deploy tool (signature required)
ski-model-deploy load-kg \
  --kg /path/to/your-signed-kg.json \
  --endpoint https://localhost:8000 \
  --api-key "$SKI_API_KEY"
```

Your KG must be a v3 typed graph (spec §3):

- typed obligations from the closed enumeration, each with `metric`,
  `value`, `unit`, and `effective_date_start`;
- `applies_to` edges routing every telemetry subject to a rule;
- `scoped_to` and `cited_by` edges on every obligation (jurisdiction +
  citation);
- a declared `risk_tier` on every rule (the caller can never set one);
- an Ed25519 signature over the canonical serialization.

See [docs/knowledge-graph.md](https://kpifinity.github.io/ski-framework/knowledge-graph/)
for the full shape and `kg-validator` for the checks.

## 2. Swap the inference backend

The reference implementation supports two backends today via
`SKI_INFERENCE_BACKEND`:

| Value | Status |
|---|---|
| `ollama` (default) | Conformant. Local. |
| `anthropic` | Non-conformant demo mode. Logs a warning on every call. |

Additional backends (`vllm`, `llama_cpp`, `bedrock`, `vertex`) are
planned. The interface lives in `src/ski_model/backends.py` —
implementations need to provide `evaluate()` and `canary_eval()`.

## 3. Secrets management

The reference implementation reads secrets from environment variables.
To plug into a secrets manager:

### HashiCorp Vault

```bash
export VAULT_ADDR=https://vault.your-org/
export VAULT_TOKEN=...

eval "$(vault kv get -format=json secret/ski/prod | jq -r '
  .data.data | to_entries[] | "export \(.key)=\(.value)"
')"

docker compose -f reference-implementation/docker-compose.yml up -d
```

### AWS Secrets Manager

```bash
aws secretsmanager get-secret-value --secret-id ski/prod --query SecretString --output text \
  | jq -r 'to_entries[] | "export \(.key)=\(.value)"' \
  | source /dev/stdin
```

### Mounted file (Kubernetes ExternalSecrets / Vault Agent)

Set `--env-file` to a path written by your secret-syncing agent. The
docker compose stack already supports this via `--env-file`.

## 4. Telemetry sources

| Source | Configuration |
|---|---|
| File | `TELEMETRY_SOURCE=file`. Place JSONL under `examples/telemetry/sample.jsonl`. |
| HTTP | `TELEMETRY_SOURCE=http`. POST to `:8001/api/telemetry`. |
| Kafka | `TELEMETRY_SOURCE=kafka`. SASL/SCRAM auth. Compose profile `kafka`. |
| MCP | planned for v3.2 — see [ROADMAP.md](../../ROADMAP.md) |

## 5. Hardware baseline

For Pillar I (Intelligence) determinism audits you need a documented
baseline. Capture and version-control:

- CPU model (`/proc/cpuinfo`)
- Instruction set extensions (avx2, avx512, etc.)
- OS / kernel
- Container runtime version
- Ollama version
- Model file SHA-256

The SKI Model refuses to start if `SKI_MODEL_FILE_SHA256` is set but
doesn't match the actual model artefact, which protects against silent
model swaps.

## 6. Air-gapped operation

Set `networks.ski-internal.internal: true` in `docker-compose.yml` and
pre-stage all images and the Ollama model files on physical media.

```bash
# On a connected host
docker save \
  ollama/ollama:0.3.12 \
  postgres:15.6-alpine \
  prom/prometheus:v2.50.1 \
  grafana/grafana:10.4.1 \
  ski-model:local \
  ski-sidecar:local \
  > ski-images.tar
docker exec ski-ollama ollama pull qwen2.5:7b-instruct
docker run --rm -v ollama-models:/from -v "$PWD":/to alpine tar -czf /to/ollama-models.tgz -C /from .

# On the air-gapped host
docker load < ski-images.tar
docker run --rm -v ollama-models:/to -v "$PWD":/from alpine tar -xzf /from/ollama-models.tgz -C /to
```

## 7. Custom alert routing

The shipped `monitoring/rules/ski-alerts.yml` declares alert rules but
no Alertmanager target. Add one by creating
`monitoring/alertmanager.yml`, mounting it into a new `alertmanager`
service in `docker-compose.yml`, and adding it under `alerting` in
`prometheus.yml`. This is standard Prometheus operations — no
SKI-specific gotchas.

## 8. Adding rules to an existing demo

For learning purposes:

1. Edit `examples/<sector>/knowledge-graphs/kg-<sector>-v3-demo.json`.
2. Add the new Subject node, the Obligation node, and the `applies_to` /
   `consists_of` / `scoped_to` / `cited_by` edges so it resolves.
3. Run `kg-validator validate -i <file>` to catch any schema or
   referential-integrity mistakes before loading.

For real deployments, edit a signed production KG through the
`kg-extractor` → `kg-validator` → `ski-model-deploy` pipeline. Do not
hand-edit signed KGs — the signature will not verify.
