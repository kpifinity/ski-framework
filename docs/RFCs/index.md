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
  as the defensibility story. Implemented across PRs 8–14 of the v3
  stream. Landed in **v3.0.0** (2026-06-01).

## Draft

- [RFC 0003 — Python SDK (`ski-sdk`) and shared schemas (`ski-schemas`)](0003-python-sdk.md)
  — A thin, typed Python client with one-call provenance verification, plus a
  shared `ski-schemas` contract package so client and server cannot drift.
  Python-only, thin-client scope for v0.

## Templates

- [Template (RFC 0000)](0000-template.md)
