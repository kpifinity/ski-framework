# RFC 0003 — Python SDK (`ski-sdk`) and shared schemas (`ski-schemas`)

| | |
|---|---|
| **Status** | Draft |
| **Author(s)** | KpiFinity Inc. |
| **Created** | 2026-06-05 |
| **Last updated** | 2026-06-05 |
| **Supersedes** | — |
| **Superseded by** | — |

## Summary

This RFC proposes a small, typed **Python SDK** (`ski-sdk`) that lets an
application submit measurements to a SKI Model, receive parsed
`V3VerdictEnvelope` objects, and — in one call — **verify the signed provenance**
of a verdict. It also proposes extracting the wire contract (the envelope,
measurement, and transcript models plus the signing/verification helpers) into a
standalone **`ski-schemas`** package that both the reference implementation and
the SDK import, so client and server cannot drift.

Scope for v0 is deliberately narrow: **Python only, thin client.** No
multi-language clients, no streaming, no new server features.

## Motivation

The framework's entire value proposition is *verifiable, tamper-evident
compliance verdicts*. Today, exercising that value is awkward:

- An adopter POSTs raw JSON to `/api/evaluate` and gets raw JSON back. There is
  no typed client; every integration re-derives the request/response shape.
- Verifying a verdict's Ed25519 transcript signature — the differentiating
  feature — is a multi-step, hand-rolled exercise against internal helpers
  (`signing_message`, `hash_pair`, `verify_signature`) buried in
  `ski_model.v3`. An end-to-end test of v3.0.3 confirmed this is the single
  biggest source of integration friction.
- The contract has already drifted twice in this codebase (version strings, KG
  formats). Any SDK that *re-declares* the envelope/measurement types will drift
  from the server within a release or two.

The project's stated near-term goal is **adoption**. A thin SDK is the
highest-leverage, lowest-risk way to lower integration friction, surface the
core "verify provenance" feature, and generate the usage signal that informs
later (enterprise) bets.

Relevant code paths: `reference-implementation/src/ski_model/server.py`
(`/api/*`), `…/v3/envelope.py` (`V3VerdictEnvelope`), `…/v3/transcript.py`
(`LLMTranscript`, `signing_message`, `hash_pair`), `…/v3/signing.py`
(`verify_signature`). Spec §6 (transcript / audit).

## Proposal

### Package layout

Two new PyPI packages, both pure-Python and independently versioned:

| Package | Depends on | Purpose |
|---|---|---|
| `ski-schemas` | `pydantic`, `cryptography` | The wire contract: Pydantic models for `MeasurementRecord`, `V3VerdictEnvelope` (and its nested `ModelProvenance`, `VerifierResult`, `KGCitation`, `FormalizableAssertion`), `LLMTranscript`; plus canonicalisation + `hash_pair`, `signing_message`, `verify_signature`. No HTTP, no server deps. |
| `ski-sdk` | `ski-schemas`, `httpx` | `SKIClient` / `AsyncSKIClient` over the HTTP API; `verify()` provenance helpers; KG validate/sign helpers. |

The reference implementation depends on `ski-schemas` and **re-exports** the
moved symbols from their current modules, so existing imports
(`from ski_model.v3 import V3VerdictEnvelope`) keep working unchanged. This is
the mechanism that prevents client/server drift: there is exactly one definition
of the contract.

### `ski-schemas` (the contract)

Move — not copy — these from `reference-implementation/src/ski_model/v3` into
`ski_schemas`:

- `envelope.py` → models + the `V3Verdict` / `VerifierStatus` enums.
- `transcript.py` → `LLMTranscript`, `canonical_request`, `canonical_response`,
  `hash_pair`, `signing_message`.
- `signing.py` → `verify_signature` (the auditor-facing verifier). The
  *signing* half (`TranscriptSigner`, private-key provisioning) stays in the
  runtime; the SDK only ever **verifies**.

`MeasurementRecord` (today defined inline in `server.py`) moves here too, so the
request body is a shared type.

### `ski-sdk` — client surface

```python
from ski_sdk import SKIClient, AsyncSKIClient
from ski_schemas import MeasurementRecord, V3VerdictEnvelope

client = SKIClient(
    endpoint="https://ski.internal:8000",
    api_key="…",                  # sent as the x-api-key header
    verify_tls=True,              # default True; path-to-CA also accepted
    timeout=30.0,
    max_retries=2,                # idempotent GETs + 5xx, exponential backoff
)

env: V3VerdictEnvelope = client.evaluate(
    measurement_id="m-001",
    timestamp="2026-06-05T12:00:00Z",
    subject="stack-7",
    measurement={"so2_ppm": 150},
    jurisdiction="us-ca",         # optional
)
print(env.verdict, [c.node_id for c in env.kg_citations])

client.health()                   # -> HealthStatus
client.list_verdicts(limit=100)   # -> paginated verdicts
client.load_kg(signed_kg_dict)    # -> load summary (signature REQUIRED server-side)
```

`AsyncSKIClient` mirrors the surface with `await`. Both are thin wrappers over a
shared `httpx` transport.

**Errors** are a typed hierarchy so callers can branch without string-matching:
`SKIError` → `SKIAuthError` (401), `SKIServiceUnavailable` (503/no-KG),
`SKIValidationError` (4xx body), `SKITransportError` (network/TLS). The client
**never logs the API key**.

### `ski-sdk` — provenance verification (the headline feature)

```python
from ski_sdk import verify_transcript

# public_key_pem fetched once from the runtime (see Open questions) or pinned
ok = verify_transcript(transcript, public_key_pem)        # bool
# or the fuller check: recompute hashes from canonical request/response,
# confirm they match the recorded hashes, then verify the ed25519 signature
report = verify_transcript(transcript, public_key_pem, strict=True)
assert report.signature_valid and report.hashes_match
```

`verify_transcript` recomputes `request_hash`/`response_hash` from the
transcript's canonical request/response, checks them against the recorded
hashes, rebuilds `signing_message(request_hash, response_hash)`, and verifies
the Ed25519 signature against the supplied public key — the exact chain an
auditor needs, as one call. Tampering with the recorded response flips the
result to invalid (already proven in the runtime suite).

### KG helpers

`ski_sdk.kg.validate(kg)` and `ski_sdk.kg.is_signed(kg)` give a client-side
pre-flight before `load_kg`, reusing the `kg-validator` rules (either by
depending on `kg-validator` or by validating against the shared schema). Signing
a KG remains an operator action (`ski-model-deploy` / key custody), out of SDK
scope.

### Versioning & compatibility

- `ski-schemas` is versioned to track the **spec** contract version (v3.0).
- `ski-sdk` is versioned independently with a documented **compatibility
  matrix** (which SDK works against which server API range).
- The SDK README and `__init__` docstring carry an explicit banner: *this wraps
  an early-alpha API; pin your versions.*

## Alternatives considered

1. **Auto-generate a client from the FastAPI OpenAPI schema.** FastAPI can emit
   OpenAPI, and generators exist. Rejected for v0: generated clients are clunky
   to hand-tune, they don't deliver the `verify()` value-add (which is the whole
   point), and you *still* need the `ski-schemas` split to avoid drift. Worth
   revisiting when multi-language clients are on the table (an OpenAPI / JSON
   Schema contract is the natural source of truth there).
2. **No SDK — just document the raw HTTP API.** Rejected: it leaves the
   signature-verification friction (the differentiator) as a DIY exercise, which
   is exactly what's blunting adoption today.
3. **Ship the client inside the reference-implementation repo, no separate
   package.** Rejected: couples the client's release cadence to the server's, and
   a client that imports server internals is the drift problem restated. The
   `ski-schemas` split is the lighter, more correct boundary.

## Backwards compatibility

- **No wire/API change.** The SDK speaks the existing `/api/*` contract.
- The `ski-schemas` extraction is **source-compatible**: the runtime re-exports
  the moved symbols, so `from ski_model.v3 import …` is unchanged. Existing
  unit/conformance tests must pass untouched (the acceptance gate for the
  extraction PR).
- One **additive** server change may be needed: an endpoint to fetch the
  transcript signing public key (see Open questions). If added, it is optional
  and backwards compatible.

## Security implications

Mapped against the [threat model](../threat-model.md):

- **Strengthens** auditability / non-repudiation: `verify_transcript` makes the
  tamper-evidence check trivial and therefore actually used.
- **TLS on by default.** The SDK defaults `verify_tls=True`. (The conformance
  test harness defaults `--insecure` for self-signed dev certs; the SDK must not
  inherit that footgun.)
- **No secret leakage**: the API key is never logged or placed in URLs; only the
  `x-api-key` header. Error reprs redact it.
- The SDK only ever **verifies** signatures; it holds no private key and cannot
  sign transcripts or KGs.

## Conformance implications

None to the Level 1/2/3 requirements. The SDK is a client, not part of the
conformant runtime. (A future "client conformance" smoke — does the SDK
round-trip a known envelope and verify it — could live under `conformance/` but
is out of scope for v0.)

## Rollout plan

1. Land this RFC as **Draft**; solicit feedback (14-day minimum per governance).
2. **PR 1 — extract `ski-schemas`.** Move the models + verify helpers; runtime
   re-exports; the full existing suite stays green. No new functionality.
3. **PR 2 — `ski-sdk` v0.** `SKIClient` / `AsyncSKIClient`, `verify_transcript`,
   typed errors, KG pre-flight. Tested end-to-end against the no-infra
   `FakeLLM`-backed server (the path proven in the v3.0.3 acceptance test).
4. Docs: a "Use the SDK" page + the verify recipe; publish both to PyPI.
5. Iterate from real usage; revisit multi-language only if pulled.

## Open questions

- **Public-key distribution.** Does the runtime expose the transcript signing
  public key over the API (for `verify_transcript`), or must auditors obtain it
  out-of-band? `signing.py` writes a `<key>.pub`; an additive
  `GET /api/transcript-key` (PEM) would make the SDK's verify path
  self-contained.
- **Package names.** `ski-sdk` vs `ski-client`; `ski-schemas` vs `ski-core`.
- **Sync + async both in v0**, or async-first with a sync shim?
- **KG validation**: depend on `kg-validator` or validate against the shared
  schema directly (avoids a heavier dependency)?
- Default **retry / backoff** policy and which methods are safe to retry.

## References

- Specification §6 (LLM transcript / audit ledger).
- [RFC 0002 — SKI v3.0: Neuro-Symbolic Pivot](0002-v3-neuro-symbolic-pivot.md).
- [Threat model](../threat-model.md).
- v3.0.3 end-to-end acceptance test (provenance-verification friction; the
  `FakeLLM` no-infra path the SDK tests will reuse).
