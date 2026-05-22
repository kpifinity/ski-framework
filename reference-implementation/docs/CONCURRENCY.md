# Concurrency

The SKI Model service enforces `SKI_MODEL_WORKERS=1`. Trying to start
with a different value raises a `RuntimeError`. This document explains
why and how to scale.

## Why a single worker

The service has three pieces of state that must not be sharded across
worker processes:

1. **Ledger sequence number.** Two workers writing concurrently can both
   read sequence N as "last", produce two N+1 entries with different
   `previous_hash` linkages, and corrupt the chain. The Postgres
   `UNIQUE(sequence_number)` constraint will reject one of them — but
   only after the local hash has been computed against a stale
   `previous_hash`, so the rejected entry's prepared payload is
   meaningless to retry. We instead serialise writes in a single worker.
2. **Tag Registry & Knowledge Graph state.** The KG is loaded once and
   mutated only via `POST /api/kg/load`. If `load` arrives at worker A
   while worker B is mid-evaluate, B continues evaluating against the
   old KG without anyone noticing — a non-determinism source. A single
   worker eliminates this by construction.
3. **Determinism canary baseline.** The canary records a baseline on
   first call and compares subsequent calls. Multi-worker would record
   N baselines and never detect divergence between them.

A future release may split (1) into a small async writer thread and (2)
into a CoW snapshot — but the v0.1 reference implementation chooses
clarity over throughput.

## How to scale

Scale **horizontally**, not via uvicorn workers:

1. Run multiple `ski-model` containers behind a deterministic load
   balancer. "Deterministic" here means: a given `telemetry_id` always
   routes to the same container instance. This preserves the
   single-writer property per shard.
2. Shard by tenant or by data domain, not by random hash. Each shard
   has its own audit ledger (its own sequence space).
3. If a single shard cannot keep up with offered load, increase its
   per-record latency budget rather than its worker count.

For most regulated workloads (compliance evaluation at human-or-machine
event rates) a single container handles the throughput easily. If you
truly need higher throughput, the right answer is usually that more of
your rules should route through the Symbolic Evaluator (Track 1), which
is orders of magnitude faster than Track 2 LLM evaluation.

## What about uvicorn `--workers`?

`uvicorn` workers are separate Python processes. They do not share
state. Setting `--workers > 1` produces exactly the bugs (1)–(3) above.
The service refuses to start in that configuration.

## What about thread pools?

FastAPI runs `async` handlers on a single event loop. Synchronous
handlers are dispatched to a thread pool. SKI Model handlers are all
`async`, and the lock-free state (Tag Registry, KG) is read-only after
load. The ledger writer uses an explicit transaction per request.

## Observability for concurrency bugs

`SKILedgerSequenceGap` (Prometheus alert) fires if the audit ledger ever
develops a gap in `sequence_number`. If you see this, you are running
the service in a configuration it was not designed to support — most
likely multiple workers, or two containers writing to the same ledger.
