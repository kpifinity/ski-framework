---
hide:
  - toc
---

# SKI Framework

**Sovereign Knowledge Intelligence** — an open architecture for deterministic
AI compliance monitoring in regulated industries.

[![License (code)](https://img.shields.io/badge/License%20(code)-Apache%202.0-blue.svg)](https://github.com/kpifinity/ski-framework/blob/main/LICENSE)
[![License (spec)](https://img.shields.io/badge/License%20(spec)-CC%20BY%204.0-lightgrey.svg)](https://github.com/kpifinity/ski-framework/blob/main/LICENSE-docs.md)
[![Release](https://img.shields.io/badge/Release-v0.2.1-blue.svg)](https://github.com/kpifinity/ski-framework/releases/tag/v0.2.1)
[![Spec](https://img.shields.io/badge/Spec-v2.1-blue.svg)](https://skiframework.org)

!!! warning "Status: ALPHA (v0.2.1)"
    The specification is stable at v2.1. The reference implementation and
    tools are pre-production quality. v0.2.x closes stateful evaluation and
    deterministic replay; production-track features (horizontal scaling,
    Kubernetes operator, Level 3 assurance) are on the v0.3 / v0.4 roadmap.

## Why SKI exists

Regulated industries — energy, finance, manufacturing, defense — cannot
adopt AI in core operational systems because existing solutions fail on
four non-negotiable requirements:

| Pillar | What it means | How SKI delivers it |
|---|---|---|
| **Determinism** | Same input always produces the same verdict | Two-phase architecture: probabilistic compilation, deterministic runtime |
| **Sovereignty** | Operational data never leaves the boundary | Local LLM runtime (Ollama) by default; no cloud calls during inference |
| **Auditability** | Every verdict traces directly to a regulation | Append-only audit ledger with database-level enforcement |
| **Human primacy** | AI supports judgment, never replaces it | Five-verdict taxonomy with explicit `DISCRETIONARY` route to humans |

## What you get

<div class="grid cards" markdown>

-   :material-flash:{ .lg .middle } **Symbolic Evaluator (Track 1)**

    ---

    Deterministic predicate evaluation. No LLM in the runtime path for
    Track 1 rules. Stateful predicates (`window_avg`, `since_last`,
    `debounce`) operate against a Postgres-backed telemetry buffer.

    [:octicons-arrow-right-24: Architecture](architecture.md)

-   :material-database-lock:{ .lg .middle } **Append-only audit ledger**

    ---

    Postgres triggers reject `UPDATE`, `DELETE`, and `TRUNCATE` on
    `ledger_entries`. Each entry's hash chains to the prior; a third
    party can independently re-verify the ledger.

    [:octicons-arrow-right-24: Replay docs](replay.md)

-   :material-shield-check:{ .lg .middle } **Conformance suite**

    ---

    Black-box tests defining Level 1 / 2 / 3 conformance. Each test
    cites the spec section it validates. Run against any implementation.

    [:octicons-arrow-right-24: Conformance](conformance.md)

-   :material-file-document-multiple:{ .lg .middle } **Knowledge Graph**

    ---

    Compiled, Ed25519-signed, tag-registry-routed rules. Human-reviewed
    in Phase 1; the runtime refuses to load unsigned KGs by default.

    [:octicons-arrow-right-24: KG schema](knowledge-graph.md)

</div>

## Quick start

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework
./scripts/setup.sh
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct
docker compose -f reference-implementation/docker-compose.yml up -d
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl --insecure
```

See [Getting started](getting-started.md) for the full walkthrough, or
[Your first rule](tutorials/first-rule.md) for a 10-minute newcomer
tutorial.

## Who's behind this

[KpiFinity Inc.](https://kpifinity.com) — Calgary-based technology and
consulting firm specialising in AI governance and compliance automation
for regulated industries.

The **specification** is permissively licensed (CC BY 4.0) and is open
to community evolution. The **reference implementation** and **tools** in
this repository are Apache 2.0. The **Knowledge Graph libraries** for
energy / finance / manufacturing / defense are proprietary and licensed
separately by KpiFinity.
