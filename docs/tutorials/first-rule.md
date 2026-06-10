# Your first rule

A 10-minute walkthrough from `git clone` to seeing a real verdict. By
the end, you'll have:

1. The reference implementation running locally.
2. A telemetry record evaluated against a real rule.
3. A verdict written to the append-only audit ledger.
4. The ledger independently re-verified.

This tutorial assumes you can run Docker. If you can't yet, see
[Getting started](../getting-started.md) for the install steps first.

---

## Step 1 — Clone and set up secrets

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework
./scripts/setup.sh
```

The setup script:

- generates a strong API key, Postgres password, and Grafana password
  into `reference-implementation/.env` (mode `0600`),
- generates a self-signed TLS CA + per-service certificates,
- verifies you have Docker, Python 3, and OpenSSL.

It will not overwrite an existing `.env`, so it's safe to re-run.

!!! tip "Demo signature override"
    For this tutorial we use the unsigned demo KG. Edit
    `reference-implementation/.env` and change
    `KG_REQUIRE_SIGNATURE=true` to `KG_REQUIRE_SIGNATURE=false`.
    This is non-conformant — production deployments MUST keep
    signature verification on.

## Step 2 — Pull the local LLM weights

```bash
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct
```

That downloads ~4.7 GB of model weights into the `ollama-models`
Docker volume. The model lives entirely inside your machine; no
external network call happens after this step.

## Step 3 — Stage the demo Knowledge Graph

The energy demo KG is at `examples/energy/knowledge-graphs/kg-energy-v3-demo.json`.
The SKI Model service expects a file literally named `kg.json` in its
mounted KG directory:

```bash
cp examples/energy/knowledge-graphs/kg-energy-v3-demo.json \
   reference-implementation/examples/knowledge-graphs/kg.json
```

## Step 4 — Start the full stack

```bash
docker compose -f reference-implementation/docker-compose.yml up -d
docker compose -f reference-implementation/docker-compose.yml ps
```

You should see seven containers `Up (healthy)`. The `ski-model` service
takes the longest (~60s) — it verifies and loads the KG, then serves on
`https://localhost:8000`.

## Step 5 — Send a telemetry record

```bash
python scripts/send-telemetry.py \
    examples/energy/telemetry/sample.jsonl \
    --insecure \
    --api-key "$(grep ^SKI_API_KEY reference-implementation/.env | cut -d= -f2)"
```

The script reads five JSON-lines from `sample.jsonl` and POSTs each
to the sidecar. Each record is:

1. matched against the KG slice in scope for its jurisdiction and
   timestamp,
2. evaluated by the **local LLM** (temperature 0, structured
   generation), whose formalizable assertions are independently
   re-checked by the **Symbolic Verifier**,
3. assigned one of the five verdicts,
4. appended to the Postgres **audit ledger** with its signed
   transcript and verdict envelope.

For this demo, you should see:

| Record subject | Value | Verdict | Why |
|---|---|---|---|
| SO2 discharge | 85 ppm | CLEAR | under the 100 ppm cap; verifier AGREED |
| SO2 discharge | 142 ppm | FLAG | over the 100 ppm cap; verifier AGREED |
| Wastewater pH | 7.2 | CLEAR | inside [6.0, 8.5] |
| Wastewater pH | 5.4 | FLAG | below 6.0 |
| `facility.unknown.metric` | — | NULL_UNMAPPED | subject not in the KG |

## Step 6 — Inspect the audit ledger

```bash
python scripts/check-verdicts.py \
    --insecure \
    --api-key "$(grep ^SKI_API_KEY reference-implementation/.env | cut -d= -f2)" \
    --limit 10
```

You'll see eight JSON entries with `sequence_number`, `telemetry_hash`,
`rule_id`, `verdict`, `reasoning`, and the chain hash linking each to
its predecessor.

## Step 7 — Verify the ledger is tamper-evident

This is the moment that separates SKI from a typical logging system.
We independently recompute every entry's hash from the canonical
serialization and confirm it matches what's stored.

```bash
export LEDGER_DSN="postgresql://$(grep ^POSTGRES_USER reference-implementation/.env | cut -d= -f2):$(grep ^POSTGRES_PASSWORD reference-implementation/.env | cut -d= -f2)@localhost:5432/ski_ledger"
python scripts/verify-ledger.py
```

Expected output:

```
Total entries:                8
Chain linkage verified:       8 / 8
Entry hash recomputed:        8 / 8
Sequence continuity:          True
Timestamp ordering:           True

Recommendation:
  Ledger integrity verified. No issues detected.
```

If you want to *prove* the append-only constraint:

```bash
docker exec -it ski-ledger-db psql \
    -U $(grep ^POSTGRES_USER reference-implementation/.env | cut -d= -f2) \
    -d ski_ledger \
    -c "UPDATE ledger_entries SET verdict = 'CLEAR' WHERE sequence_number = 2;"
```

Postgres will refuse:

```
ERROR:  ledger_entries is append-only
```

## Step 8 — Replay deterministically

The acid test: re-evaluate the recorded entries against the same KG
and confirm every symbolically verifiable verdict matches.

```bash
pip install -e tools/audit-ledger
audit-ledger replay \
    --source "$LEDGER_DSN" \
    --from-sequence 1 --to-sequence 8 \
    --kg-path reference-implementation/examples/knowledge-graphs/kg.json
```

Expected output:

```
Replay: 5/5 entries replayed, 5 matched, 0 diverged, 0 skipped.
```

For v3 entries, replay re-runs the symbolically verifiable part of each
verdict; the LLM reasoning itself is re-verified through the signed
transcript (provenance), not regenerated — see
[`docs/replay.md`](../replay.md).

## What just happened

You ran a real local LLM, evaluated real rules against real telemetry,
wrote real cryptographically-chained ledger entries, and proved the
result is deterministic by re-running it. The only things that were
mock were the telemetry values themselves — in production those would
come from a SCADA system or sensor stream.

## Next steps

- [Bring your own Knowledge Graph](../knowledge-graph.md) — write rules
  for your own domain.
- [Conformance levels](../conformance.md) — what does this deployment
  qualify for?
- [Architecture](../architecture.md) — what's actually under the hood?
- [Replay](../replay.md) — when and how to use deterministic replay
  in production.

## Tear down

```bash
# Stops everything but keeps the audit ledger and model weights:
docker compose -f reference-implementation/docker-compose.yml down

# Full clean slate (DELETES the audit ledger):
docker compose -f reference-implementation/docker-compose.yml down -v
```
