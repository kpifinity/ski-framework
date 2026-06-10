# RFCs

Architectural changes to the SKI Framework follow an RFC process.

## How to propose one

1. Copy [`0000-template.md`](0000-template.md) to
   `docs/RFCs/NNNN-short-title.md` with the next sequential number.
2. Open a draft pull request titled `[RFC] <Title>`.
3. Solicit feedback for at least 14 days.
4. The Spec Editor closes the RFC as **Accepted** (merged) or
   **Rejected** (closed with rationale).

See [Governance](../governance.md) for the full process.

## Accepted (implemented)

- [RFC 0001 — Stateful evaluation](0001-stateful-evaluation.md)
  — Authoritative-clock semantics, telemetry buffer, deterministic
  replay. Landed in v0.2.0.
- [RFC 0002 — SKI v3.0: Neuro-Symbolic Pivot](0002-v3-neuro-symbolic-pivot.md)
  — Inverts the runtime: KG-grounded sovereign LLM as primary reasoner,
  Symbolic Evaluator repositioned as an independent verifier of the LLM's
  output, Knowledge Graph elevated from routing table to typed semantic
  substrate. Replaces *deterministic replay* with *verifiable provenance*
  as the defensibility story. Implemented in **v3.0.0** (2026-06-01;
  GitHub PRs #56–#75).

- [RFC 0003 — `ski-sdk` and `ski-schemas`](0003-client-sdk-and-shared-schemas.md)
  — A typed Python client (`SKIClient` / `AsyncSKIClient`) with one-call
  Ed25519 provenance verification, plus extraction of the shared wire
  models into a `ski-schemas` package. PR 2 (the SDK) landed June 2026;
  PR 1 (`ski-schemas`) is deferred to v3.1.

## Draft

_(none currently)_

## Templates

- [Template (RFC 0000)](0000-template.md)
