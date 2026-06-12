# SKI Framework — Public Roadmap

This is the single authoritative roadmap. Release-by-release detail
lives in [CHANGELOG.md](./CHANGELOG.md); architectural rationale lives
in the [RFCs](./docs/RFCs/index.md). Dates are targets, not promises;
items move when reality disagrees with the plan. Discuss the roadmap in
[GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions).

**Current release:** see the [Releases page](https://github.com/kpifinity/ski-framework/releases).
**Specification:** v3.0 (versioned separately, via the RFC process).

## v3.1 — Prove the claims (target: Q3 2026)

The theme of v3.1 is that every public claim becomes a runnable
artifact.

- **Sovereignty (L3) conformance: 6 of 6.** Four checks are runnable
  today (`single_worker`, `no_outbound_calls`,
  `jurisdiction_scope_captured`, `signed_llm_transcript`). Remaining:
  the ledger tamper-resistance rig and the air-gapped boot fixture.
- **SKI Evals — verdict-accuracy evaluation suite.** Golden datasets
  per sector (energy first): labeled telemetry + KG + expected verdict
  and assertions. Published metrics per LLM backend: accuracy, FLAG
  recall (missed breaches), verifier-agreement rate, DISCRETIONARY
  routing precision. Run nightly; results published in the docs.
- **Performance benchmarks.** p50/p95/p99 verdict latency and
  throughput on stated reference hardware, per backend, harness in-repo.
- **vLLM backend** behind the existing `V3LLMBackend` protocol. Shipped:
  `SKI_V3_LLM_BACKEND=vllm` with decoder-level guided decoding.
- **Helm chart** (shipped: `deploy/helm/ski`) honoring the constraints in
  [KUBERNETES.md](./reference-implementation/docs/KUBERNETES.md)
  (append-only triggers across PVC rebinds, single writer per shard,
  sovereign-boundary NetworkPolicy).
- **`ski-schemas` extraction** (RFC 0003 PR 1): one shared package for
  envelope/transcript/measurement models.
- **PyPI distribution.** All five packages installable from PyPI via
  trusted publishing (`ski-sdk`, `ski-kg-extractor`, `ski-kg-validator`,
  `ski-model-deploy`, `ski-audit-ledger`).
- **EU AI Act crosswalk.** Formal mapping of SKI controls to EU AI Act
  articles (the regulatory crosswalk promised at v3.0). First revision
  shipped: [docs/crosswalks/eu-ai-act.md](./docs/crosswalks/eu-ai-act.md);
  revisions follow as harmonised standards and Commission guidance land.

## v3.2 — Scale and ecosystem (target: Q4 2026)

- **Kubernetes operator + CRDs** (`SkiModelDeployment`), shard router,
  ledger partitioning — designed via a dedicated RFC before code.
- **SKI MCP server.** Verdict queries, ledger verification, and
  coverage-register lookups exposed via the Model Context Protocol so
  AI agents and assistants can interrogate a SKI deployment.
- **llama.cpp backend.**
- **Additional sector example KGs** and tutorials.

## Later (v4.x / exploratory)

- TPM-attested model loading.
- Conformance certification program (KpiFinity-issued mark; see
  [TRADEMARKS.md](./TRADEMARKS.md)).
- Long-term-supported reference implementation line.
- TypeScript SDK, if adopter demand materializes.

## How to influence this roadmap

Open a Discussion for direction questions, an Issue for concrete gaps,
or an RFC for architectural changes (see
[docs/governance.md](./docs/governance.md)). Design-partner inquiries:
<hello@kpifinity.com>.
