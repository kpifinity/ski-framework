# SKI Framework

> **Sovereign Knowledge Intelligence** — An open architecture for deterministic AI compliance monitoring in regulated industries.

> **⚠ STATUS: EARLY ALPHA (v0.1.0-alpha).** The specification is stable at v2.1. The reference implementation and tools in this repository are *proof-of-scaffold* quality and are **not production ready**. Treat this repo as an executable companion to the specification, not a turnkey product. See [CHANGELOG.md](./CHANGELOG.md) for the current scope.

[![License: Apache-2.0 (code)](https://img.shields.io/badge/License%20(code)-Apache%202.0-blue.svg)](./LICENSE)
[![License: CC BY 4.0 (spec)](https://img.shields.io/badge/License%20(spec)-CC%20BY%204.0-lightgrey.svg)](./LICENSE-docs.md)
[![Specification](https://img.shields.io/badge/Spec-v2.1-blue.svg)](https://skiframework.org)
[![Status](https://img.shields.io/badge/Status-alpha-orange.svg)](./CHANGELOG.md)

## What is SKI?

SKI is an open-source framework that enables **real-time, deterministic, auditable AI compliance monitoring** in environments where regulatory requirements, operational risk, and audit defensibility are non-negotiable.

Unlike general-purpose AI systems, SKI is purpose-built to solve a specific problem: regulated industries (energy, finance, manufacturing, defense) cannot adopt AI in core operational systems because existing solutions don't satisfy four non-negotiable requirements:

1. **Determinism** — Same input always produces the same verdict, every time.
2. **Sovereignty** — Operational data never leaves the organization's infrastructure.
3. **Auditability** — Every verdict traces directly to a specific regulation.
4. **Human Primacy** — AI supports human judgment, never replaces it.

SKI satisfies all four through a two-phase architecture: offline Knowledge Graph compilation (probabilistic) plus runtime evaluation (deterministic, sovereign, and air-gap capable). The runtime is a hybrid of a deterministic **Symbolic Evaluator** (Track 1) and a bounded local **SKI Model** (Track 2) gated by a governed **Tag Registry**.

---

## What's in this repository

This is the **open** half of the SKI ecosystem:

```
ski-framework/
├── docs/                          Specification documents (CC BY 4.0)
├── reference-implementation/      Reference Phase 2 runtime (Apache 2.0)
│   ├── src/
│   │   ├── ski_model/             SKI Model service (Track 2 wrapper)
│   │   ├── symbolic_evaluator/    Symbolic Evaluator (Track 1)
│   │   ├── tag_registry/          Tag Registry (B4.3)
│   │   ├── ledger/                Append-only audit ledger schema
│   │   └── sidecar/               Read-only telemetry intake
│   ├── docker-compose.yml         Ollama + Postgres + Prometheus + Grafana
│   └── ...
├── tools/                         CLI tools (Apache 2.0)
│   ├── kg-extractor/              Phase 1: extract rules from regulations
│   ├── kg-validator/              Phase 1: human-expert validation
│   ├── ski-model-deploy/          Phase 2: deploy and verify a Knowledge Graph
│   └── audit-ledger/              Verify, export, back up the ledger
├── examples/                      DEMO-ONLY illustrative KGs and telemetry
├── conformance/                   SKI conformance test suite (Apache 2.0)
└── scripts/                       Setup, deploy, cleanup helpers
```

The **commercial** half (Knowledge Graph libraries for energy, finance, manufacturing, defense; certified MCP connectors; managed implementation services) lives behind [KpiFinity](https://kpifinity.com) and is not present in this repository.

---

## Quick start

> The reference implementation runs entirely **on-premise**. It does not require — and by default does not have — any cloud API key. Inference is performed by a local LLM runtime (Ollama). An optional "demo" backend can call the Anthropic API, but it is **non-conformant** and clearly labelled as such.

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework

# 1. Generate strong secrets and TLS certs, then write .env.
./scripts/setup.sh

# 2. Pull the small open-weights model used by the reference impl.
docker compose -f reference-implementation/docker-compose.yml up -d ollama
docker exec ski-ollama ollama pull qwen2.5:7b-instruct

# 3. Start the full stack.
docker compose -f reference-implementation/docker-compose.yml up -d

# 4. Send a sample telemetry record (uses the demo KG in examples/).
python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl

# 5. Verify the audit ledger.
python scripts/verify-ledger.py
```

See [reference-implementation/QUICKSTART.md](./reference-implementation/QUICKSTART.md) for the full walkthrough and [reference-implementation/docs/DEPLOYMENT.md](./reference-implementation/docs/DEPLOYMENT.md) for production-track guidance.

---

## Architecture at a glance

```
┌──── PHASE 1: COMPILATION (outside sovereign boundary) ────┐
│  Regulatory docs → kg-extractor → kg-validator (human)    │
│  → signed Knowledge Graph + Tag Registry                   │
└────────────────────────────────────────────────────────────┘
                            │
                  one-way boundary crossing
                            │
┌──── PHASE 2: RUNTIME (inside sovereign boundary) ─────────┐
│  Telemetry → Sidecar → SKI Model service                   │
│      │                                                      │
│      ├── Tag Registry resolves subject → rule               │
│      ├── Track 1 → Symbolic Evaluator (deterministic)       │
│      └── Track 2 → bounded local LLM (temperature 0, seed)  │
│                                                              │
│  Verdict ∈ { CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE,         │
│              DISCRETIONARY }                                 │
│      │                                                      │
│      └── append-only audit ledger (hash chained)            │
└────────────────────────────────────────────────────────────┘
```

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the full picture.

---

## Verdicts (v2.1)

SKI produces exactly five verdict types. No scores, no confidence intervals, no probabilistic ranges (B3.1).

| Verdict | Meaning | Action |
|---------|---------|--------|
| **CLEAR** | Applicable rules evaluated; no compliance issue detected | Normal operation; logged to audit ledger |
| **FLAG** | A compliance rule has been breached | Escalate to designated human reviewer; create incident |
| **NULL_UNMAPPED** | Telemetry subject is not present in the Tag Registry | Document in Coverage Register; expand KG |
| **NULL_STALE** | Rule matched but its time-window predicate has expired | Investigate upstream freshness; expand KG buffer |
| **DISCRETIONARY** | Rule applies but requires qualified human judgment | Route to compliance expert for decision |

---

## Components

### Specification (CC BY 4.0)
- Two-phase architecture, three axioms, three pillars
- Knowledge Graph schema and Tag Registry requirements
- SKI Model selection, configuration, determinism enforcement controls
- Data integration and sidecar patterns
- Audit ledger specification with canonical serialization
- Governance, conformance levels, and audit requirements

### Reference implementation (Apache 2.0, alpha)
- ✅ Symbolic Evaluator (Track 1)
- ✅ SKI Model wrapper (Track 2) with Ollama backend
- ✅ Tag Registry as a first-class governed artifact
- ✅ Knowledge Graph signature verification (Ed25519)
- ✅ Append-only audit ledger with database-level triggers
- ✅ Determinism canary
- ⏳ Stateful evaluation buffer (NULL_STALE path) — partial
- ⏳ Kubernetes manifests — planned

### Tools (Apache 2.0, alpha)
- `kg-extractor` — extract rules from regulatory docs (multiple LLM backends)
- `kg-validator` — every rule is human-reviewed; no auto-approval
- `ski-model-deploy` — refuses to load unsigned KGs
- `audit-ledger` — real hash recomputation; real `pg_dump` backup

### Conformance test suite (Apache 2.0)
- Black-box tests for Level 1 / Level 2 / Level 3 conformance
- Each test cites the spec section it validates
- Runnable against any implementation

### Knowledge Graph libraries (proprietary — KpiFinity)
- Energy, Finance, Manufacturing, Defense — not in this repo.
- See [KpiFinity](https://kpifinity.com) for licensing and professional services.

---

## Conformance levels

The framework defines three executable conformance levels. The repository's [`conformance/`](./conformance) directory contains the test suite that decides whether an implementation can claim a given level.

| Level | Focus | Test scope |
|---|---|---|
| **Level 1 Foundational** | Determinism, signature verification, ledger integrity | Single-domain happy path |
| **Level 2 Managed** | Multi-domain, Tag Registry coverage, NULL_UNMAPPED handling | Multi-KG + Coverage Register |
| **Level 3 Assured** | Determinism canary, append-only enforcement, third-party verifiability | Tamper-resistance under adversarial inputs |

See [docs/CONFORMANCE.md](./docs/CONFORMANCE.md) for the methodology and [conformance/README.md](./conformance/README.md) for runnable tests.

---

## Security

This is a security-relevant project. Please **do not** open public issues for vulnerabilities. Follow the disclosure process in [SECURITY.md](./SECURITY.md).

Hardening defaults are documented in [reference-implementation/SECURITY_DEFAULTS.md](./reference-implementation/SECURITY_DEFAULTS.md):
- TLS is enabled by default; self-signed certs are generated by `scripts/setup.sh`.
- Default passwords are absent; the stack refuses to start without operator-supplied secrets.
- The audit ledger is append-only at the database layer (Postgres triggers prevent UPDATE/DELETE).
- The reference implementation makes **no outbound network calls** during inference when the default Ollama backend is used.

---

## Contributing

We welcome contributions. Start with [CONTRIBUTING.md](./CONTRIBUTING.md) and please read the [Code of Conduct](./CODE_OF_CONDUCT.md).

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

CI runs ruff, mypy, bandit, pip-audit, and the conformance suite on every pull request. See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).

---

## Licensing summary

| Part | License |
|---|---|
| Specification (`docs/`, framework PDF) | CC BY 4.0 — see [LICENSE-docs.md](./LICENSE-docs.md) |
| Software (Python, Docker, shell, SQL, YAML) | Apache 2.0 — see [LICENSE](./LICENSE) |
| Knowledge Graph libraries | Proprietary — KpiFinity |

CC explicitly recommends against using CC licenses for software, which is why we split. Apache 2.0 includes the explicit patent grant that regulated-industry adopters typically require.

---

## Roadmap

### v0.1.0-alpha (this release)
- Specification at v2.1 ✅
- Reference implementation: Symbolic Evaluator, SKI Model wrapper (Ollama), Tag Registry, signed-KG loader, append-only ledger ✅
- Determinism canary ✅
- Conformance suite: Level 1 tests ✅
- CI/CD with security scanning ✅

### v0.2.0
- Stateful evaluation buffer with NULL_STALE routing
- Conformance suite: Level 2 tests
- Additional LLM backends (vLLM, llama.cpp) behind the same interface
- Kubernetes manifests

### v0.3.0
- Conformance suite: Level 3 tests, tamper-resistance benchmarks
- MCP connector framework
- Air-gapped deployment playbook

### v1.0
- Long-term-supported reference implementation
- Conformance-mark issuance via KpiFinity

---

## Citation

A machine-readable citation file is provided ([CITATION.cff](./CITATION.cff)). Human-readable form:

> KpiFinity Inc. (2026). *SKI Framework v2.1: Sovereign Knowledge Intelligence for Regulated Industries.* Retrieved from <https://skiframework.org>. Specification under CC BY 4.0; reference implementation under Apache 2.0.

---

## About

KpiFinity Inc. is a Calgary-based technology and consulting firm specialising in AI governance and compliance automation for regulated industries. → [kpifinity.com](https://kpifinity.com)

**Questions?** Start with the [specification](https://skiframework.org) or email <hello@kpifinity.com>.
