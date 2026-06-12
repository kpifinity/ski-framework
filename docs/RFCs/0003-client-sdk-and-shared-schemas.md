# RFC 0003 — `ski-sdk` and `ski-schemas`: a typed client and a single source of truth for wire models

- **Status:** Accepted and fully implemented (PR 2 June 2026; PR 1 `ski-schemas` landed for v3.1)
- **Author:** KpiFinity maintainers
- **Created:** 2026-06
- **Implemented in:** `ski-sdk` v0.1.0 (landed on `main`, June 2026)

> **Note on numbering.** RFC 0002's open-questions list informally
> reserved "RFC 0003" for the LLM backend portfolio (vLLM, llama.cpp).
> That work will be proposed under its own number when it is designed.
> This RFC takes the 0003 slot because it shipped first; the CHANGELOG
> and `ski-sdk` already reference it by this number.

## Summary

Adopters today integrate with the SKI Model over raw HTTP and hand-roll
both the request shape and the verdict-envelope parsing. The envelope is
normative (spec v3.0 §4): getting a field wrong does not produce an
error, it produces an integration that silently mis-reads provenance.
This RFC introduces two packages:

1. **PR 1 — `ski-schemas`** (deferred): extract the Pydantic models for
   the verdict envelope, the signed LLM transcript, and the measurement
   record out of `reference-implementation/src/ski_model` into a small,
   dependency-light package that the server, the SDK, and the
   conformance suite all import. One definition; no drift.
2. **PR 2 — `ski-sdk`** (shipped): a typed Python client — `SKIClient`
   and `AsyncSKIClient` over `/api/*` — returning parsed
   `V3VerdictEnvelope` objects, a typed error hierarchy, and a one-call
   `verify_transcript()` that checks a verdict's Ed25519 provenance
   (signature validity plus recorded-hash agreement with the canonical
   serialization).

## Motivation

- **The envelope is the product.** SKI's defensibility story is that any
  auditor can re-verify a verdict. If every integrator re-implements
  envelope parsing and signature checking, the weakest integration
  defines the credibility of the whole story. `verify_transcript()` makes
  the strong path the easy path.
- **Drift is a silent failure mode.** The server's models and any
  client-side copy can diverge without an error being raised anywhere.
- **Adoption funnel.** `pip install ski-sdk` followed by five lines of
  Python is the front door for evaluators; raw HTTP plus a 500-line spec
  section is not.

## Design

### `ski-sdk` (PR 2 — shipped)

- Sync (`SKIClient`) and async (`AsyncSKIClient`) clients over the
  `/api/*` surface, returning typed envelopes.
- Typed error hierarchy (`SKIError` and subclasses) — no raw `httpx`
  exceptions escape the public API.
- `verify_transcript(transcript, public_key_pem)` returns a
  `VerificationReport`; `report.ok` requires both a valid Ed25519
  signature and recorded hashes matching the canonical pair.
- Dependencies: `httpx`, `pydantic`, `cryptography` only. The SDK must
  not depend on the reference implementation.
- Lives under `tools/ski-sdk`.

### `ski-schemas` (PR 1 — deferred)

**Implemented (v3.1):** `tools/ski-schemas` is the shared package; the
server, the SDK, and the runtime shims all import it, and the runtime
image carries it (repo-root Docker build context). The former
field-parity drift test is now an *identity* test — the models are the
same objects, so drift is structurally impossible rather than merely
detected.

## Versioning

`ski-sdk` is versioned **independently** of the framework (it wraps a
wire contract, not the runtime), starting at 0.1.0. The four CLI tools
continue to share the framework version. A compatibility table is
maintained in the SDK README.

## Security considerations

- Transcript verification is offline: the SDK receives the runtime's
  public key out-of-band (operator-distributed); it never fetches keys
  from the server it is verifying.
- All dependencies are pinned per the repository's reproducibility
  policy.

## Alternatives considered

- **OpenAPI-generated client.** Rejected: generated clients cannot carry
  `verify_transcript()` semantics, and the generated code quality is not
  something we want adopters reading as their first impression.
- **Schemas-first (PR 1 before PR 2).** Rejected for sequencing: the SDK
  delivers adopter value immediately; the extraction is internal
  hygiene. The drift test bounds the risk of doing it second.
