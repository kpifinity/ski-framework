# Troubleshooting

## SKI Model won't start

### "KG signature verification FAILED. Refusing to load."
The KG at `KG_PATH` is unsigned, has an invalid signature, or has been
tampered with. This is the spec-correct behaviour.

- For local demos, set `KG_REQUIRE_SIGNATURE=false`. **This disqualifies
  the deployment from any conformance level.**
- For real KGs, re-sign with `ski-model-deploy sign-kg`.

### "SKI_MODEL_WORKERS must be 1."
You tried to start with `SKI_MODEL_WORKERS != 1`. The service refuses
this configuration. See [`CONCURRENCY.md`](./CONCURRENCY.md).

### "Service misconfiguration: API_KEY_REQUIRED=true but no API_KEY set."
Add `SKI_API_KEY` to `.env` (or your secrets source) and restart. Set
one via `openssl rand -hex 32` — `scripts/setup.sh` will do this if
you run it before deploy.

### "ANTHROPIC_API_KEY required"
You set `SKI_INFERENCE_BACKEND=anthropic` (the non-conformant demo
backend). Either supply the key, or — preferably — set
`SKI_INFERENCE_BACKEND=ollama`.

### Ollama health check fails
```bash
docker logs ski-ollama
docker exec ski-ollama ollama list
```
Confirm `SKI_MODEL_NAME` matches a model that's actually been pulled.

## Determinism canary FAILED

`SKI_canary_status: FAILED` in `/api/canary` means the backend returned
a different result for the same input. Causes, in order of likelihood:

1. **Seed not propagated.** Confirm `SKI_MODEL_SEED` is set and matches
   what was used to record the baseline. Restart the service to reset
   the baseline.
2. **Model file swapped.** Run `sha256sum` on the model file inside the
   Ollama volume and compare to `SKI_MODEL_FILE_SHA256`. If they
   differ, you have a silent model change.
3. **Runtime non-determinism in the backend.** Some Ollama versions
   ignore `top_k=1` for certain models. Try a different model
   (`qwen2.5:7b-instruct` is well-behaved in our tests).
4. **GPU non-determinism.** Some CUDA kernels are non-deterministic by
   default. For demo purposes use CPU inference; for production use
   `CUBLAS_WORKSPACE_CONFIG=:4096:8` and `PYTHONHASHSEED=0`.

## Sidecar cannot reach SKI Model

### TLS verification fails
`SKI_MODEL_CA_CERT` should point at `/app/tls/ca.crt`. If you regenerated
certs after the sidecar started, restart the sidecar.

### Connection refused
```bash
docker logs ski-model
docker exec ski-sidecar curl -k -sS https://ski-model:8000/api/health
```

## Audit ledger issues

### `SKILedgerSequenceGap` alert
A gap in `sequence_number` was detected. Causes:

- Multiple writers (you ran more than one ski-model container against
  the same Postgres ledger). Fix: one writer per shard.
- A failed insert that nonetheless consumed a sequence number. Postgres
  `SERIAL` does not reuse on failure — this is expected for `id`, but
  `sequence_number` is application-assigned and should be gap-free. If
  you see this, file an issue with the failing log line.

### `verify_integrity` reports `ENTRY_HASH_MISMATCH`
Someone has modified a row in `ledger_entries`. Investigate immediately:
- Confirm Postgres triggers are installed (`\df ledger_block_update_delete`).
- Confirm the writing role does not have `BYPASSRLS` or superuser.
- Take a forensic snapshot before further investigation.

### `pg_dump` not found
```bash
pip install --upgrade audit-ledger
apt-get install -y postgresql-client          # on the host
```
or use the audit-ledger CLI inside a container that has `postgresql-client`.

## Prometheus & Grafana

### "context deadline exceeded" on a target
The target is unreachable or refusing TLS. For the SKI Model target,
`insecure_skip_verify: true` is set by default (self-signed CA).

### No Postgres metrics
Confirm `postgres-exporter` is up:
```bash
docker compose -f reference-implementation/docker-compose.yml ps postgres-exporter
curl -sS http://localhost:9187/metrics | head
```
Postgres does not expose `/metrics` natively — the exporter is required.

## Performance

Track 1 (Symbolic Evaluator) is microseconds per evaluation. Track 2
(LLM-bounded) is hundreds of milliseconds to seconds depending on the
model. If you need higher throughput:

1. Move as many rules as possible from Track 2 to Track 1 by introducing
   structured predicates.
2. Shard horizontally (one ski-model container per shard with affinity
   routing). See [`CONCURRENCY.md`](./CONCURRENCY.md).
3. Use a smaller model (`phi3.5:3.8b-mini-instruct`) — at the cost of
   quality on harder Track 2 rules.

## Reporting issues

If none of the above applies, please file a bug:

- <https://github.com/kpifinity/ski-framework/issues/new/choose>
- Include the version, deployment mode, backend, and stack traces.
- Do NOT include secrets, customer data, or signed KG contents.
