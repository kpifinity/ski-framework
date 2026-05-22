# Getting started with the SKI Framework

> **⚠ STATUS: EARLY ALPHA (v0.1.0-alpha).** The specification is stable
> at v2.1. The reference implementation and tools are alpha.

This guide orients you to the framework and points to the right next
document for each role.

## What is SKI?

SKI is an open architecture for **deterministic, sovereign, auditable AI
compliance monitoring**. It is purpose-built for regulated industries —
energy, finance, manufacturing, defense — that cannot adopt
general-purpose AI in core operational systems because of four
non-negotiable requirements: determinism, sovereignty, auditability,
and human primacy.

The framework defines a **two-phase architecture**:

- **Phase 1 — offline compilation.** Regulatory documents are turned
  into a signed Knowledge Graph through a probabilistic, human-validated
  process.
- **Phase 2 — runtime evaluation.** Telemetry is evaluated against the
  signed Knowledge Graph inside the sovereign boundary, deterministically.

## Core concepts in five minutes

1. **Knowledge Graph** — set of structured compliance rules, signed.
2. **Tag Registry** — compile-time mapping from telemetry subject to
   rule. Runtime tag inference is architecturally prohibited.
3. **Symbolic Evaluator (Track 1)** — deterministic predicate evaluator
   used for the bulk of rules. Outputs `CLEAR` / `FLAG` / `NULL_*`.
4. **SKI Model (Track 2)** — bounded local LLM for the small fraction of
   rules that require natural-language interpretation. Temperature 0,
   seeded, structured output, with a determinism canary.
5. **Verdicts** — exactly five: `CLEAR`, `FLAG`, `NULL_UNMAPPED`,
   `NULL_STALE`, `DISCRETIONARY`. No scores, no confidence intervals.
6. **Audit ledger** — append-only, hash-chained, append-only at the
   database layer.

## Pick a role

### "I want to read the spec."
Start at [skiframework.org](https://skiframework.org) or
[`docs/ARCHITECTURE.md`](./ARCHITECTURE.md). The spec is licensed
CC BY 4.0.

### "I want to run the reference implementation."
Go to [`reference-implementation/QUICKSTART.md`](../reference-implementation/QUICKSTART.md).
You'll be evaluating sample telemetry against a demo KG in about ten
minutes. The implementation is Apache 2.0 and runs entirely on-premise.

### "I want to bring my own regulations into SKI."
1. Extract rules with [`tools/kg-extractor`](../tools/kg-extractor/).
2. Validate them with [`tools/kg-validator`](../tools/kg-validator/).
3. Sign the resulting KG with your production Ed25519 key.
4. Deploy via [`tools/ski-model-deploy`](../tools/ski-model-deploy/).

For commercial-grade, regulator-mapped Knowledge Graph libraries for
energy, finance, manufacturing, and defense, contact
[KpiFinity](https://kpifinity.com).

### "I want to claim SKI conformance for my implementation."
Run the SKI conformance suite under [`conformance/`](../conformance/).
Each test cites the spec section it validates. See
[`docs/CONFORMANCE.md`](./CONFORMANCE.md) for the methodology and the
Level 1 / 2 / 3 progression.

### "I'm reviewing this for purchase / regulatory approval."
The fastest path to a credible assessment:

1. Skim the [README's status section](../README.md).
2. Read [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) for the spec
   compliance picture.
3. Read [`reference-implementation/SECURITY_DEFAULTS.md`](../reference-implementation/SECURITY_DEFAULTS.md).
4. Run the conformance suite against the reference implementation:
   `pytest conformance -q -m level1`.
5. Verify the audit ledger end-to-end: `python scripts/verify-ledger.py --strict`.

## What's in the repository

```
ski-framework/
├── README.md
├── docs/
│   ├── GETTING_STARTED.md          ← you are here
│   ├── ARCHITECTURE.md             Specification: architecture
│   ├── KNOWLEDGE_GRAPH.md          Specification: KG format
│   └── CONFORMANCE.md              Specification: conformance methodology
├── reference-implementation/       Apache 2.0 — runs entirely on-premise
├── tools/                          Apache 2.0
│   ├── kg-extractor/               Phase 1: extract rules
│   ├── kg-validator/               Phase 1: human validation
│   ├── ski-model-deploy/           Phase 2: deploy signed KGs
│   └── audit-ledger/               Verify, export, back up the ledger
├── conformance/                    Apache 2.0 — runnable spec tests
├── examples/                       DEMO ONLY — never production
└── scripts/                        Operational helpers
```

The proprietary Knowledge Graph libraries (Energy, Finance,
Manufacturing, Defense) live in a private KpiFinity repository and are
not present here. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the
open/proprietary boundary.

## Next steps

- Read the architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- Run the reference implementation: [`../reference-implementation/QUICKSTART.md`](../reference-implementation/QUICKSTART.md)
- Run the conformance suite: [`../conformance/README.md`](../conformance/README.md)
- Talk to KpiFinity: [kpifinity.com](https://kpifinity.com)
