# Benchmarks

> **License:** CC BY 4.0. See [LICENSE-docs.md](../LICENSE-docs.md).

The SKI Framework's latency story has to be honest about what the
framework controls and what it does not. Per-verdict latency in a
deployment decomposes as:

```
end-to-end  =  framework overhead  +  LLM inference  +  ledger round-trip
```

The framework controls the first term: jurisdiction + effective-date
scoping (`scope_to`), prompt rendering, citation validation, the
Symbolic Verifier's per-assertion cross-check, risk-tier policy, and
ed25519 transcript signing. LLM inference time is a property of the
model and hardware the operator chooses; the ledger round-trip is a
property of their Postgres deployment. **"Sub-100ms" is therefore a
framework-overhead budget, not an end-to-end promise** — end-to-end
latency must be validated per deployment, and the suite ships a mode
for exactly that.

## The suite

`benchmarks/` measures the production code path — the same
`kg_loader.scope_to` → `V3Evaluator.aevaluate_with_transcript` flow
`server.py` runs, with real transcript signing — never a simulation.
The workload is the SKI Evals golden dataset, cycled deterministically,
with dataset hashes recorded in the run provenance.

```bash
# Framework overhead (in-process, deterministic FakeLLM, no infra):
python -m benchmarks.run --mode pipeline --n 2000 --warmup 200

# End-to-end against a live deployment (any backend it runs):
python -m benchmarks.run --mode http \
  --endpoint https://localhost:8000 --api-key "$SKI_API_KEY" \
  --n 200 --warmup 20

# CI gate — fail the build if the overhead budget is exceeded:
python -m benchmarks.run --mode pipeline --max-framework-p99-ms 100
```

Reports render as markdown (humans) and JSON (machines), both carrying
full provenance: dataset hashes, git commit, Python version, platform,
CPU count, and the verdict mix actually produced.

## Reference numbers — framework overhead

Pipeline mode, FakeLLM backend (model inference ≈ 0), 2,000 samples
after 200 warmup, transcript signing enabled. Workload:
`evals/datasets/energy` (50 golden cases, 10-obligation KG).

| Stage | p50 | p90 | p95 | p99 | mean | verdicts/s |
|---|---|---|---|---|---|---|
| KG scoping (`scope_to`) | 0.01 ms | 0.01 ms | 0.01 ms | 0.03 ms | 0.01 ms | — |
| Evaluate + verify + sign | 0.09 ms | 0.13 ms | 0.14 ms | 0.29 ms | 0.11 ms | — |
| **Framework total (per verdict)** | **0.10 ms** | **0.14 ms** | **0.16 ms** | **0.36 ms** | **0.12 ms** | ~8,500 |

Environment: Python 3.10, Linux aarch64, 2 vCPUs (deliberately modest —
commodity-edge-class, not a benchmarking rig). Reproduce with the first
command above; CI uploads a fresh report artifact on every build and
gates on `framework_total` p99 ≤ 100 ms.

The headline: **framework overhead is sub-millisecond at p99** — about
250× inside the 100 ms budget on 2 vCPUs. In a real deployment,
per-verdict latency is dominated by LLM inference (hundreds of ms to
seconds for a 7B-class model on CPU; tens of ms on a GPU with vLLM) and
the audit-ledger append (single-digit ms on a local Postgres). The
framework does not meaningfully add to either.

## Scope and caveats

- **Single worker by design.** The runtime enforces
  `SKI_MODEL_WORKERS=1` (see `docs/CONCURRENCY.md`), so throughput
  scales by sharding deployments, not by adding workers. The
  verdicts/s figure above is the single-worker ceiling imposed by
  framework overhead alone; a deployment's real ceiling is its model's
  inference throughput.
- **`http` mode measures everything.** FastAPI, auth, TLS, scoping,
  inference, verification, signing, and the ledger append — the number
  an operator should validate and record per deployment.
- **No KG-size scaling claims yet.** The workload KG has 10
  obligations. `scope_to` is a linear scan; numbers for real-sized KGs
  (hundreds to thousands of obligations) land with the sector KG work.
- Shared CI runners are noisy; the CI gate exists to catch order-of-
  magnitude regressions, not single-digit-percent drift. Trend numbers
  belong in the per-build artifacts, reference numbers in this page.
