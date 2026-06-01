# Glossary

Domain terms used throughout the SKI Framework specification and
implementation. When a term has a regulatory meaning *and* an SKI-specific
meaning, both are defined.

---

## Agreement monitor

The rolling-window tracker (`ski_model.v3.AgreementMonitor`) that
records every verdict's [Verifier status](#verifier-status) and exposes
an `agreement_rate = AGREED / total` plus a healthy / unhealthy signal.
Replaces the v2 [Determinism canary](#determinism-canary). Pages on a
sustained drop below the configured threshold (default 0.95).

## Audit ledger

The append-only Postgres table (`ledger_entries`) that records every
verdict the runtime produces. Each row chains to its predecessor via a
SHA-256 hash, and `UPDATE` / `DELETE` / `TRUNCATE` statements are rejected
by database triggers (`append_only.sql`). v3 extends the row with the
[signed LLM transcript](#llm-transcript), model provenance hashes, KG
citations, and the verifier status. A third party can re-verify the
ledger using only the canonical serialization documented in
`tools/audit-ledger/src/audit_ledger/canonical.py`.

See also: [Replay](replay.md).

## CLEAR

One of the five verdicts. Applicable rules were evaluated and no
compliance issue was detected. Normal operation; logged to the audit
ledger like every other verdict.

## Conformance level

A claim about how rigorously an implementation satisfies the
specification. v3 defines three:

- **Provenance** — every verdict envelope is complete, the Symbolic
  Verifier ran, citations exist, the agreement monitor is mounted, and
  the verdict taxonomy is exactly the five canonical values.
- **Durability** — the KG is signed; the Risk-Tier Governor is strict;
  the audit ledger is append-only at the DB layer; the hash chain
  recomputes entry hashes (not just chain linkage); replay reproduces
  historical verdicts.
- **Sovereignty** — operable air-gapped, tamper-evident, end-to-end
  signed. (Scaffolded; harness is the v3.1 milestone.)

See [Conformance](conformance.md).

## Coverage Register

A read-only Postgres view (`coverage_register`) exposing every
`NULL_UNMAPPED` and `NULL_STALE` verdict. KG editors use it to identify
gaps in the obligation set and freshness expectations.

## Determinism canary

The v2 mechanism — a fixed input + expected verdict pair that the
service re-evaluated on a schedule. **Retired in v3** in favour of the
[Agreement monitor](#agreement-monitor), which measures the live
LLM↔verifier agreement rate continuously instead of replaying a
synthetic baseline.

## DISCRETIONARY

One of the five verdicts. The rule applies but evaluating it requires
qualified human judgment; route to a compliance expert.

## Ed25519

The signature scheme used to sign Knowledge Graphs and LLM transcripts.
Chosen for short keys (32 bytes), short signatures (64 bytes), and
constant-time verification. The runtime refuses to load an unsigned KG —
there is no escape hatch.

## Extraction quality

The extractor's authoring-time trust signal on a [ComplianceRule]
(EXPLICIT / DISCRETIONARY / CONFLICTING). It is **not** a runtime
confidence score (Axiom 2 prohibits those in the audit trail). v3
renamed it from the v2 `confidence` to avoid confusion with the
runtime's prohibited `confidence_level`.

## FLAG

One of the five verdicts. A compliance rule has been breached. The
sidecar emits an alert; a designated human reviewer is escalated.

## Formalizable assertion

A structured claim the LLM produces alongside its verdict (e.g.
`{ "obligation_id": "x", "metric": "so2_ppm", "operator":
"must_not_exceed", "observed": 87, "expected": 100, "satisfied": true
}`). The [Symbolic Verifier](#symbolic-verifier) cross-checks each
formalizable assertion mechanically and records AGREED / contradiction
/ divergence / unverifiable.

## Jurisdictional scope

The v3 KG's mechanism for routing only the obligations applicable to a
tenant's jurisdiction (and effective at the measurement's timestamp)
into the LLM prompt. Implemented by
`KnowledgeGraph.scope_to(jurisdiction, as_of)`; the scope block
(`jurisdiction`, `as_of`, `n_in`, `n_out`) travels in the signed LLM
transcript so an auditor can confirm *what was sent*.

## Knowledge Graph (KG)

The compiled, signed artifact that drives the runtime. In v3 it is a
typed graph of nodes (Subject, Rule, Obligation, Definition, Exemption,
Precedent, Jurisdiction, Citation) and edges (`applies_to`,
`consists_of`, `defined_by`, `exempted_by`, `amended_by`,
`interpreted_by`, `scoped_to`, `cited_by`). Produced by the
**kg-extractor** + **kg-validator** Phase 1 pipeline. Loaded once per
version and never modified at runtime.

## LLM transcript

The verbatim prompt + LLM response, plus the prompt template hash,
decoder seed, structured-grammar hash, and the model-weight hash for
the backend that produced it. Signed (ed25519) by the runtime and
recorded alongside the ledger entry. Reconstructable by an auditor —
the v3 *verifiable provenance* contract.

## NULL_STALE

One of the five verdicts. A rule matched, but its
`requires_recent_within_seconds` freshness gate found no telemetry
sample in the buffer for that subject within the window.

## NULL_UNMAPPED

One of the five verdicts. The telemetry's `subject` is not present in
the KG. Document in the Coverage Register; expand the KG.

## Pillar

One of the four non-negotiable design constraints SKI is built on:
Determinism (of provenance, not of bits in v3), Sovereignty,
Auditability, Human Primacy.

## Predicate

The structured operand inside an Obligation that the
[Symbolic Verifier](#symbolic-verifier) interprets. v3 stateless
operators: `must_not_exceed`, `must_be_at_least`, `must_be_within`,
`must_equal`, `must_not_equal`, plus `must_be_one_of`,
`must_not_be_one_of`, `must_be_recorded_within`. v3 stateful operators
(against the [Telemetry buffer](#telemetry-buffer)): `window_count`,
`window_sum`, `window_avg`.

## Replay

Re-evaluating a range of ledger entries against the recorded KG and
telemetry buffer, then comparing the produced verdict to the
originally-recorded verdict. The deterministic-replay primitive
(`audit-ledger replay`) underpins the Durability conformance level.

See [Replay](replay.md).

## Risk-Tier Governor

The authoritative source of risk tier per obligation (spec v3.0 §5.4).
Reads each KG rule's optional `risk_tier` field and returns the
strictest tier across the obligations applicable to a measurement.
**Strict by design** — the caller cannot self-declare a tier. The
strictest tier across applicable rules wins; default is `tier-2`.

## Sidecar

The passive, read-only telemetry intake service. Reads from file / HTTP
/ Kafka, normalises records, and forwards them to the SKI Model. The
sidecar **does not perform tag inference** — that routing decision
belongs to the runtime.

## SKI Model

The runtime service that hosts the v3 Evaluator. Wraps the local LLM
backend (Ollama by default; pluggable via the `V3LLMBackend`
protocol), runs structured generation against the scoped KG snapshot,
hands the result to the Symbolic Verifier, applies the risk-tier
policy, signs the transcript, and writes the envelope to the ledger.

## Sovereignty

The constraint that operational data must never leave the
organisation's infrastructure boundary. SKI satisfies it by running
inference on a local LLM (Ollama, vLLM, or llama.cpp) inside the same
Docker network as the audit ledger. The Sovereignty conformance level
(v3) makes the constraint testable.

## Subject

The dotted-path string that identifies what a telemetry record is
about, e.g. `facility.so2.discharge_ppm`. v3 obligations are scoped to
a subject via the `applies_to` edge. Producers MUST NOT include a
`rule_id` in telemetry records.

## Symbolic Verifier

The v3 mechanical cross-check on the LLM's
[formalizable assertions](#formalizable-assertion). For each assertion,
the verifier evaluates the underlying predicate against the same
telemetry and emits one of four statuses: `AGREED`,
`LLM_CONTRADICTION` (LLM was wrong about the verifiable claim),
`NEURO_SYMBOLIC_DIVERGENCE` (LLM verdict ≠ verifier verdict for a
non-trivial reason), `UNVERIFIABLE` (the assertion's predicate is not
formalizable or telemetry is missing).

## Tag Registry

The compile-time, governed subject → rule mapping carried in the KG.
The v3 package retains the v2 invariant (no runtime fuzzy matching, no
LLM disambiguation, no embedding lookup) and additionally houses the
[Risk-Tier Governor](#risk-tier-governor).

## Telemetry buffer

The Postgres-backed, append-only, RANGE-partitioned-by-`telemetry_ts`
table that stores recent telemetry for stateful predicate evaluation.
Retention is configured per tenant (no default). Introduced in v0.2.0
([RFC 0001](RFCs/index.md)).

## Verdict

The structured output of evaluating a measurement against the KG.
Exactly five values: `CLEAR`, `FLAG`, `NULL_UNMAPPED`, `NULL_STALE`,
`DISCRETIONARY`. No scores, no probabilities, no confidence levels —
that's a deliberate constraint (Axiom 2).

## Verdict envelope

The v3 audit-grade contract around the verdict. Carries: `verdict`,
`reasoning`, `kg_citations`, `formalizable_assertions`,
`verifier_result`, `model_provenance`, `transcript_ref`. Validates
under `extra="forbid"` — unknown fields are a contract violation.

## Verifier status

One of four spec-normative outcomes the
[Symbolic Verifier](#symbolic-verifier) emits per evaluation:
`AGREED`, `LLM_CONTRADICTION`, `NEURO_SYMBOLIC_DIVERGENCE`,
`UNVERIFIABLE`. Recorded in the ledger; fed to the
[Agreement monitor](#agreement-monitor) in aggregate.
