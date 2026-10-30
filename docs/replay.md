# Deterministic replay

> **Status:** runnable today (`audit-ledger replay`). In v3 the replay
> primitive is one half of the defensibility story; the other half is
> per-verdict **verifiable provenance** — the signed LLM transcript and
> envelope recorded in the ledger, re-verifiable offline with
> `ski-sdk`'s `verify_transcript()`.

Replay re-evaluates a contiguous range of audit ledger entries against
the recorded Knowledge Graph and the telemetry buffer state as it
existed at each entry's timestamp. The replayed verdict is compared to
the originally-recorded verdict, and any divergence is reported.

## Why this exists

1. **Audit defence.** A regulator asks "show me your evaluation of
   record `tel_e_0042` from 2026-05-22 14:32:07." You can produce the
   ledger row and, with replay, demonstrate that re-running the same
   inputs through the same KG yields the same verdict. That's
   determinism by demonstration, not by assertion.
2. **Tamper detection.** If a row in the ledger has been silently
   modified, the replayed verdict will disagree with the recorded
   verdict — and the canonical entry-hash check (Durability conformance)
   will independently catch the modification.
3. **Durability conformance.** The Durability suite uses replay as a
   black-box test (`durability/test_replay_three_evaluations.py`).

## Usage

```bash
audit-ledger replay \
  --source "postgresql://user:pw@db/ledger" \
  --from-sequence 1000 \
  --to-sequence  1500 \
  --kg-path /etc/ski/energy-kg-v1.2-signed.json \
  --tenant-id default \
  --output replay-report.json
```

Exit code:

- `0` — every replayable entry matched.
- `1` — at least one divergence (unless `--no-strict` is passed).

## What gets replayed

Every entry the language model evaluated (it has a stored envelope and a
signed transcript). For each one, replay:

1. recovers the exact measurement and scoped KG snapshot the model was
   given from the transcript's canonical prompt;
2. finds the telemetry buffer row by `telemetry_hash` and checks it holds
   that measurement;
3. checks `--kg-path` reproduces the recorded `kg_version_hash` and,
   scoped as recorded, the same obligations;
4. re-runs the runtime's own evaluator with the model call replaced by the
   recorded response, with the same risk tier, subject, telemetry time and
   buffer, and compares the verdict and verifier status.

The model output itself is not regenerated (spec §8.2: model replay is
judged by tolerance bounds); everything downstream of it (citation checks,
the Symbolic Verifier, the freshness gate, the risk-tier policy) replays
exactly.

## What gets skipped

- **Entries without a stored envelope** (pre-v3). Listed under `notes`.
- **Entries without a transcript**: the model never saw them (the
  clock-skew guard routes those to DISCRETIONARY without evaluating).

## Failure modes and what they mean

| Mismatch reason | Meaning | What to do |
|---|---|---|
| `verdict_divergence` | Replay gives a different verdict or verifier status | Investigate: the ledger was tampered with, or the evaluator is non-deterministic |
| `kg_version_mismatch` | `--kg-path` does not hash to the entry's recorded `kg_version_hash` | Supply the KG that was active when the entry was written |
| `kg_snapshot_divergence` | The KG, scoped as recorded, gives different obligations than the transcript shows | The transcript or the KG does not match what was evaluated |
| `telemetry_divergence` | The buffer row for `telemetry_hash` holds a different measurement than the transcript | The buffer or the transcript was altered |
| `buffer_row_missing` | No buffer row has the entry's `telemetry_hash` | Retention dropped it, or the buffer was not provisioned when the entry was written |
| `transcript_unreadable` | The transcript's prompt does not have the expected sections | Investigate the transcript |

## Report format

```json
{
  "started_at": "2026-05-22T14:00:00+00:00",
  "finished_at": "2026-05-22T14:00:03+00:00",
  "from_sequence": 1000,
  "to_sequence": 1500,
  "total_entries": 500,
  "replayed_entries": 462,
  "matched_entries": 462,
  "skipped_entries": 38,
  "is_clean": true,
  "mismatches": [],
  "notes": [
    "seq=1012: Track 2 (LLM) entry — replay is best-effort only; skipped.",  // legacy v0.2 entry
    ...
  ]
}
```

A clean replay (`is_clean: true`) is the signed artefact you attach to a
regulatory submission. KpiFinity's Level 3 Assured audit replays a
randomly-sampled subset of ledger entries during certification.

## Implementation notes

See [docs/RFCs/0001-stateful-evaluation.md](./RFCs/0001-stateful-evaluation.md)
for the architectural rationale, and
[tools/audit-ledger/src/audit_ledger/replay.py](../tools/audit-ledger/src/audit_ledger/replay.py)
for the implementation. Replay runs the runtime's own `V3Evaluator`,
`SymbolicVerifier` and `TelemetryBuffer` — there is no second
implementation that could drift from production.
