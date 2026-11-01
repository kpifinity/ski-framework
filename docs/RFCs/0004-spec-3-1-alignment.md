# RFC 0004 — Specification 3.1: align the text with the contracts

| | |
|---|---|
| **Status** | Draft (comment period: 14 days from the PR that opens it) |
| **Author(s)** | SKI Framework maintainers |
| **Created** | 2026-11-01 |
| **Last updated** | 2026-11-01 |
| **Supersedes** | — |
| **Superseded by** | — |

## Summary

Specification 3.1 makes the prose say what the published contracts (JSON
Schema, OpenAPI, test vectors) and the reference implementation already do,
so a second implementation can be written from the specification and the
vectors alone. It resolves each divergence the contracts work recorded,
three more found while implementing v3.3.0, and takes the vendor out of the
normative text. It changes no behaviour of a conforming v3.0 implementation
except where v3.0 was ambiguous; each such case is listed below.

## Motivation

The gold-standard criterion for the framework is a second, independent,
conformant implementation. Today an implementer who follows the prose would
diverge from the vectors in at least eight places (below), and §7.3 alone
admits several incompatible canonical forms. The specification also names a
single company as the reference implementation's maintainer and as the
authority for receipt schemes, which a neutral standard cannot do.

## Proposal

Each item names the v3.0 text, the divergence, and the 3.1 text.

### 1. Canonical JSON (§7.3): RFC 8785, exactly

*v3.0:* "keys sorted lexicographically", "minimum number of significant
digits", ECMA-262 for floats. *Divergence:* "lexicographically" is ambiguous
(code points, UTF-8 bytes and UTF-16 units sort `U+10000` and `U+FFFF`
differently), integers and floats are described separately, and nothing says
what happens to NaN, infinities, unsafe integers, duplicate keys or a BOM.
*3.1:* the canonical form **is** RFC 8785 (JCS): member names sorted by UTF-16
code units; numbers by ECMA-262 `Number::toString` (integers are numbers);
NaN, ±Infinity, lone surrogates and in-memory integers no IEEE-754 double
represents exactly MUST be rejected (number literals in JSON text are read as
`JSON.parse` reads them); JSON text with duplicate member names or a BOM MUST be rejected
(I-JSON, RFC 7493). Vectors: `spec/test-vectors/canonical/`.

### 2. NFC scope (§7.3 rule 3)

*Divergence:* "String values are NFC-normalized" left member names open.
*3.1:* NFC applies to string **values** only; member names are used as
written (normalizing them could merge distinct keys). Vector:
`nfc_key_not_normalized.json`.

### 3. Formalizable assertion predicates (§4.4)

*v3.0:* `predicate` is "drawn from the same enumeration as
`Obligation.type`". *Divergence:* the verifier also evaluates `must_equal`,
`must_not_equal` and the stateful `must_not_exceed_in_window` /
`must_average_within`, which carry `window_seconds`; `value` is a scalar, a
`[lo, hi]` range or a set. *3.1:* the assertion predicate set is the §3.3
enumeration plus those four; `value` and `observed` are a scalar, a
two-element range (`must_be_within`, `must_average_within`) or an array
(`*_one_of`); stateful predicates carry `window_seconds` (integer ≥ 1). A
predicate outside the set is a schema violation, recorded in
`verifier_result.divergences`. Schema: `v3_verdict_envelope.schema.json`.

### 4. Provenance fields (§4.6)

*Divergence:* v3.2.0 added optional `model_hash_verified`,
`inference_backend`, `kg_signer_key_id` and `kg_trust`, which the schema
publishes and auditors rely on. *3.1:* listed as OPTIONAL fields with their
meaning; an implementation that emits them MUST give them that meaning.

### 5. `prompt_template_hash` (§4.6, §5.2, §8.1)

*v3.0:* §5.2 says it is "the SHA-256 of the rendered prompt as sent". *Divergence:*
it identifies the **template** (the rendered prompt differs per request and
is already hashed as the transcript's `request_hash`). *3.1:*
`prompt_template_hash` is the SHA-256 of the prompt template; the rendered
prompt's hash is the transcript's `request_hash`; replay (§8.1 step 3)
re-renders the prompt and compares it with the recorded transcript.

### 6. Ledger storage (§7.1, §7.4)

*Divergence:* §7.1 names `llm_transcript` / `verifier_result` columns and §7.4
requires a separate transcript store; the reference ledger stores the
envelope and the signed transcript in the ledger row, covered by the entry
hash since ledger format 4. *3.1:* §7.1 lists the required **content**; the
envelope, the transcript and the verifier result MAY be stored in the ledger
row or in a separate append-only store, and in either case the entry hash
MUST commit to them (formats 4 and 5, already in §7.1).

### 7. One Knowledge Graph shape (§3, §5.1, §11.2)

*Divergence:* the published `kg_obligation.schema.json` described the flat
compatibility shape the runtime loaded; §5.1 routing was not implemented and
did not say what a Rule without `applies_to` means. *3.1 (implemented in
v3.3.0):* the graph is the one shape; a Rule with no `applies_to` applies to
every subject; the compatibility mode is opt-in and runs as the converted
graph; `kg_version_hash` is defined once over `{metadata, nodes, edges}`.

### 8. Every Rule has an obligation (§3.3)

*3.1:* stated explicitly as a load-time requirement (a Rule with no
`consists_of` Obligation MUST be refused), which v3.3.0 enforces.

### 9. Vendor-neutral normative text

*v3.0:* the editor is a company; "the reference implementation" is defined
as one company's repository; §7.5 accepts receipt schemes approved by
"KpiFinity's conformance authority"; §2.1.2 names KpiFinity. *3.1:* the
editor is "the SKI Framework maintainers"; "the reference implementation"
is defined by its repository without naming an owner; §7.5 accepts any
receipt scheme whose verification procedure is published and that satisfies
the stated property; §2.1.2 says "any vendor".

## Alternatives considered

- **Keep v3.0 and document the divergences in `contracts.md`.** Rejected: a
  second implementation must be able to follow the normative text, and two
  sources of truth is what produced the divergences.
- **Change the reference implementation to match the v3.0 prose.** Rejected
  for items 1-3 and 5-6: the prose was ambiguous or less safe (e.g. a hash of
  the rendered prompt as `prompt_template_hash` would not identify the
  template), and the implementation's behaviour is pinned by published vectors.
- **Defer to v4.0.** Rejected: none of the items breaks a v3.0 implementation
  that followed the vectors, so a minor version is the honest label.

## Compatibility

Specification 3.1 is a minor revision. A v3.0 implementation that already
reproduces the published vectors conforms to 3.1 unchanged, except that it
must refuse a Rule with no obligation (item 8) and route by subject (item 7).

## Unresolved questions

- Whether the four extended assertion predicates (item 3) should also become
  `Obligation.obligation_type` values in §3.3 (today a KG expresses them with
  `must_be_within` / `must_not_exceed` and `window_seconds`).
- **Verifier status after `satisfied` correction (§4.5).** The reference
  verifier first corrects each `satisfied` flag it can compute from
  `observed`, so a FLAG whose assertions all hold is reported as
  `NEURO_SYMBOLIC_DIVERGENCE`; the §4.5 wording makes it
  `LLM_CONTRADICTION`. The verdict is the same at every tier that downgrades
  either. Proposal: define the status on the corrected assertions and say so.
- **Subject absent from the KG (§4.1, §5.1).** §4.1 gives `NULL_UNMAPPED`
  ("the telemetry subject is not present in the KG"); the reference treats
  any subject with an empty slice as tier-1 and returns `DISCRETIONARY`.
  Options: keep §4.1 and split the two cases (absent → `NULL_UNMAPPED`,
  present but unrouted → `DISCRETIONARY`), or make both `DISCRETIONARY`.
- **Risk tiers at `high` and `low` (§5.4).** At `high`, §5.4 holds an AGREED
  verdict until a human attestation arrives; the reference honours it
  without one and requires attestation only when the verifier disagrees. At
  `low`, §5.4 honours the model's verdict whatever the verifier says; the
  reference downgrades `LLM_CONTRADICTION` to `DISCRETIONARY`. The `low`
  behaviour is safer and should become the text. The `high` behaviour is a
  product decision: implement the hold (an attestation API), or relax the
  text to the reference's rule.

These three were found by the black-box conformance suite
(`conformance/blackbox/`), which accepts either behaviour until this RFC
decides.
