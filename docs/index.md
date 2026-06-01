---
hide:
  - toc
---

# SKI Framework

**Sovereign Knowledge Intelligence** — an open neuro-symbolic architecture for AI compliance in regulated industries.

[![License (code)](https://img.shields.io/badge/License%20(code)-Apache%202.0-blue.svg)](https://github.com/kpifinity/ski-framework/blob/main/LICENSE)
[![License (spec)](https://img.shields.io/badge/License%20(spec)-CC%20BY%204.0-lightgrey.svg)](https://github.com/kpifinity/ski-framework/blob/main/LICENSE-docs.md)
[![Release](https://img.shields.io/badge/Release-v3.0.0-blue.svg)](https://github.com/kpifinity/ski-framework/releases)
[![Spec](https://img.shields.io/badge/Spec-v3.0-blue.svg)](https://skiframework.org)

!!! success "Status — v3.0 is current"
    A KG-grounded sovereign LLM is the primary reasoner on every verdict.
    The Symbolic Evaluator is repositioned as an independent verifier of
    the LLM's formalizable assertions. The Knowledge Graph is a typed
    semantic substrate with jurisdictional scope and effective-date
    intervals. The audit trail moves from *deterministic replay* to
    *verifiable provenance*. The architectural rationale is in
    [RFC 0002](RFCs/0002-v3-neuro-symbolic-pivot.md) (Accepted,
    implemented across PRs 8–14).

## Why SKI exists

Regulated industries — energy, finance, manufacturing, defense — need AI in
core operational systems but cannot adopt frontier-model chatbots or
cloud-hosted compliance APIs. The reasons are non-negotiable: operational
data cannot leave the deployment perimeter, every decision must trace to
a specific regulation, the audit story must survive cross-examination,
and human judgment must remain the final authority. A rule engine
satisfies the audit requirement but cannot reason about regulatory
language. A frontier LLM can reason but ships data and cannot prove how
it decided. SKI is the architecture that meets all four requirements
simultaneously.

| Pillar | What it means | How SKI delivers it |
|---|---|---|
| **Sovereign** | All evaluation runs on customer infrastructure; no data egress during inference | Local LLM runtime (Ollama, vLLM, or llama.cpp); model weights, KG, and ledger stay on the host |
| **Knowledge** | Regulations are a typed semantic substrate the system reasons over, not free text | Knowledge Graph with typed obligations, jurisdictional scope, exemptions, precedent, citations |
| **Intelligence** | An LLM that understands regulatory language, with its reasoning made auditable | KG-grounded local LLM (v3 primary); symbolic verifier on the formalizable subset; signed transcripts |
| **Human primacy** | AI supports human judgment, never replaces it | Five-verdict taxonomy with explicit `DISCRETIONARY`; high-tier rules require attestation tokens |

## What you get

<div class="grid cards" markdown>

-   :material-brain:{ .lg .middle } **KG-grounded local LLM**

    ---

    Sovereign local model (Ollama / vLLM / llama.cpp), temperature=0,
    structured generation. Reads the typed KG slice for each rule;
    emits a verdict, reasoning, KG citations, and formalizable
    assertions.

    [:octicons-arrow-right-24: RFC 0002](RFCs/0002-v3-neuro-symbolic-pivot.md)

-   :material-shield-check:{ .lg .middle } **Symbolic Verifier**

    ---

    Independent cross-check of the LLM's formalizable assertions —
    numeric bounds, set membership, temporal windows. Disagreement is
    a first-class signal recorded in the ledger.

    [:octicons-arrow-right-24: Architecture](architecture.md)

-   :material-file-document-multiple:{ .lg .middle } **Knowledge Graph**

    ---

    Typed semantic substrate: obligations, definitions, exemptions,
    jurisdictional scope, effective-date intervals, precedent edges.
    Ed25519-signed; the runtime refuses to load an unsigned KG.

    [:octicons-arrow-right-24: KG schema](knowledge-graph.md)

-   :material-database-lock:{ .lg .middle } **Verifiable audit ledger**

    ---

    Postgres triggers reject UPDATE, DELETE, TRUNCATE. Each entry's
    hash chains to the prior; v3 adds signed LLM transcript, model
    weight hash, KG version hash, KG citations, verifier result.

    [:octicons-arrow-right-24: Replay docs](replay.md)

-   :material-shield-account:{ .lg .middle } **Conformance suite**

    ---

    Black-box Provenance / Durability / Sovereignty tests citing the
    spec section they validate. Verifiable provenance is the audit
    contract every conformant runtime must produce.

    [:octicons-arrow-right-24: Conformance](conformance.md)

-   :material-gavel:{ .lg .middle } **Governance and RFCs**

    ---

    Lazy-consensus model with named maintainer teams. Architectural
    changes go through RFCs; the v3 pivot is RFC 0002.

    [:octicons-arrow-right-24: Governance](governance.md)

</div>

## How SKI differs

A rule engine is fast and easy to audit but cannot reason about an actual
regulation's language. A frontier-model chatbot can reason but ships data
to a vendor and cannot prove how a decision was made. SKI sits between:
an LLM reasons over a curated, signed knowledge graph that captures the
regulation's structure; a symbolic verifier catches the subset the LLM
can hallucinate on; every step is signed and chained into an append-only
ledger. Each pillar is non-negotiable. Remove sovereignty and you cannot
deploy in a regulated environment. Remove the knowledge graph and the
LLM has no ground truth. Remove the symbolic verifier and an LLM can
hallucinate a `CLEAR` verdict on a value that is plainly over the limit.

## Quick start

Clone the repo, run `scripts/setup.sh` to generate TLS certificates and
a `.env` file, start the Ollama container, pull the default
open-weights model (`qwen2.5:7b-instruct`), bring up the rest of the
stack with `docker compose`, send a sample telemetry record from
`examples/`, and verify the audit ledger. The full walkthrough is in
[Getting started](getting-started.md); the 10-minute newcomer path is
in [Your first rule](tutorials/first-rule.md).

## Who's behind this

[KpiFinity Inc.](https://kpifinity.com) — a Calgary-based technology and
consulting firm specialising in AI governance and compliance automation
for regulated industries.

The **specification** is permissively licensed (CC BY 4.0) and is open
to community evolution. The **reference implementation** and **tools**
in this repository are Apache 2.0. The **Knowledge Graph libraries**
for energy, finance, manufacturing, and defense are proprietary and
licensed separately by KpiFinity.
