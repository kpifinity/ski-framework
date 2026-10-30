# Published contracts

SKI is a *language-neutral* framework: the specification and the reference
implementation are two things, and a second, independent implementation — in
any language — must be able to exist and be certified against the same
contract. This page describes the machine-readable contracts that make that
possible, and the test vectors any implementation must reproduce to claim
conformance.

All of it is **additive and non-breaking**. In framework v3.2.0 the runtime
still computes its envelope and audit-ledger hashes with the legacy ad-hoc
serializers; switching those call sites to the canonicalizer below changes
stored hashes and is a separate, coordinated change (ledger v4). Nothing here
alters an existing hash.

These contracts implement specification v3.0
[§7.3](specification-v3.md#73-prompt-template-and-kg-canonical-hashing). Where
the Pydantic models (what the runtime actually emits) and the prose spec
diverge, the models are authoritative here and the divergences are tracked for
normative reconciliation in **RFC 0004** (spec 3.1 alignment); see the
[RFC index](RFCs/index.md).

## The canonicalizer (RFC 8785 + spec §7.3)

`ski_schemas.canonical` is the one canonical-JSON implementation the contracts
are defined against. It implements the **JSON Canonicalization Scheme
([RFC 8785](https://www.rfc-editor.org/rfc/rfc8785))** with the Unicode **NFC**
rule of spec §7.3:

- **Object member names** are sorted by their **UTF-16 code units** (RFC 8785
  §3.2.3) — not by Unicode code point and not by locale. The difference is
  observable: `U+10000` sorts *before* `U+FFFF` because its first UTF-16 code
  unit is the high surrogate `0xD800`.
- **Numbers** are serialized by the ECMA-262 `Number::toString` algorithm:
  integers carry no `.0`; the shortest decimal string that round-trips is used;
  plain notation is used for decimal exponents in `[-6, 21)` and exponential
  notation otherwise; `-0` prints as `0`. `NaN` and the infinities are
  rejected, and an integer no IEEE-754 double can represent exactly is rejected
  rather than silently rounded.
- **Strings** are emitted as UTF-8. Only `"`, `\` and the C0 controls
  (`U+0000`–`U+001F`) are escaped — the five short escapes where they exist and
  lowercase `\u00xx` otherwise. `/`, `U+007F` and `U+2028` are written
  literally.
- **NFC** is applied to string *values* (spec §7.3 rule 3, "string values are
  UTF-8 NFC-normalized"). Member *names* are left as written; normalizing them
  could merge two distinct keys, and §7.3 does not require it. This
  value-only reading is flagged for RFC 0004.

The public surface:

```python
from ski_schemas.canonical import canonicalize, sha256_canonical

canonicalize(obj)        # -> bytes   (canonical UTF-8 serialization)
sha256_canonical(obj)    # -> "sha256:<hex>"  (SHA-256 of those bytes)
```

Duplicate member names and byte-order marks are rejected when parsing JSON
text (`parse_json`), per I-JSON (RFC 7493).

## JSON Schema (draft 2020-12)

`spec/contracts/schemas/*.schema.json` are generated **from the Pydantic
models** so they cannot drift from what the runtime emits:

| schema | object |
|---|---|
| `measurement_record.schema.json` | the input of `POST /api/evaluate` |
| `v3_verdict_envelope.schema.json` | the verdict envelope (spec §4.2) |
| `model_provenance.schema.json` | inference provenance (spec §4.6) |
| `kg_obligation.schema.json` | the flat-shape KG obligation the runtime loads |

Regenerate with `python spec/contracts/generate_schemas.py`.

## OpenAPI 3.1

`spec/contracts/openapi.yaml` is derived from the live FastAPI app
(`app.openapi()`), pruned to the three public paths — `POST /api/evaluate`,
`GET /api/health`, `POST /api/kg/load` — and the component schemas they
reference. Regenerate with `python spec/contracts/generate_openapi.py`.

## Test vectors and conformance

`spec/test-vectors/` is the language-neutral conformance contract. **Any
implementation claiming conformance MUST reproduce every vector**:

- `canonical/` — input JSON → expected canonical bytes → expected SHA-256
  (including the RFC 8785 §3.2.3 worked example and the UTF-16 surrogate
  key-sort case).
- `envelopes/` — a full signed `V3VerdictEnvelope` that validates against the
  published JSON Schema.
- `verifier/truth_table.json` — the externally observable verdict /
  verifier-status outcomes for the finding-C1 cases (omission, masking,
  non-finite readings, breach-never-CLEAR).

See `spec/test-vectors/README.md` for the full index.

## Drift control

`python spec/contracts/check_drift.py` regenerates the JSON Schemas from the
live models and fails on any difference, re-derives every `canonical/` vector,
and validates every `envelopes/` vector against the committed schema. The CI
`contracts` job runs it on every pull request, alongside an OpenAPI drift
check, so the published contracts can never silently fall out of step with the
code.
