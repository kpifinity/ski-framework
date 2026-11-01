# ISO/IEC 24970 (AI system logging) crosswalk

> **License:** CC BY 4.0. See [LICENSE-docs.md](../../LICENSE-docs.md).
>
> **Status: provisional and informative.** ISO/IEC 24970, *Artificial
> intelligence — AI system logging* (JTC 1/SC 42), is at the Final Draft
> (FDIS) stage. Its information model is in the paid draft text, which this
> mapping was **not** prepared against. The left column below uses the
> logging elements the standard's published scope and the EU AI Act
> (Article 12, which it is expected to support) describe, not the
> standard's own element names. When the text is published, replace the
> left column with its normative element identifiers; the SKI side will not
> need to change.

## Scope

ISO/IEC 24970's published scope is shared capabilities, requirements and an
**information model for recording events in AI systems**, used together
with a risk management system. SKI's audit ledger is such a record for
every compliance verdict: append-only at the storage layer (spec §7.2),
hash-chained and checkpointed (§7.1), and re-verifiable by replay (§8.1).

## Field-level correspondence

| AI event-logging element (provisional) | SKI ledger / evidence field | Integrity |
|---|---|---|
| Event identifier | `sequence_number` (per tenant), `entry_hash` | chained (`previous_hash`), signed (`verdict_signature`) |
| Event time | `timestamp` (verdict production) | in `entry_hash`; monotonic order verified |
| Recording system identity | `tenant_id`; runtime key id (`verdict_signing_key_id`) | `tenant_id` chained (format 5); key pinned by auditor |
| AI system / version | `ski_model_version`; image digest and commit (`/api/sovereignty`) | attested, signed |
| Model identity and version | `model_weight_hash`; envelope `model_provenance` (backend, `model_id`) | chained; weights verified at boot, OMS-signed origin |
| Input reference | `telemetry_id`, `telemetry_hash` (the measurement in the telemetry buffer) | chained; replay joins it to the buffer row |
| Reference data / rules applied | `kg_version_hash`, `rule_id`, envelope `kg_citations` | chained; KG signed by a pinned anchor |
| Output / decision | `verdict` (five-verdict taxonomy, spec §4.1), envelope `reasoning` | chained |
| Automated verification of the output | `verifier_status`, envelope `verifier_result` | chained |
| Model interaction record | signed transcript (`transcript_json`, `transcript_signature`) | chained by digest; signature verified on replay |
| Human oversight / escalation | `DISCRETIONARY` verdicts, envelope `human_attestation`, `escalation_status` | verdict and envelope chained |
| Logging format version | `schema_version` (`3.0.0`), ledger format (`ledger_format` in the hashed payload) | chained |
| Tamper evidence | hash chain, verdict signatures, signed Merkle checkpoints, optional RFC 3161 time-stamps | `audit-ledger verify` |
| Log export and retention | `audit-ledger export`, `checkpoint export` (WORM), `backup` | exported checkpoints verify the ledger later |
| Interoperable event form | SCITT signed statement + receipt, TRACE record per entry ([standards](../standards.md)) | signed; receipts prove inclusion |

## Gaps to confirm against the final text

- **Event types beyond verdicts.** SKI logs each compliance decision. Runtime
  lifecycle events (start, configuration, KG load) are in the structured
  application log and the signed `/api/sovereignty` attestation, not in the
  ledger. If ISO/IEC 24970 requires them in the same log, they need a ledger
  track of their own.
- **Retention periods** are operator policy (telemetry-buffer partitions,
  backups); SKI enforces none itself.
- **Element names and cardinality** of the information model: to be checked
  against the published standard.
