---
hide:
  - toc
---

# SKI Framework Specification v3.0

| | |
|---|---|
| **Status** | Draft (pending RFC 0002 acceptance) |
| **Editor** | KpiFinity Inc. |
| **License** | CC BY 4.0 |
| **Supersedes** | SKI Framework Specification v2.1 |
| **Reference RFC** | [RFC 0002 — SKI v3.0 Neuro-Symbolic Pivot](RFCs/0002-v3-neuro-symbolic-pivot.md) |

## 0. Status of this document

This is the normative specification for SKI Framework v3.0. The
architectural rationale, alternatives considered, and rollout plan
live in [RFC 0002](RFCs/0002-v3-neuro-symbolic-pivot.md). This document
states what an implementation MUST, SHOULD, and MAY do in order to
conform to the v3.0 specification.

v3.0 supersedes v2.1. v2.1 implementations remain conformant to v2.1
indefinitely; the v3.0 conformance ladder is distinct. The
[backwards-compatibility section](#11-backwards-compatibility) defines
how v2.x ledger entries and v2.x Knowledge Graphs are handled by v3.0
implementations during the dual-runtime period.

This document is published under the Creative Commons Attribution 4.0
International license. Software implementing this specification is
covered by its own licensing terms; the reference implementation in
the SKI Framework repository is Apache 2.0.

## 1. Conformance terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL
NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and
**OPTIONAL** in this document are to be interpreted as described in
RFC 2119 and RFC 8174 when, and only when, they appear in all capitals
as shown here.

Throughout this document:

- **"the framework"** means the SKI Framework as a whole.
- **"this specification"** means this document, v3.0.
- **"an implementation"** means any software that claims conformance
  to some level of this specification.
- **"the reference implementation"** means the open-source
  implementation maintained by KpiFinity at
  <https://github.com/kpifinity/ski-framework>.
- **"the operator"** means the organization deploying an implementation
  in a regulated environment.

The framework has three pillars: Sovereign, Knowledge, Intelligence.
These pillars are normative. An implementation that does not satisfy
all three pillars MUST NOT claim conformance to this specification at
any level.

## 2. Architecture

### 2.1 The three pillars

#### 2.1.1 Sovereign

An implementation MUST evaluate every verdict on infrastructure
controlled by the operator. Specifically, during the evaluation hot
path:

1. The local language model weights MUST reside on host-attached
   storage controlled by the operator.
2. The Knowledge Graph MUST reside on host-attached storage controlled
   by the operator.
3. The Symbolic Verifier MUST execute in-process or in an
   operator-controlled service, never on a third-party endpoint.
4. The Audit Ledger MUST write to operator-controlled storage.
5. No outbound network calls to third-party inference, retrieval,
   verification, or storage services MAY be issued during a verdict's
   evaluation.

An implementation MAY perform out-of-band egress for explicitly
governed channels: Knowledge Graph distribution from a signed upstream,
telemetry receipt to a downstream observer, and out-of-band log or
metric shipping. Egress channels MUST be enumerable, MUST be configured
explicitly by the operator, and MUST NOT be reachable from the
evaluation hot path.

An implementation MUST expose a sovereignty attestation endpoint as
defined in [§6](#6-sovereignty).

#### 2.1.2 Knowledge

The Knowledge Graph (KG) is the framework's typed semantic substrate.
An implementation MUST represent regulations as a structured KG that
satisfies the schema defined in [§3](#3-knowledge-graph-schema). The
KG MUST NOT be reduced to a routing table; specifically, every rule
served by an implementation MUST reference at least one typed
obligation node.

The KG MUST be human-reviewed in a Phase 1 compilation step before
deployment. The reference tools (`kg-extractor`, `kg-validator`)
implement the reference Phase 1 pipeline; an implementation MAY use
alternative pipelines provided the human-review property is preserved
and demonstrated to a conformance auditor.

The KG MUST be cryptographically signed; an implementation MUST refuse
to load an unsigned KG in `SKI_SOVEREIGNTY=strict` mode. The signing
scheme is Ed25519. The trust anchor MUST be configured by the operator;
the implementation MUST NOT ship with a default trust anchor that
chains to KpiFinity or any other vendor.

#### 2.1.3 Intelligence

An implementation MUST use a language model as the primary reasoner on
every verdict. Specifically, the runtime path defined in
[§5](#5-runtime-model) is non-negotiable: for every verdict request,
the implementation MUST perform KG retrieval, KG-grounded LLM
evaluation, and symbolic verification in that order.

The language model MUST run within the sovereignty perimeter defined
in §2.1.1. The reference implementation supports Ollama, vLLM, and
llama.cpp as inference backends; any backend that satisfies the
sovereignty pillar is permitted.

The language model MUST be invoked with deterministic decoding
parameters:

- Temperature MUST be 0 (or, if the backend does not support exactly
  zero, the minimum value permitted by the backend that the
  implementation can demonstrate is operationally indistinguishable
  from zero).
- Top-p MUST be 1.0.
- Top-k MUST be 1.
- A decoder seed MUST be set and recorded in the verdict envelope.
- Structured-generation constraints (grammar-bounded decoding) MUST be
  enabled so that the language model's output is parseable as the
  verdict envelope schema in [§4](#4-verdict-envelope) without
  post-hoc string repair.

### 2.2 Runtime pipeline

Every verdict MUST be produced by the following five-step pipeline.
The pipeline is normative; an implementation MUST NOT short-circuit
any step except as explicitly permitted by [§5.6](#56-the-fast-path-optimization).

1. **Telemetry ingestion.** A telemetry record arrives at the
   implementation's evaluation entry point.
2. **KG retrieval.** The implementation queries the KG for the typed
   semantic slice relevant to the rule referenced by the telemetry
   record's subject, scoped to the record's `as_of` timestamp and
   declared jurisdiction.
3. **KG-grounded LLM evaluation.** The implementation invokes the
   language model with the rule, the KG slice, and the telemetry
   record. The model emits a structured verdict envelope as defined in
   [§4](#4-verdict-envelope).
4. **Symbolic verification.** The implementation invokes the Symbolic
   Verifier (see [§5.3](#53-the-symbolic-verifier)) to cross-check the
   language model's `formalizable_assertions` against the rule's
   formalizable subset.
5. **Audit ledger write.** The implementation appends a ledger entry
   containing the full verdict envelope, the language model
   transcript, the model provenance metadata, and the verifier's
   result, hash-chained to the prior entry.

### 2.3 Out of scope

The following are out of scope for v3.0 and are addressed by separate
specifications or RFCs:

- Multi-tenant model weight isolation. Out of scope; v3.1+ work item.
- Cross-jurisdictional rule federation. Out of scope; future work.
- Frontier-model integration via remote APIs. Explicitly disallowed
  by the sovereignty pillar.
- Probabilistic verdicts. Explicitly disallowed by the verdict
  taxonomy in [§4.1](#41-the-five-verdict-taxonomy).
- Verdict appeal and override workflows. Out of scope; the framework
  defines the data plane, not the operator's case-management plane.

## 3. Knowledge Graph schema

### 3.1 Node types

The KG MUST consist of nodes of the following types. Each node has a
stable identifier, a version, and a citation.

| Node type | Purpose |
|---|---|
| `Subject` | A telemetry subject that a rule can apply to (e.g., a specific emission stack, a transaction, a position) |
| `Rule` | A regulatory requirement composed of one or more obligations |
| `Obligation` | A typed normative statement (see [§3.3](#33-typed-obligations)) |
| `Definition` | A regulatory term and its scope-restricted meaning |
| `Exemption` | A condition under which an obligation does not apply |
| `Precedent` | A prior obligation that the present one amends, supersedes, or interprets |
| `Jurisdiction` | A scope identifier (country, state, regulatory body, internal policy) |
| `Citation` | A reference to the originating regulatory text |

Every node MUST have a stable, globally-unique identifier (the
implementation MAY use UUIDs, content-addressed hashes, or a
hierarchical naming scheme; the choice is implementation-defined but
MUST be stable across re-emissions of the same node).

Every node MUST carry a `version` field. KG versions are content-
addressed: the `version` of a node is the SHA-256 of the canonical
serialization of the node's content (excluding the version field
itself).

Every `Obligation`, `Definition`, `Exemption`, and `Precedent` node
MUST carry a `Citation` edge to one or more `Citation` nodes.

### 3.2 Edge types

The KG MUST support the following edge types. All edges are directional
and typed.

| Edge type | From | To | Semantics |
|---|---|---|---|
| `applies_to` | `Rule` | `Subject` | The rule applies to telemetry from this subject |
| `consists_of` | `Rule` | `Obligation` | The rule is composed of this obligation |
| `defined_by` | `Obligation` | `Definition` | The obligation's terms are scoped by this definition |
| `exempted_by` | `Obligation` | `Exemption` | The obligation does not apply when this exemption holds |
| `amended_by` | `Precedent` | `Obligation` | A subsequent obligation that amends the precedent |
| `interpreted_by` | `Obligation` | `Precedent` | The obligation should be read in the light of this precedent |
| `scoped_to` | `Obligation` | `Jurisdiction` | The obligation only applies in this jurisdiction |
| `cited_by` | any | `Citation` | The originating regulatory text |

### 3.3 Typed obligations

An `Obligation` node MUST carry a `type` field drawn from the following
closed enumeration:

- `must` — the subject MUST satisfy the predicate.
- `must_not` — the subject MUST NOT satisfy the predicate.
- `must_not_exceed` — the predicate yields a numeric value that MUST
  NOT exceed the operand.
- `must_be_at_least` — the predicate yields a numeric value that MUST
  be at least the operand.
- `must_be_below` — the predicate yields a numeric value that MUST be
  strictly less than the operand.
- `must_be_above` — the predicate yields a numeric value that MUST be
  strictly greater than the operand.
- `must_be_within` — the predicate yields a value that MUST be within
  a specified range.
- `must_be_one_of` — the predicate yields a value that MUST be a
  member of an enumerated set.
- `must_not_be_one_of` — the predicate yields a value that MUST NOT
  be a member of an enumerated set.
- `must_be_recorded_within` — the predicate is a temporal window;
  evidence MUST be present in the window.
- `should` — a non-binding recommendation; affects `DISCRETIONARY`
  routing but never produces `FLAG`.
- `discretionary` — the obligation requires qualified human judgment
  to evaluate; ALWAYS produces `DISCRETIONARY`.

Implementations MUST treat obligations of unknown type as
`DISCRETIONARY` and record the unknown-type detection in the verdict
envelope's `verifier_result.divergences` array.

### 3.4 Jurisdictional scope and effective-date intervals

Each `Obligation` MAY be scoped to one or more `Jurisdiction` nodes
via `scoped_to` edges. An obligation with no `scoped_to` edge applies
universally (i.e., in any jurisdiction).

Each `Obligation` MUST carry an `effective_date_start` field
(ISO 8601 date-time, RFC 3339). An obligation MAY carry an
`effective_date_end` field; absence MUST be interpreted as "no end
date".

At evaluation time, an implementation MUST resolve which obligations
apply to a telemetry record by intersecting:

1. The set of obligations reachable from the `Rule` referenced by the
   telemetry subject.
2. The set of obligations whose `effective_date_start <= as_of <=
   effective_date_end` (with `effective_date_end` treated as `+inf`
   when absent).
3. The set of obligations whose `scoped_to` jurisdictions contain the
   telemetry record's declared jurisdiction (or whose `scoped_to` is
   empty).

The intersection MUST be the set of obligations the language model is
shown in the KG slice. Obligations outside the intersection MUST NOT
be passed to the language model.

### 3.5 Signature requirements

The KG MUST be cryptographically signed at distribution time. The
signing scheme is Ed25519.

The signature MUST cover the canonical serialization of the entire KG
including all nodes, edges, and embedded metadata. The canonical
serialization scheme is defined in [§7.3](#73-prompt-template-and-kg-canonical-hashing).

An implementation in `SKI_SOVEREIGNTY=strict` mode MUST refuse to load
a KG whose signature does not verify against an operator-configured
trust anchor.

In `SKI_SOVEREIGNTY=advisory` mode, an implementation MAY load an
unsigned KG; it MUST log a warning and the verdict envelope MUST
record `kg_version_hash` as the empty hash (sha256 of empty bytes) so
auditors can distinguish unsigned-KG evaluations.

### 3.6 Validation requirements

The reference `kg-validator` MUST detect and reject the following
classes of defects before a KG is signed for distribution:

- Duplicate nodes (same identifier, different content).
- Contradictory obligations (same subject and relation with
  numerically incompatible operands; see CHANGELOG v0.2.1 for the
  motivating bug).
- Date-interval overlaps for obligations that are mutually exclusive
  by relation.
- Cyclic precedent edges.
- `applies_to` edges pointing at undefined `Subject` nodes.
- `consists_of` edges pointing at obligations whose `type` is not in
  the enumeration of [§3.3](#33-typed-obligations).
- Obligations missing `effective_date_start`.
- Obligations referencing a `Definition` whose scope does not cover
  the obligation.

Implementations MAY add additional validation passes; the reference
validator's passes are the minimum a conforming KG distribution MUST
satisfy.

## 4. Verdict envelope

### 4.1 The five-verdict taxonomy

Every verdict produced by an implementation MUST carry exactly one of
the following five values in its `verdict` field:

- `CLEAR` — applicable obligations evaluated; no compliance issue.
- `FLAG` — at least one applicable obligation breached.
- `NULL_UNMAPPED` — the telemetry subject is not present in the KG.
- `NULL_STALE` — an obligation with a temporal freshness predicate
  matched, but the freshness window was not satisfied.
- `DISCRETIONARY` — an applicable obligation requires qualified human
  judgment to evaluate.

Implementations MUST NOT emit verdict values outside this enumeration.
Implementations MUST NOT emit numeric scores, probabilistic confidence
intervals, or ranges as the primary verdict. Such values MAY be
recorded in the `reasoning` field as supporting information; they
MUST NOT replace the verdict.

### 4.2 Envelope structure

The verdict envelope is a structured object. Every verdict envelope
MUST contain the following fields.

**Required fields.**

| Field | Type | Description |
|---|---|---|
| `verdict` | enum | One of the five values in [§4.1](#41-the-five-verdict-taxonomy) |
| `reasoning` | string | Natural-language reasoning produced by the language model |
| `kg_citations` | array | KG nodes the language model cited (see [§4.3](#43-kg-citations)) |
| `formalizable_assertions` | array | Structured assertions the language model committed to (see [§4.4](#44-formalizable-assertions)) |
| `verifier_result` | object | Symbolic verifier's per-assertion result (see [§4.5](#45-verifier-result)) |
| `model_provenance` | object | Inference provenance metadata (see [§4.6](#46-model-provenance)) |
| `transcript_ref` | string | Pointer to the language model transcript in the ledger transcript store (see [§7.4](#74-transcript-store)) |

**Optional fields.**

| Field | Type | Description |
|---|---|---|
| `human_attestation` | object | Attestation token if required by the risk tier (see [§5.4](#54-the-risk-tier-governor)) |
| `notes` | array of strings | Implementation-specific annotations |

### 4.3 KG citations

A `kg_citations` element is an object with the following required
fields:

- `node_id` — the stable identifier of the cited KG node.
- `version` — the content-addressed version of the cited node at
  evaluation time.
- `role` — one of `obligation`, `definition_resolved`,
  `exemption_considered`, `precedent_referenced`,
  `jurisdiction_matched`.

The `kg_citations` array MUST include every obligation that
contributed to the verdict. The `kg_citations` array SHOULD include
every definition, exemption, precedent, and jurisdictional match the
language model relied on. Implementations MUST NOT include citations
to nodes that were not present in the KG slice supplied to the
language model.

### 4.4 Formalizable assertions

A `formalizable_assertions` element is an object representing a
language-model assertion that the Symbolic Verifier can mechanically
check.

| Field | Type | Description |
|---|---|---|
| `predicate` | enum | The predicate type, drawn from the same enumeration as `Obligation.type` in [§3.3](#33-typed-obligations) |
| `metric` | string | A dotted-path identifier into the telemetry record's measurement object |
| `value` | scalar | The operand the predicate is being evaluated against |
| `observed` | scalar | The measured value the language model claims it observed |
| `satisfied` | boolean | The language model's claim about whether the predicate is satisfied |
| `obligation_id` | string | The KG obligation this assertion is checking |

The `formalizable_assertions` array MAY be empty if the rule has no
formalizable subset. Implementations MUST record an empty array as
`[]`, not as a missing field.

### 4.5 Verifier result

The `verifier_result` field is a single object with the following
required fields.

| Field | Type | Description |
|---|---|---|
| `status` | enum | `AGREED`, `LLM_CONTRADICTION`, `NEURO_SYMBOLIC_DIVERGENCE`, or `UNVERIFIABLE` |
| `checked_assertions` | integer | The count of formalizable assertions the verifier independently evaluated |
| `divergences` | array | Details of any disagreement |

The `status` values are normative and mean:

- `AGREED` — the verifier ran every formalizable assertion and
  agreed with the language model's `satisfied` value on each.
- `LLM_CONTRADICTION` — the verifier detected at least one assertion
  where the language model's `observed` value does not satisfy its
  own `satisfied` claim (e.g., `observed=120`, `value=100`,
  `predicate=must_not_exceed`, `satisfied=true` is a contradiction).
- `NEURO_SYMBOLIC_DIVERGENCE` — the verifier and the language model
  reached different conclusions on the same formalizable assertion
  for reasons that are not a direct contradiction. The verdict is
  not necessarily wrong; the divergence is recorded for human
  review.
- `UNVERIFIABLE` — the rule has no formalizable subset, or the
  verifier could not be invoked. Conforming implementations MUST NOT
  silently elide verification; if `UNVERIFIABLE` is recorded, the
  reason MUST be recorded in `divergences`.

### 4.6 Model provenance

The `model_provenance` field is an object with the following required
fields.

| Field | Type | Description |
|---|---|---|
| `model_weight_hash` | string | SHA-256 of the language model weights, prefixed `sha256:` |
| `kg_version_hash` | string | SHA-256 of the canonical KG used in evaluation |
| `prompt_template_id` | string | Stable identifier of the prompt template (e.g., `ski.v3.evaluate.1`) |
| `prompt_template_hash` | string | SHA-256 of the rendered prompt template, prefixed `sha256:` |
| `decoder_seed` | integer | The decoder seed used for inference |
| `structured_grammar_hash` | string | SHA-256 of the structured-generation grammar |

All hash values MUST be lowercase hex, prefixed with the algorithm
identifier (e.g., `sha256:abc123...`). Implementations MAY use
stronger hashes in addition; SHA-256 is the minimum a conforming
implementation MUST support.

## 5. Runtime model

### 5.1 KG retrieval

An implementation MUST resolve the relevant KG slice for each verdict
request by:

1. Identifying the `Rule` nodes whose `applies_to` edges target the
   telemetry record's subject.
2. Identifying the `Obligation` nodes reachable from those rules via
   `consists_of`.
3. Filtering by `effective_date_start <= as_of` and (if
   `effective_date_end` is present) `as_of <= effective_date_end`.
4. Filtering by jurisdictional match per [§3.4](#34-jurisdictional-scope-and-effective-date-intervals).
5. Including the `Definition`, `Exemption`, and `Precedent` nodes
   reachable from the surviving obligations.
6. Including the `Citation` nodes for every surviving node.

The resulting slice MUST be passed to the language model in the
inference call. The slice MUST NOT include nodes that did not survive
the filtering passes.

### 5.2 KG-grounded LLM evaluation

The language model MUST be invoked with a deterministic prompt
constructed from the KG slice, the telemetry record, and the rule's
metadata. The prompt construction MUST be:

1. Deterministic given the same inputs.
2. Identifiable by a stable `prompt_template_id`.
3. Canonically hashable; the `prompt_template_hash` recorded in
   `model_provenance` MUST be the SHA-256 of the rendered prompt as
   sent to the language model.

The language model MUST be invoked with the decoder parameters
specified in [§2.1.3](#213-intelligence) and with structured-generation
constraints that bind its output to the verdict envelope schema.

The language model's output MUST be parsed as the verdict envelope.
Parse failures MUST be treated as `DISCRETIONARY` verdicts with the
parse error recorded in `verifier_result.divergences`.

### 5.3 The Symbolic Verifier

The Symbolic Verifier is an independent component that receives the
rule, the verdict envelope's `formalizable_assertions`, and the KG
slice. For each assertion in `formalizable_assertions`, the verifier
MUST:

1. Resolve `metric` against the telemetry record's measurement object.
2. Compute the predicate's truth value against the resolved metric
   and the assertion's `value`.
3. Compare the computed truth value to the language model's
   `satisfied` claim.
4. Compare the computed truth value to the verifier's own evaluation
   of the same obligation against the KG.

The verifier MUST produce a `verifier_result` object per
[§4.5](#45-verifier-result). The verifier MUST NOT modify the verdict
field of the envelope; the risk tier governor (next section) decides
whether to honour the language model's verdict given the verifier's
findings.

### 5.4 The risk tier governor

Every `Rule` node in the KG MUST carry a `risk_tier` field drawn from
the enumeration `low`, `medium`, `high`. The risk tier governs how
the implementation honours the language model's verdict given the
verifier's result.

**Low.** The implementation MUST honour the language model's verdict.
Verifier divergences are logged in the envelope but do not change the
outcome.

**Medium.** If the verifier's status is `AGREED` or `UNVERIFIABLE`,
the implementation MUST honour the language model's verdict. If the
verifier's status is `LLM_CONTRADICTION` or
`NEURO_SYMBOLIC_DIVERGENCE`, the implementation MUST emit
`DISCRETIONARY` and record the divergence.

**High.** If the verifier's status is `AGREED` AND a valid human
attestation token is present in the `human_attestation` field, the
implementation MUST honour the language model's verdict. Otherwise,
the implementation MUST hold the verdict; the verdict is not finalized
until the operator submits an attestation token through the
implementation's attestation API.

### 5.5 Audit ledger write

The implementation MUST append a ledger entry containing the verdict
envelope, the language model transcript, and the verifier's result.
The entry MUST be hash-chained to the prior entry per
[§7](#7-audit-ledger-and-provenance).

### 5.6 The fast-path optimization

For rules whose `risk_tier` is `low` AND whose `formalizable_assertions`
on a prior similar verdict were stable for at least N evaluations (N
operator-configurable, default 1000), an implementation MAY skip the
language model invocation and emit a verdict by running the verifier
alone. This is the **fast path**.

A fast-path verdict MUST:

- Record `verdict_path: "fast"` in the envelope.
- Set `model_provenance.model_weight_hash` to the value the model
  would have used had it been invoked.
- Set `verifier_result.status` to `AGREED` or `LLM_CONTRADICTION`
  based on the verifier's findings.
- Set `kg_citations` to the obligations the verifier evaluated.

The fast path is a Performance Optimization, not a separate Track. An
implementation MUST NOT use the fast path for rules whose `risk_tier`
is `medium` or `high`.

## 6. Sovereignty

### 6.1 Mode selection

An implementation MUST expose the `SKI_SOVEREIGNTY` configuration
parameter with two values: `strict` (default) and `advisory`.

In `strict` mode, the implementation MUST refuse to start if any of
the conditions in [§6.2](#62-strict-mode-requirements) are unmet.

In `advisory` mode, the implementation MAY start with unmet
requirements; each unmet requirement MUST be logged at WARN level
on startup.

Operators MUST NOT deploy `advisory` mode in production. The framework
treats `advisory` mode as a development and CI convenience.

### 6.2 Strict mode requirements

In `strict` mode, the implementation MUST verify on startup:

1. The configured language model backend is a sovereign backend
   (Ollama, vLLM, llama.cpp, or an operator-tagged custom backend).
2. The language model weight hash is present in the implementation's
   local model-weight registry.
3. The configured KG signature trust anchor is operator-provided and
   does not chain to a vendor default.
4. The configured ledger storage is local to the deployment.
5. No outbound network destinations are listed in the implementation's
   evaluation-path egress allowlist.

The implementation MUST refuse to start if any of these checks fails.
The implementation SHOULD emit a structured failure report identifying
which checks failed.

### 6.3 Egress prohibitions

In `strict` mode, the implementation MUST NOT issue any outbound HTTP,
gRPC, or other network call during the evaluation of a verdict. The
implementation MUST emit a Prometheus counter
`ski_egress_attempts_total` that increments on every attempted
outbound call regardless of mode; the determinism canary MUST trip on
non-zero values in `strict` mode.

Out-of-band egress (KG distribution, telemetry receipt, log shipping,
metrics export) MUST be performed by separate processes or
clearly-segregated code paths that are not on the evaluation hot path.

### 6.4 Attestation endpoint

The implementation MUST expose an HTTP endpoint at `/api/sovereignty`
that returns a signed JSON document containing:

- `model_weight_hash` — the active language model's weight hash.
- `kg_version_hash` — the active KG version hash.
- `codebase_commit_hash` — the git commit hash of the running
  implementation.
- `build_provenance_attestation` — an SLSA provenance attestation
  for the running build.
- `signed_at` — the time the attestation was produced.

The document MUST be signed with a key derived from the
implementation's deployment identity, suitable for third-party SLSA
verification.

## 7. Audit ledger and provenance

### 7.1 Ledger schema

The implementation MUST persist every verdict to an append-only ledger
with at minimum the following columns:

| Column | Type | Notes |
|---|---|---|
| `sequence_number` | bigint | Monotonically increasing within a tenant |
| `tenant_id` | text | Operator-defined tenant identifier |
| `previous_hash` | text | SHA-256 of the prior entry; zero hash for sequence 1 |
| `entry_hash` | text | SHA-256 of the canonical serialization of this entry |
| `timestamp` | timestamptz | Time of verdict production |
| `telemetry_id` | text | Identifier of the source telemetry record |
| `telemetry_hash` | text | SHA-256 of the canonical telemetry record |
| `verdict` | text | One of the five values in [§4.1](#41-the-five-verdict-taxonomy) |
| `rule_id` | text | The rule the verdict applies to |
| `kg_version_hash` | text | Per `model_provenance.kg_version_hash` |
| `model_weight_hash` | text | Per `model_provenance.model_weight_hash` |
| `llm_transcript` | jsonb | The verdict envelope plus full LLM transcript |
| `verifier_result` | jsonb | Per [§4.5](#45-verifier-result) |
| `schema_version` | text | Currently `3.0.0` |

The implementation MAY add additional columns; the columns above are
the minimum a conforming implementation MUST emit.

### 7.2 Append-only enforcement

The implementation MUST enforce append-only semantics at the storage
layer. For the reference Postgres ledger, this means database triggers
that reject UPDATE, DELETE, and TRUNCATE on the ledger table.
Storage-layer enforcement is normative; application-layer enforcement
alone is insufficient.

### 7.3 Prompt template and KG canonical hashing

The canonical hash of a prompt template, a KG node, or a KG version
is the SHA-256 of the canonical UTF-8 byte serialization of the
underlying object. The canonical serialization is JSON with the
following rules:

1. Object keys are sorted lexicographically.
2. Whitespace is removed between tokens.
3. String values are UTF-8 NFC-normalized.
4. Numeric values are emitted with the minimum number of significant
   digits required to round-trip.
5. Floating-point values follow ECMA-262 §7.1.12.1 ("ToString applied
   to the Number type").

This canonical scheme is identical to the v2.1 ledger entry hashing
scheme; v3 reuses it for KG and prompt-template hashing.

### 7.4 Transcript store

The full language model transcript MUST be persisted in a transcript
store separate from the main ledger table. The transcript MUST be
referenced from the ledger entry via `llm_transcript->>'transcript_ref'`.

The transcript store MUST be append-only and signature-verifiable
in the same way as the ledger.

The transcript store MAY be partitioned for retention; partition
drop policies are operator-defined.

### 7.5 Verifiable inference receipts

For Level 3 conformance, the implementation MUST attach a verifiable
inference receipt to every verdict. The receipt scheme MUST permit a
third party to verify, given the receipt and the model weights, that
the recorded transcript was produced by the recorded model on the
recorded prompt. The reference scheme is CommitLLM (or equivalent
receipt scheme accepted by KpiFinity's conformance authority).

For Level 1 and Level 2 conformance, the receipt is OPTIONAL.

## 8. Replay

### 8.1 Provenance re-verification procedure

An implementation MUST support replay of v3 ledger entries. The replay
procedure for an entry is:

1. Re-fetch the KG slice at `kg_version_hash` from operator-controlled
   storage. Confirm the SHA-256 matches.
2. Re-fetch the language model weights at `model_weight_hash` from
   operator-controlled storage. Confirm the SHA-256 matches.
3. Re-render the prompt from `(rule, kg_slice, telemetry,
   prompt_template_id)`. Compute the SHA-256 and compare to
   `prompt_template_hash`. The hashes MUST match.
4. Re-invoke the language model with `decoder_seed` and the structured
   grammar identified by `structured_grammar_hash`. Compare the
   resulting transcript to the recorded transcript using the receipt
   scheme's tolerance bounds (next section).
5. Re-run the Symbolic Verifier against the recorded
   `formalizable_assertions`. The result MUST match the recorded
   `verifier_result`.
6. Re-compute `entry_hash` from the recovered envelope and verify
   `entry_hash == previous_hash_{n+1}` (chain integrity).

### 8.2 Tolerance bounds

Bit-identical replay of a language model output is not guaranteed even
with identical inputs and seeds, due to floating-point non-associativity
on accelerated hardware. The receipt scheme MUST define a tolerance
bound that admits operationally-equivalent transcripts (e.g., the
CommitLLM commit-and-audit protocol's tolerance bound).

Replays that fall outside the receipt scheme's tolerance MUST be
treated as `REPLAY_DIVERGENCE` and reported by the replay tool. They
are not necessarily evidence of tampering; the operator MUST
investigate the cause.

### 8.3 v2.x entries

v2.x ledger entries do not carry `llm_transcript`, `model_provenance`,
or `verifier_result` and cannot be replayed by the v3 procedure. The
replay tool MUST emit a `SKIPPED_PRE_V3` notice for each such entry
and continue.

## 9. Conformance levels

The framework defines three executable conformance levels. An
implementation claiming a level MUST pass every test the conformance
suite defines for that level. Levels are cumulative: a Level 3
implementation MUST also satisfy Level 2 and Level 1.

### 9.1 Level 1 Foundational

A Level 1 implementation MUST:

- Implement the five-step runtime pipeline in [§2.2](#22-runtime-pipeline).
- Emit verdicts in the envelope structure in [§4](#4-verdict-envelope).
- Emit only the five verdicts in [§4.1](#41-the-five-verdict-taxonomy).
- Enforce sovereignty per [§6](#6-sovereignty) in strict mode.
- Persist verdicts to an append-only ledger per [§7](#7-audit-ledger-and-provenance).
- Sign and verify KGs per [§3.5](#35-signature-requirements).
- Include at least one typed obligation per rule per [§3.3](#33-typed-obligations).
- Expose the attestation endpoint per [§6.4](#64-attestation-endpoint).

### 9.2 Level 2 Managed

A Level 2 implementation MUST additionally:

- Maintain a neuro-symbolic agreement rate (per
  [§5.3](#53-the-symbolic-verifier)) above an operator-configurable
  threshold (default 99.5%).
- Resolve jurisdictional scope per
  [§3.4](#34-jurisdictional-scope-and-effective-date-intervals)
  across multi-jurisdiction KGs.
- Support v3 replay per [§8](#8-replay).
- Maintain a Coverage Register identifying telemetry subjects that
  receive `NULL_UNMAPPED` verdicts.
- Honour the risk-tier governor per [§5.4](#54-the-risk-tier-governor)
  for all three tiers.
- Emit telemetry buffer state per the v2.1 stateful-evaluation
  semantics (RFC 0001).

### 9.3 Level 3 Assured

A Level 3 implementation MUST additionally:

- Attach a verifiable inference receipt to every verdict per
  [§7.5](#75-verifiable-inference-receipts).
- Pass the SLSA attestation chain verification per
  [§6.4](#64-attestation-endpoint).
- Enforce human attestation tokens on `high` risk-tier rules.
- Resist a defined adversarial test corpus from the conformance
  suite (prompt injection via telemetry, KG poisoning, weight
  substitution).
- Provide cryptographic evidence of model-weight integrity at every
  verdict (the model_weight_hash MUST chain to a TPM-attested boot
  measurement or equivalent).

## 10. Security

This specification defers the threat model to
[docs/threat-model.md](threat-model.md). The threat model lists the
in-scope threats and the controls that mitigate each.

[RFC 0002 §Security implications](RFCs/0002-v3-neuro-symbolic-pivot.md)
documents v3-specific threats and how each is mitigated by the
provisions of this specification.

The following are not covered by this specification and are
operator responsibilities: physical security of the deployment host,
operating-system patch hygiene, deployment access control, audit log
storage and rotation, and breach notification.

## 11. Backwards compatibility

### 11.1 v2.x ledger entries

A v3 implementation MUST be able to read v2.x ledger entries. The
implementation MUST NOT attempt to replay v2.x entries through the
v3 replay procedure; the v2.x replay procedure (RFC 0001) MUST be
preserved as a separate code path.

### 11.2 v2.x Knowledge Graphs

A v3 implementation MUST accept v2.x KGs in a backwards-compatibility
mode for at least one minor version. v2.x KGs that omit typed
obligations MUST be treated as `DISCRETIONARY`-only and the absence of
typed obligations MUST be reported by `kg-validator --schema=v3
--suggest-upgrades`.

### 11.3 The `track` field on rules

The `track` field on a `Rule` is silently ignored by v3
implementations. For one minor version (v3.0 to v3.1), the
implementation MUST emit a deprecation log line on encountering
`track`. From v3.2 onward, the implementation MAY suppress the
deprecation log.

### 11.4 Dual-runtime period

For one minor version after the v3.0 release, the reference
implementation MUST ship both runtimes side by side, with
`SKI_RUNTIME_VERSION` selecting between them (default `v3`). After
the deprecation period, v2 may be removed.

## 12. Glossary

The framework's glossary lives in [docs/glossary.md](glossary.md). The
following terms are defined for this specification's normative use:

- **as_of** — the telemetry record's `timestamp` field; the
  authoritative clock for stateful evaluation.
- **canonical hash** — SHA-256 of the canonical serialization defined
  in [§7.3](#73-prompt-template-and-kg-canonical-hashing).
- **Coverage Register** — the registry of telemetry subjects that
  receive `NULL_UNMAPPED` verdicts.
- **fast path** — the optimization defined in
  [§5.6](#56-the-fast-path-optimization).
- **formalizable subset** — the subset of a rule's obligations whose
  predicates the Symbolic Verifier can evaluate mechanically.
- **KG slice** — the subset of the KG passed to the language model
  for a particular verdict request, per
  [§5.1](#51-kg-retrieval).
- **language model** — a large language model run within the
  sovereignty perimeter; the primary reasoner in v3.
- **neuro-symbolic agreement rate** — the rate at which the
  Symbolic Verifier's status is `AGREED` over the formalizable
  assertions in a fixed window.
- **risk tier** — `low`, `medium`, or `high`; governs how the
  implementation honours the language model's verdict given the
  verifier's findings.
- **sovereignty perimeter** — the deployment boundary defined by
  the operator's infrastructure; the boundary the framework
  refuses to cross during evaluation.
- **Symbolic Verifier** — the independent cross-check defined in
  [§5.3](#53-the-symbolic-verifier).
- **verdict envelope** — the structured object defined in
  [§4](#4-verdict-envelope).
- **verifiable provenance** — the property that every verdict's
  inputs and processing steps can be independently re-verified by
  a third party.

## 13. References

**Normative.**

- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels.
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words.
- RFC 3339 — Date and Time on the Internet: Timestamps.
- ECMA-262 — ECMAScript Language Specification, §7.1.12.1.

**Informative.**

- [RFC 0002 — SKI v3.0 Neuro-Symbolic Pivot](RFCs/0002-v3-neuro-symbolic-pivot.md)
  for the design rationale, alternatives considered, and rollout plan.
- [RFC 0001 — Stateful Evaluation and Deterministic Replay](RFCs/0001-stateful-evaluation.md)
  for the telemetry buffer and authoritative-clock semantics
  preserved in v3.
- [SKI Framework Specification v2.1](https://skiframework.org) for
  the prior released specification this document supersedes.
- [docs/threat-model.md](threat-model.md) for the threat model.
- [docs/governance.md](governance.md) for the governance and RFC
  process.
- CommitLLM — Verifiable execution for LLM inference.
- TensorCommitments — Lightweight verifiable inference for language
  models.
