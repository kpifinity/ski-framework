# SKI Framework

> **Sovereign Knowledge Intelligence** — an open neuro-symbolic architecture for AI compliance in regulated industries.

> **STATUS.** Beta. SKI implements the **v3.0 specification** — a Knowledge-Graph-grounded sovereign LLM as the primary reasoner, with the Symbolic Evaluator as an independent verifier and a verifiable-provenance audit trail (the neuro-symbolic architecture from [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md)). Current release: **v3.1.0-beta.1**. See [CHANGELOG.md](./CHANGELOG.md) for release history.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/kpifinity/ski-framework?quickstart=1)

[![License: Apache-2.0 (code)](https://img.shields.io/badge/License%20(code)-Apache%202.0-blue.svg)](./LICENSE)
[![License: CC BY 4.0 (spec)](https://img.shields.io/badge/License%20(spec)-CC%20BY%204.0-lightgrey.svg)](./LICENSE-docs.md)
[![Spec](https://img.shields.io/badge/Spec-v3.0-blue.svg)](https://skiframework.org)
[![Release](https://img.shields.io/badge/Release-v3.1.0--beta.1-blue.svg)](https://github.com/kpifinity/ski-framework/releases/tag/v3.1.0-beta.1)
[![Docs](https://img.shields.io/badge/Docs-MkDocs%20Material-blue.svg)](https://kpifinity.github.io/ski-framework/)

## Try it in your browser -- no install needed

Click the button above to open a pre-configured GitHub Codespace, then run:

```
python quickstart.py
```

The guided walkthrough takes about two minutes. It runs four real compliance evaluations against an energy-sector Knowledge Graph -- a clean reading, a breach, a boundary case, and a measurement covered by a future rule that isn't in force yet. No cloud API keys. No local setup. Everything runs inside the Codespace.

To see all 50 benchmark cases and the full accuracy report:

```
python quickstart.py --all
```

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
- `scripts/` — Setup, deploy, and cleanup helpers.

## Quick start

The instructions below run the v3 reference implementation: the Knowledge Graph is queried for the slice relevant to each rule, the local LLM evaluates against it under structured-generation constraints, and the Symbolic Verifier independently checks the formalizable subset.

The reference implementation runs entirely on-premise. It does not require — and by default does not have — any cloud API key. Inference is performed by a local LLM runtime (Ollama). An optional "demo" backend can call the Anthropic API; it is non-conformant and clearly labelled as such.

To run the stack: clone the repo, run `./scripts/setup.sh` to generate TLS certificates and write a `.env` file, start the Ollama container, pull the default open-weights model (`qwen2.5:7b-instruct`), bring up the rest of the stack with `docker compose`, send a sample telemetry record from `examples/`, and verify the audit ledger. The full walkthrough is in [reference-implementation/QUICKSTART.md](./reference-implementation/QUICKSTART.md). Production-track guidance is in [reference-implementation/docs/DEPLOYMENT.md](./reference-implementation/docs/DEPLOYMENT.md).

## Architecture

**v2.1 (legacy).** Two phases. Phase 1 is compilation: regulatory documents are processed by `kg-extractor` (LLM-assisted) and then by `kg-validator` (human-reviewed) to produce a signed Knowledge Graph and a Tag Registry. Phase 2 is runtime: telemetry arrives at the SKI Model service, the Tag Registry dispatches a rule to either the Symbolic Evaluator (Track 1, deterministic) or the bounded local LLM (Track 2), and the verdict is hash-chained into the append-only audit ledger. The default for any rule is Track 1; Track 2 is the escape hatch for rules that resist formalization. This is described in full in [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

**v3.0 (current).** The Track 1 / Track 2 split dissolves. Every verdict takes the same path: telemetry arrives, the KG is queried for the typed semantic slice relevant to the rule, the local LLM evaluates against that slice with structured-generation constraints, the Symbolic Verifier independently checks the formalizable subset, and the ledger records the full provenance — signed LLM transcript, model weight hash, KG version hash, KG citations, verifier result. The audit story moves from "deterministic replay of a rule engine" to "verifiable provenance of a neuro-symbolic decision" — the stronger defensibility story for 2026. The full proposal, alternatives considered, threat-model deltas, and rollout plan are in [RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md).

## Verdicts

SKI produces exactly five verdict types. No scores, no confidence intervals, no probabilistic ranges. The taxonomy is preserved across v2.1 and v3.

| Verdict | Meaning | Action |
|---|---|---|
| **CLEAR** | Applicable rules evaluated; no compliance issue detected | Normal operation; logged to audit ledger |
| **FLAG** | A compliance rule has been breached | Escalate to designated human reviewer; create incident |
| **NULL_UNMAPPED** | Telemetry subject is not present in the Knowledge Graph | Document in Coverage Register; expand KG |
| **NULL_STALE** | Rule matched but its time-window predicate has expired | Investigate upstream freshness; expand KG buffer |
| **DISCRETIONARY** | Rule applies but requires qualified human judgment | Route to compliance expert for decision |

In v3 the verdict envelope is extended with the LLM transcript reference, KG citations, formalizable assertions, the symbolic verifier's per-assertion result, and model provenance metadata. The five-value taxonomy itself is unchanged.

## Components

The specification under `docs/` defines the architecture, the Knowledge Graph schema, the Tag Registry requirements (v2.1) or risk-tier governor requirements (v3), the SKI Model determinism enforcement controls, the data integration and sidecar patterns, and the audit ledger canonical serialization. It is CC BY 4.0.

The reference implementation under `reference-implementation/` includes the Symbolic Evaluator (Track 1 in v2.1; Symbolic Verifier in v3), the SKI Model wrapper with Ollama backend, the Tag Registry, the signed-KG loader (Ed25519), the append-only audit ledger with database-level triggers, the determinism canary (repurposed in v3 to monitor neuro-symbolic agreement), and a Postgres-backed stateful evaluation buffer with `NULL_STALE` routing and deterministic replay. Kubernetes manifests and horizontal scaling are planned for a later v3.x release.

The four CLI tools under `tools/` cover the framework's lifecycle: `kg-extractor` reads regulatory documents and emits structured rule candidates; `kg-validator` runs the human-in-the-loop validation; `ski-model-deploy` refuses to load unsigned KGs; `audit-ledger` performs real hash recomputation and uses real `pg_dump` for backups.

The conformance test suite under `conformance/` defines Level 1 / 2 / 3 conformance as runnable black-box tests. Each test cites the specification section it validates. v3 reorganizes the levels around verifiable provenance (see RFC 0002 §Conformance implications).

The Knowledge Graph libraries for specific industries (energy, finance, manufacturing, defense) are proprietary and licensed separately by [KpiFinity](https://kpifinity.com).

## Conformance levels

| Level | v2.1 focus | v3 focus (per RFC 0002) |
|---|---|---|
| **Level 1 Foundational** | Determinism, signature verification, ledger integrity | Adds: KG typed-obligations present, verdict envelope carries provenance, sovereignty enforced |
| **Level 2 Managed** | Multi-domain, Tag Registry coverage, NULL_UNMAPPED handling | Adds: neuro-symbolic agreement rate threshold, jurisdictional resolution, v3 replay verification |
| **Level 3 Assured** | Determinism canary, append-only enforcement, third-party verifiability | Adds: SLSA attestation endpoint, CommitLLM-style verifiable inference receipts, human attestation tokens for high-tier rules |

See [docs/CONFORMANCE.md](./docs/CONFORMANCE.md) for the v2.1 methodology and [conformance/README.md](./conformance/README.md) for runnable tests. The v3 reorganization lands in PR 14 of the v3 stream.

## Security

This is a security-relevant project. Please **do not** open public issues for vulnerabilities. Follow the disclosure process in [SECURITY.md](./SECURITY.md). The [threat model](./docs/threat-model.md) enumerates the in-scope threats and the controls that mitigate each; [RFC 0002 §Security implications](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md) extends the model with v3-specific threats (prompt injection via telemetry, KG retrieval poisoning, LLM weight substitution).

Hardening defaults are documented in [reference-implementation/SECURITY_DEFAULTS.md](./reference-implementation/SECURITY_DEFAULTS.md): TLS is enabled by default with self-signed certs generated by `scripts/setup.sh`; default passwords are absent and the stack refuses to start without operator-supplied secrets; the audit ledger is append-only at the database layer via Postgres triggers; the reference implementation makes no outbound network calls during inference when the default local backend is used.

## Contributing

We welcome contributions. Start with [CONTRIBUTING.md](./CONTRIBUTING.md) and please read the [Code of Conduct](./CODE_OF_CONDUCT.md). The [MAINTAINERS](./MAINTAINERS.md) document lists the teams and their areas of ownership. Architectural changes follow the [RFC process](./docs/governance.md) — RFC 0002 is the current example.

Local setup is the standard Python workflow: clone the repo, create a virtual environment, install `requirements-dev.txt`, run `pytest`. CI runs ruff, mypy, bandit, pip-audit, the Trivy container scan, the SBOM generator, the CodeQL scanner, and the conformance suite on every pull request. See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).

## Licensing summary

| Part | License |
|---|---|
| Specification (`docs/`, framework PDF) | CC BY 4.0 — see [LICENSE-docs.md](./LICENSE-docs.md) |
| Software (Python, Docker, shell, SQL, YAML) | Apache 2.0 — see [LICENSE](./LICENSE) |
| Knowledge Graph libraries | Proprietary — KpiFinity |

CC explicitly recommends against using CC licenses for software, which is why we split. Apache 2.0 includes the explicit patent grant that regulated-industry adopters typically require.

## Roadmap

The reference implementation's major version tracks the specification's: the **0.x** releases implemented spec **v2.x**, and from the v3 neuro-symbolic pivot ([RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md)) the implementation realigned onto **3.x** to match spec **v3.0**.

**Released**

- **v0.1.0-alpha** (spec v2.0) — initial reference implementation: Symbolic Evaluator, SKI Model wrapper (Ollama), Tag Registry, signed-KG loader, append-only ledger, determinism canary, conformance Level 1, CI/CD with security scanning.
- **v0.2.0** (spec v2.1) — stateful evaluation: Postgres-backed telemetry buffer, stateful predicate operators (`window_count`, `window_sum`, `window_avg`, `since_last`, `debounce`), `NULL_STALE` end-to-end, deterministic replay, conformance Level 2, Alembic schema migrations.
- **v0.2.1** — patch: Symbolic Evaluator exports `Verdict`; kg-validator detects contradictory limits.
- **v3.0.0 – v3.0.3** (spec v3.0) — the neuro-symbolic pivot ([RFC 0002](./docs/RFCs/0002-v3-neuro-symbolic-pivot.md)): KG-grounded sovereign LLM as primary reasoner, Symbolic Evaluator repositioned as an independent verifier, the Knowledge Graph elevated from routing table to typed semantic substrate, and a verifiable-provenance audit trail (signed LLM transcript, model-weight and KG hashes, KG citations, verifier result).
- **v3.1.0-beta.1** (current) — wire-contract package (`ski-schemas`), typed Python client (`ski-sdk`), production vLLM backend, Helm chart, `/metrics` contract, SKI Evals verdict-accuracy suite, Level 3 conformance rigs (DB-backed and air-gapped), performance benchmarks, and signed releases (Sigstore/cosign with SLSA Level 3 provenance).

**Planned**

- **v3.1.0 (GA)** — promote the beta to the first general-availability v3 release.
- **Later v3.x** — horizontal scaling (shard router, ledger partitioning), a Kubernetes operator + CRDs (`SkiModelDeployment`), and additional LLM backends behind the uniform interface (llama.cpp, Bedrock, Vertex).
- **Conformance-mark program** — a long-term-supported reference implementation and conformance-mark issuance via KpiFinity.

## Citation

A machine-readable citation file is provided in [CITATION.cff](./CITATION.cff). Human-readable form:

> KpiFinity Inc. (2026). *SKI Framework: Sovereign Knowledge Intelligence for Regulated Industries — neuro-symbolic compliance with verifiable provenance.* v3.1.0-beta.1 (specification v3.0). Retrieved from <https://skiframework.org>. Specification under CC BY 4.0; reference implementation under Apache 2.0.

## About

KpiFinity Inc. is a Calgary-based technology and consulting firm specialising in AI governance and compliance automation for regulated industries. → [kpifinity.com](https://kpifinity.com)

**Questions?** Start with the [specification](https://skiframework.org) or email <hello@kpifinity.com>.
