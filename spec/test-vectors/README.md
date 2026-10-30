# SKI test vectors

These vectors are the **language-neutral conformance contract** for the SKI
Framework. They let a second, independent implementation — in any language —
prove it matches the reference runtime without reading its source. Any
implementation claiming conformance **MUST** reproduce every vector here.

The vectors pin the *wire* behaviour (bytes on the wire, verdicts out of the
API), not any implementation's internals. They are additive: in framework
v3.2.0 the reference runtime still computes its envelope and ledger hashes
with the legacy ad-hoc serializers; rewiring those call sites to the
canonicalizer is a separate, coordinated change (tracked for ledger v4 and
RFC 0004). These vectors define what that canonicalizer and the API already
produce.

## Layout

### `canonical/` — canonicalization known-answer tests

Each file pins one `input` JSON value to:

- `canonical` — the expected canonical UTF-8 serialization, and
- `sha256` — `"sha256:" + hex(sha256(canonical bytes))`.

The scheme is the SKI profile of **RFC 8785 (JCS)** plus the Unicode **NFC**
rule of spec v3.0 §7.3 (NFC applied to string *values*; see
`nfc_key_not_normalized.json` for the member-name carve-out). It is
implemented by `ski_schemas.canonical.canonicalize` /
`sha256_canonical`. A conforming canonicalizer must, for each file,
produce `canonical` byte-for-byte from `input` and the same `sha256`.

Headline cases and what they pin:

| file | what it proves |
|---|---|
| `numbers_rfc8785.json` | ECMA-262 `Number::toString` number form (RFC 8785 Appendix B values) |
| `rfc8785_section_3_2_3.json` | the full worked example from RFC 8785 §3.2.3 (`canonical` is the RFC's published output) |
| `key_sort_ascii.json` | member names sorted by UTF-16 code unit |
| `key_sort_utf16_surrogate.json` | the surrogate subtlety: U+10000 sorts **before** U+FFFF |
| `nfc_value_normalized.json` | a decomposed string value is NFC-composed |
| `nfc_key_not_normalized.json` | a member *name* is left as-is (§7.3 scopes NFC to values) |
| `control_and_escape.json` | RFC 8785 string escaping (short escapes, lowercase `\u00xx`, literal `/` and U+007F) |

Numbers in `input` are written in a form that round-trips through a standard
JSON parser as IEEE-754 doubles. Rejections (NaN, ±Infinity, lone
surrogates, integers no double can hold exactly) are not representable as
JSON input and so are covered by the canonicalizer's unit tests
(`tools/ski-schemas/tests/test_canonical.py`), not by these files.

### `envelopes/` — signed verdict envelope examples

A full `V3VerdictEnvelope` (spec §4.2) with every provenance field
populated, including the optional framework v3.2.0 trust/backend fields. The
drift check validates every file here against the committed JSON Schema
`spec/contracts/schemas/v3_verdict_envelope.schema.json`, so these prove the
published schema accepts a real envelope.

### `verifier/` — verifier/evaluator truth table

`truth_table.json` states, for each input (scoped KG obligations +
measurement + the language model's scripted output), the externally
observable outcome a conforming implementation must produce: an HTTP status,
or a verdict plus `verifier_result.status` and required divergence
substrings. It encodes finding **C1** (fail-open verifier) and covers:
omission (`OMITTED_OBLIGATION` / contradiction, never CLEAR), a masking junk
predicate (`SCHEMA_VIOLATION` → DISCRETIONARY), a non-finite reading
(rejected with HTTP 422), and a breach never resolving to CLEAR at any risk
tier — plus the controls that an honest CLEAR survives. The reference
runtime enforces every case in
`conformance/adversarial/test_fail_closed_verifier.py`.

## Regenerating

- `python spec/contracts/generate_schemas.py` — JSON Schemas from the models.
- `python spec/contracts/generate_openapi.py` — OpenAPI from the FastAPI app.
- `python spec/test-vectors/canonical/generate.py` — canonical vectors.
- `python spec/test-vectors/envelopes/generate.py` — envelope examples.
- `python spec/contracts/check_drift.py` — fails if any committed schema or
  vector no longer matches the code (wired into CI).
