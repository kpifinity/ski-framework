# Getting started with the SKI Framework

> **Status:** v3.0 — first production-target release. Specification at
> v3.0; reference implementation, tools, and conformance suite are
> aligned.

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
  into a signed v3 Knowledge Graph through a probabilistic,
  human-validated process (`kg-extractor` produces the v3 KG; the
  `kg-validator` runs the spec §3.6 validation passes).
- **Phase 2 — runtime evaluation.** Telemetry is evaluated by a
  KG-grounded local LLM inside the sovereign boundary; the Symbolic
  Verifier mechanically cross-checks every formalizable assertion;
  every verdict carries signed provenance.

## Core concepts in five minutes

1. **Knowledge Graph** — typed graph of obligations, subjects,
   definitions, exemptions, precedents, jurisdictions, citations
   (spec §3). Signed Ed25519. The runtime refuses to load an unsigned
   KG.
2. **Risk-Tier Governor** — the strict KG-side source of risk tier per
   obligation (spec §5.4). The caller cannot self-declare a tier; the
   strictest tier across applicable obligations wins.
3. **SKI Model evaluator** — the KG-grounded local LLM that produces
   the verdict, reasoning, KG citations, and formalizable assertions.
   Temperature 0, fixed seed, structured generation against the
   scoped KG snapshot.
4. **Symbolic Verifier** — mechanically cross-checks each formalizable
   assertion against the same telemetry. Emits one of four statuses:
   AGREED, LLM_CONTRADICTION, NEURO_SYMBOLIC_DIVERGENCE,
   UNVERIFIABLE.
5. **Verdicts** — exactly five: `CLEAR`, `FLAG`, `NULL_UNMAPPED`,
   `NULL_STALE`, `DISCRETIONARY`. No scores, no confidence intervals.
6. **Audit ledger** — append-only, hash-chained, append-only at the
   database layer.

## Pick a role

### "I want to read the spec."
Start at [skiframework.org](https://skiframework.org) or
[`docs/architecture.md`](./architecture.md). The spec is licensed
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
[`docs/conformance.md`](./conformance.md) for the methodology and the
Provenance / Durability / Sovereignty progression.

### "I'm reviewing this for purchase / regulatory approval."
The fastest path to a credible assessment:

1. Skim the [README's status section](../README.md).
2. Read [`docs/architecture.md`](./architecture.md) for the spec
   compliance picture.
3. Read [`reference-implementation/SECURITY_DEFAULTS.md`](../reference-implementation/SECURITY_DEFAULTS.md).
4. Run the conformance suite against the reference implementation:
   `pytest conformance -q -m "provenance or durability"`.
5. Verify the audit ledger end-to-end: `python scripts/verify-ledger.py --strict`.

## What's in the repository

```
ski-framework/
├── README.md
├── docs/
│   ├── getting-started.md          ← you are here
│   ├── architecture.md             Specification: architecture
│   ├── knowledge-graph.md          Specification: KG format
│   └── conformance.md              Specification: conformance methodology
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

- Read the architecture: [`architecture.md`](./architecture.md)
- Run the reference implementation: [`../reference-implementation/QUICKSTART.md`](../reference-implementation/QUICKSTART.md)
- Run the conformance suite: [`../conformance/README.md`](../conformance/README.md)
- Talk to KpiFinity: [kpifinity.com](https://kpifinity.com)
