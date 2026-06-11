# SKI Framework

> **Sovereign Knowledge Intelligence** — an open neuro-symbolic architecture for AI compliance in regulated industries.

> **STATUS.** The specification is at **v3.0**; the reference implementation is on the **v3.1.0-alpha** line ([releases](https://github.com/kpifinity/ski-framework/releases), [PyPI](https://pypi.org/project/ski-sdk/)). A KG-grounded sovereign LLM is the primary reasoner on every verdict; the Symbolic Evaluator is repositioned as an independent verifier of the LLM's formalizable assertions; the Knowledge Graph is a typed semantic substrate, not a routing table. The audit trail moves from *deterministic replay* to *verifiable provenance*. The architectural rationale is in [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md) (Accepted; implemented in v3.0.0). See [CHANGELOG.md](./CHANGELOG.md) for the full ship log and [ROADMAP.md](./ROADMAP.md) for what's next.

[![License: Apache-2.0 (code)](https://img.shields.io/badge/License%20(code)-Apache%202.0-blue.svg)](./LICENSE)
[![License: CC BY 4.0 (spec)](https://img.shields.io/badge/License%20(spec)-CC%20BY%204.0-lightgrey.svg)](./LICENSE-docs.md)
[![Spec](https://img.shields.io/badge/Spec-v3.0-blue.svg)](https://skiframework.org)
[![Release](https://img.shields.io/github/v/release/kpifinity/ski-framework?label=Release&color=blue)](https://github.com/kpifinity/ski-framework/releases)
[![Docs](https://img.shields.io/badge/Docs-MkDocs%20Material-blue.svg)](https://kpifinity.github.io/ski-framework/)

## What SKI is

SKI is an open neuro-symbolic compliance system designed for regulated industries — energy, finance, manufacturing, defense — where every automated decision must be defensible to an auditor, a regulator, or a court. The framework's name decomposes into three pillars, each load-bearing:

**Sovereign.** Every component of evaluation runs on the customer's own infrastructure. Model weights, knowledge graph, evaluator, verifier, ledger, and signing keys never leave the deployment perimeter. The reference deployment uses a local LLM runtime (Ollama, vLLM, or llama.cpp on customer hardware); there are no external API calls during evaluation. The EU AI Act (broadly enforceable from 2026-08-02), DORA, and equivalent regulations in other jurisdictions are turning this from a preference into a legal requirement.

**Knowledge.** SKI's Knowledge Graph is the framework's brain, not a routing table. In v3 it is a typed semantic substrate: every obligation has a structured operand and jurisdictional scope, every exemption is a first-class edge, every definition is resolvable, every node carries a citation back to the originating regulation. The KG is human-reviewed in Phase 1 (offline compilation by `kg-extractor` and `kg-validator`) and signed; the runtime refuses to load an unsigned KG.

**Intelligence.** A sovereign local LLM is the primary reasoner on every verdict. It is grounded in the relevant slice of the Knowledge Graph (typed obligations, definitions, exemptions, precedent), runs with temperature=0 and structured-generation constraints, and emits a verdict together with reasoning, KG citations, and a structured set of formalizable assertions. A separate Symbolic Verifier independently checks the formalizable subset (numeric bounds, set membership, temporal windows) and records its result alongside the LLM's. Disagreement is a first-class signal, not an error.

The output is a **verifiable verdict**: every downstream auditor can reconstruct exactly how the decision was produced (which model weights, which KG version, which prompt template, which decoder seed, which KG citations, which symbolic checks) and re-verify each step. Defensibility in 2026 is provenance, not bit-identical determinism — and provenance is what SKI gives you.

## How SKI differs from a rule engine and from a generic LLM chatbot

A rule engine is fast and easy to audit but cannot reason about the language of an actual regulation. A frontier-model chatbot can interpret regulation but ships data to a vendor, cannot prove how a decision was made, and is not certifiable. SKI sits between: an LLM reasons over a curated, signed knowledge graph that captures the regulation's structure; a symbolic verifier catches the subset the LLM can hallucinate on; every step is signed and chained into an append-only ledger. Each pillar is non-negotiable. Remove sovereignty and you cannot deploy in a regulated environment. Remove the knowledge graph and the LLM has no ground truth. Remove the symbolic verifier and an LLM can hallucinate a `CLEAR` verdict on a value that is plainly over the limit.

## Documentation

Full documentation is published at **<https://kpifinity.github.io/ski-framework/>** — searchable, with the architecture overview, a glossary of regulatory and framework terms, the governance model, the threat model, RFCs (including [RFC 0002 — SKI v3 Neuro-Symbolic Pivot](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md)), and a 10-minute newcomer tutorial.

For the source of those pages, see [`docs/`](./docs/) in this repository.

## What's in this repository

This repository is the open half of the SKI ecosystem. The commercial half (Knowledge Graph libraries for specific industries, certified MCP connectors, managed implementation services) lives behind [KpiFinity](https://kpifinity.com).

The repo layout is:

- `docs/` — Specification documents (CC BY 4.0), architecture, RFCs, threat model, governance.
- `reference-implementation/` — Phase 2 runtime (Apache 2.0): the SKI Model service, the Symbolic Evaluator / Verifier, the Tag Registry, the audit ledger schema, and the read-only telemetry sidecar.
- `tools/` — Four CLI tools (Apache 2.0): `kg-extractor` (extract candidate rules from regulatory documents), `kg-validator` (human-in-the-loop validation), `ski-model-deploy` (sign and deploy a Knowledge Graph), `audit-ledger` (verify, export, back up the ledger).
- `examples/` — Demo-only illustrative KGs and telemetry. Never production-grade.
- `conformance/` — The SKI conformance test suite (Apache 2.0): Level 1 / 2 / 3 tests that any implementation can be run against.
- `evals/` — SKI Evals (Apache 2.0): the verdict-accuracy suite — golden datasets + metrics (FLAG recall, verifier agreement) run against the real evaluation path. See [docs/evals.md](./docs/evals.md).
- `scripts/` — Setup, deploy, and cleanup helpers.

## Quick start

### Install from PyPI

```bash
pip install ski-sdk          # typed client + one-call provenance verification
pip install ski-kg-extractor ski-kg-validator ski-model-deploy ski-audit-ledger
```

The CLI command names are unchanged (`kg-extractor`, `kg-validator`,
`ski-model-deploy`, `audit-ledger`). PyPI publication starts with the
first release after June 2026; earlier wheels are attached to
[GitHub Releases](https://github.com/kpifinity/ski-framework/releases),
each with a cosign signature and SLSA provenance.

### Run the full stack

The reference implementation runs entirely on-premise. It does not require — and by default does not have — any cloud API key. Inference is performed by a local LLM runtime (Ollama). An optional "demo" backend can call the Anthropic API; it is non-conformant and clearly labelled as such.

To run the stack: clone the repo, run `./scripts/setup.sh` to generate TLS certificates and write a `.env` file, start the Ollama container, pull the default open-weights model (`qwen2.5:7b-instruct`), bring up the rest of the stack with `docker compose`, send a sample telemetry record from `examples/`, and verify the audit ledger. The full walkthrough is in [reference-implementation/QUICKSTART.md](./reference-implementation/QUICKSTART.md). Production-track guidance is in [reference-implementation/docs/DEPLOYMENT.md](./reference-implementation/docs/DEPLOYMENT.md).

## Architecture

Every verdict takes the same path: telemetry arrives, the Knowledge Graph is scoped to the obligations applicable to the tenant's jurisdiction and the measurement's effective date, the local LLM evaluates against that scoped snapshot with structured-generation constraints, the Symbolic Verifier independently cross-checks the formalizable subset (numeric bounds, set membership, temporal windows, stateful window predicates), the Risk-Tier Governor derives the strictest applicable tier from the KG, and the ledger records the full provenance — signed LLM transcript, model weight hash, KG version hash, KG citations, verifier result, agreement-monitor status. The audit story is *verifiable provenance of a neuro-symbolic decision*, not bit-identical replay of a rule engine — the stronger defensibility story for 2026. The full architecture is in [docs/architecture.md](./docs/architecture.md); the design rationale is in [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md).

## Verdicts

SKI produces exactly five verdict types. No scores, no confidence intervals, no probabilistic ranges. The taxonomy is preserved across v2.1 and v3.

| Verdict | Meaning | Action |
|---|---|---|
| **CLEAR** | Applicable rules evaluated; no compliance issue detected | Normal operation; logged to audit ledger |
| **FLAG** | A compliance rule has been breached | Escalate to designated human reviewer; create incident |
| **NULL_UNMAPPED** | Telemetry subject is not present in the Knowledge Graph | Document in Coverage Register; expand KG |
| **NULL_STALE** | Rule matched but its time-window predicate has expired | Investigate upstream freshness; expand KG buffer |
| **DISCRETIONARY** | Rule applies but requires qualified human judgment | Route to compliance expert for decision |

The verdict envelope carries the LLM transcript reference, KG citations, formalizable assertions, the symbolic verifier's per-assertion result, and model provenance metadata (model weight hash, KG version hash, prompt template hash, decoder seed, structured-grammar hash). The five-value taxonomy itself is preserved from v2.

## Components

The specification under `docs/` defines the architecture, the Knowledge Graph schema (typed obligations, jurisdictional scope, effective dates, precedent edges), the Risk-Tier Governor, the Symbolic Verifier contract, the verdict envelope, and the audit ledger canonical serialization. It is CC BY 4.0.

The reference implementation under `reference-implementation/` includes the v3 Evaluator (KG-grounded LLM + structured generation), the Symbolic Verifier with five stateless predicates and three stateful (window_count / window_sum / window_avg), the SKI Model service with pluggable LLM backends (FakeLLM for tests, Ollama for sovereign deployment), the signed-KG loader (Ed25519) with jurisdiction + effective-date scoping, the append-only audit ledger with database-level triggers, the agreement monitor (rolling LLM↔verifier health signal), the Risk-Tier Governor, signed LLM transcripts, and a Postgres-backed telemetry buffer. Kubernetes deployment (Helm chart) is targeted for v3.1; horizontal scaling and the operator for v3.2 — see [ROADMAP.md](./ROADMAP.md).

The four CLI tools under `tools/` cover the framework's lifecycle: `kg-extractor` reads regulatory documents and emits v3 Knowledge Graphs; `kg-validator` runs the schema + §3.6 validation passes; `ski-model-deploy` refuses to load unsigned KGs; `audit-ledger` performs real hash recomputation, replay against historical telemetry, and uses real `pg_dump` for backups.

The conformance test suite under `conformance/` defines three levels — **Provenance** (verdict envelope is complete and verifier-checked), **Durability** (provenance is signed, replayable, audit-chained), **Sovereignty** (operable air-gapped, tamper-evident, end-to-end signed) — as runnable black-box tests. Each test cites the specification section it validates.

The Knowledge Graph libraries for specific industries (energy, finance, manufacturing, defense) are proprietary and licensed separately by [KpiFinity](https://kpifinity.com).

## Conformance levels

| Level | What it proves |
|---|---|
| **Provenance** | Every verdict envelope is well-formed, KG citations exist, the Symbolic Verifier ran and emitted one of the four spec-normative statuses, the agreement monitor is mounted, and the verdict taxonomy is exactly the five canonical values. |
| **Durability** | The KG is signed; the Risk-Tier Governor is strict (caller cannot self-declare tier); the audit ledger is append-only at the DB layer; hash-chain integrity recomputes entry hashes (not just chain linkage); the replay primitive can reproduce historical verdicts. |
| **Sovereignty** | The runtime makes zero outbound HTTP calls during evaluation when the LLM is local; boots air-gapped; tamper attempts on the ledger fail closed; recorded transcripts carry the jurisdiction scope; LLM transcript signatures verify. (Scaffolded; harness is the v3.1 milestone.) |

See [docs/conformance.md](./docs/conformance.md) for the methodology and [conformance/README.md](./conformance/README.md) for runnable tests.

## Security

This is a security-relevant project. Please **do not** open public issues for vulnerabilities. Follow the disclosure process in [SECURITY.md](./SECURITY.md). The [threat model](./docs/threat-model.md) enumerates the in-scope threats and the controls that mitigate each; [RFC 0002 §Security implications](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md) extends the model with v3-specific threats (prompt injection via telemetry, KG retrieval poisoning, LLM weight substitution).

Hardening defaults are documented in [reference-implementation/SECURITY_DEFAULTS.md](./reference-implementation/SECURITY_DEFAULTS.md): TLS is enabled by default with self-signed certs generated by `scripts/setup.sh`; default passwords are absent and the stack refuses to start without operator-supplied secrets; the audit ledger is append-only at the database layer via Postgres triggers; the reference implementation makes no outbound network calls during inference when the default local backend is used.

## Contributing

We welcome contributions. Start with [CONTRIBUTING.md](./CONTRIBUTING.md) and please read the [Code of Conduct](./CODE_OF_CONDUCT.md). For how to get help, see [SUPPORT.md](./SUPPORT.md). The [MAINTAINERS](./MAINTAINERS.md) document lists the teams and their areas of ownership. Architectural changes follow the [RFC process](./docs/governance.md) — RFC 0002 is the current example.

Local setup is the standard Python workflow: clone the repo, create a virtual environment, install `requirements-dev.txt`, run `pytest`. CI runs ruff, mypy, bandit, pip-audit, the Trivy container scan, the SBOM generator, the CodeQL scanner, and the conformance suite on every pull request. See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).

## Licensing summary

| Part | License |
|---|---|
| Specification (`docs/`, framework PDF) | CC BY 4.0 — see [LICENSE-docs.md](./LICENSE-docs.md) |
| Software (Python, Docker, shell, SQL, YAML) | Apache 2.0 — see [LICENSE](./LICENSE) |
| Knowledge Graph libraries | Proprietary — KpiFinity |

CC explicitly recommends against using CC licenses for software, which is why we split. Apache 2.0 includes the explicit patent grant that regulated-industry adopters typically require.

The licenses cover code and text, not names: “SKI Framework” and “SKI Conformant” are trademarks of KpiFinity Inc. — see [TRADEMARKS.md](./TRADEMARKS.md).

## Roadmap

The authoritative, always-current roadmap is [ROADMAP.md](./ROADMAP.md). Summary:

**v3.0 (shipped).** Specification at v3.0. The neuro-symbolic pivot per [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md): KG-grounded sovereign LLM as primary reasoner, Symbolic Verifier on the formalizable subset, typed-graph Knowledge Graph with jurisdictional scope + effective-date intervals, strict Risk-Tier Governor, signed LLM transcripts, agreement monitor, conformance reorganized around Provenance / Durability / Sovereignty.

**v3.1 (planned).** Sovereignty conformance harness (no-outbound-calls test, air-gapped container, tamper-resistance, single-worker enforcement, jurisdiction-scope inspection), full-fidelity v3 KG extraction (LLM emits typed obligations directly), additional LLM backends (vLLM, llama.cpp, Bedrock, Vertex).

**v3.2 (planned).** Per-shard horizontal scaling, shard router, ledger partitioning, Kubernetes operator + CRDs (`SkiModelDeployment`), Sigstore / cosign image signing with SLSA Level 3 provenance.

**v1.0 (long-term).** Long-term-supported reference implementation, conformance-mark issuance via KpiFinity.

### Legacy

**v0.1.0-alpha → v0.2.1 (superseded by v3.0).** The v2 line shipped the Track 1 (Symbolic Evaluator) / Track 2 (bounded LLM) split. v3 dissolves the split. v2 paths have been removed from `main` as of the v3.0 cutover; the last released v2 artefact is `v0.2.1`. New deployments should target v3.0.

## Citation

A machine-readable citation file is provided in [CITATION.cff](./CITATION.cff). Human-readable form:

> KpiFinity Inc. (2026). *SKI Framework: Sovereign Knowledge Intelligence for Regulated Industries — neuro-symbolic compliance with verifiable provenance.* v3.0.0 (specification v3.0). Retrieved from <https://skiframework.org>. Specification under CC BY 4.0; reference implementation under Apache 2.0.

## About

KpiFinity Inc. is a Calgary-based technology and consulting firm specialising in AI governance and compliance automation for regulated industries. → [kpifinity.com](https://kpifinity.com)

**Questions?** Start with the [specification](https://skiframework.org) or email <hello@kpifinity.com>.
