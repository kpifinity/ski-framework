# Glossary

Domain terms used throughout the SKI Framework specification and
implementation. When a term has a regulatory meaning *and* an SKI-specific
meaning, both are defined.

---

## Audit ledger

The append-only Postgres table (`ledger_entries`) that records every
verdict the runtime produces. Each row chains to its predecessor via a
SHA-256 hash, and `UPDATE` / `DELETE` / `TRUNCATE` statements are rejected
by database triggers (`append_only.sql`). A third party can re-verify the
ledger using only the canonical serialization documented in
`tools/audit-ledger/src/audit_ledger/canonical.py`.

See also: [Replay](replay.md).

## CLEAR

One of the five verdicts. Applicable rules were evaluated and no
compliance issue was detected. Normal operation; logged to the audit
ledger like every other verdict.

## Conformance level

A claim about how rigorously an implementation satisfies the
specification. SKI defines three:

- **Level 1 — Foundational.** Determinism, signature verification,
  ledger integrity. Single-domain happy path.
- **Level 2 — Managed.** Stateful evaluation, NULL_STALE routing,
  Tag Registry coverage. Multi-domain.
- **Level 3 — Assured.** Tamper-resistance under adversarial inputs,
  determinism canary, third-party verifiability.

See [Conformance](conformance.md).

## Coverage Register

A read-only Postgres view (`coverage_register`) exposing every
`NULL_UNMAPPED` and `NULL_STALE` verdict. The KG editor uses it to
identify gaps in the Tag Registry and freshness expectations.

## Determinism canary

A fixed input + expected verdict pair that the SKI Model service
re-evaluates on a schedule. If the verdict ever changes, the canary
fails — signalling that something in the inference path (model, seed,
quantization, library version) has drifted.

## DISCRETIONARY

One of the five verdicts. The rule applies but evaluating it requires
qualified human judgment; route to a compliance expert. Track 2 rules
typically produce this verdict.

## Ed25519

The signature scheme used to sign Knowledge Graphs. Chosen for short
keys (32 bytes), short signatures (64 bytes), and constant-time
verification. The SKI Model service refuses to load an unsigned KG
unless `KG_REQUIRE_SIGNATURE=false` (non-conformant).

## FLAG

One of the five verdicts. A compliance rule has been breached. The
sidecar emits an alert; a designated human reviewer is escalated.

## Knowledge Graph (KG)

The compiled, signed artifact that drives the runtime. Contains:

- `rules`: list of compliance rules with predicates.
- `tag_registry`: subject → rule mapping.
- `metadata`: version, sector, compilation provenance.
- `signature`: Ed25519 signature over the canonical form.

KGs are produced by the **kg-extractor** + **kg-validator** Phase-1
pipeline. They are loaded once at runtime and never modified.

## NULL_STALE

One of the five verdicts. A rule matched, but its
`requires_recent_within_seconds` freshness gate found no telemetry
sample in the buffer for that subject within the window. Investigate
upstream freshness; the runtime cannot meaningfully evaluate stale
inputs.

## NULL_UNMAPPED

One of the five verdicts. The telemetry's `subject` is not present in
the Tag Registry. Document in the Coverage Register; expand the KG.

## Pillar

One of the four non-negotiable design constraints SKI is built on:
Determinism, Sovereignty, Auditability, Human Primacy.

## Predicate

The structured AST inside a rule that the Symbolic Evaluator
interprets:

```json
{"operator": "lte", "metric": "so2_ppm", "value": 100, "unit": "ppm"}
```

Operators: `lte`, `gte`, `lt`, `gt`, `eq`, `range`, `between`, `in_set`,
`not_in_set`, `exists`, and the v0.2 stateful operators `window_count`,
`window_sum`, `window_avg`, `since_last`, `debounce`.

## Replay

Re-evaluating a range of ledger entries against the recorded KG and
telemetry buffer, then comparing the produced verdict to the originally-
recorded verdict. The deterministic-replay primitive
(`audit-ledger replay`) underpins Level 3 conformance.

See [Replay](replay.md).

## Sidecar

The passive, read-only telemetry intake service. Reads from file / HTTP /
Kafka, normalises records, and forwards them to the SKI Model. Crucially,
the sidecar **does not perform tag inference** — subject→rule routing is
the SKI Model's responsibility via the Tag Registry.

## SKI Model

The runtime service that wraps the local LLM (Ollama by default) with
determinism controls, structured-output enforcement, and Tag Registry
gating. Formerly called *MiLM* (Mini-LM) in pre-v2.1 documentation;
renamed because the v2.1 spec broadened scope beyond the original
"miniature LM" framing.

## Sovereignty

The constraint that operational data must never leave the organisation's
infrastructure boundary. SKI satisfies it by running inference on a
local LLM (Ollama, vLLM, or llama.cpp) inside the same Docker network as
the audit ledger.

## Subject

The dotted-path string that identifies what a telemetry record is about,
e.g. `facility.so2.discharge_ppm`. The Tag Registry maps subjects to
rules. Producers MUST NOT include a `rule_id` in telemetry records — that
routing decision belongs to the runtime.

## Symbolic Evaluator

The Track 1 evaluator. A pure function from `(rule, telemetry)` to
verdict. No LLM involved. Operators are limited to the predicate grammar
above; rules that need natural-language interpretation must be declared
`track: "llm"` and route to Track 2 instead.

## Tag Registry

The compile-time, governed subject → rule mapping (specification B4.3).
A first-class artifact: rule routing is a property of the KG, not a
runtime decision. Loaded once per KG version.

## Telemetry buffer

The Postgres-backed, append-only, RANGE-partitioned-by-`telemetry_ts`
table that stores recent telemetry for stateful predicate evaluation.
Retention is configured per tenant (no default). Introduced in v0.2.0
([RFC 0001](RFCs/index.md)).

## Track 1 / Track 2

The two runtime tracks. **Track 1** (`track: "symbolic"`) routes to the
Symbolic Evaluator and is deterministic by construction. **Track 2**
(`track: "llm"`) routes through the local LLM under `temperature=0` and
a fixed seed — best-effort deterministic, but not formally guaranteed.
Replay skips Track 2 entries by design.

## Verdict

The structured output of evaluating a rule against telemetry. Exactly
five values: `CLEAR`, `FLAG`, `NULL_UNMAPPED`, `NULL_STALE`,
`DISCRETIONARY`. No scores, no probabilities, no confidence levels —
that's a deliberate constraint (specification B3.1).
