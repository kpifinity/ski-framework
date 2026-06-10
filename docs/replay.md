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

## What gets skipped

- **Pre-v0.2 ledger entries.** Pre-buffer; we cannot reconstruct
  stateful evaluation. The report lists them under `notes`.
- **LLM-evaluated entries** are replayed as *provenance verification*
  (transcript signature + recorded hashes), not bit-identical
  re-generation — defensibility in v3 is reconstructible provenance,
  not replaying a rule engine. The symbolic-verifier results replay
  exactly.
- **Entries whose buffer row has been retention-dropped.** Hot retention
  is per-tenant; if the buffer no longer holds the row, replay can't
  reconstruct evaluation. Use longer retention windows when audit
  defence requires it.

## Failure modes and what they mean

| Mismatch reason | Meaning | What to do |
|---|---|---|
| `verdict_divergence` | Recorded verdict ≠ replayed verdict | Investigate; either the ledger has been tampered with, or your evaluator has a non-determinism bug |
| `tag_registry_divergence` | The current Tag Registry routes the subject to a different rule than was recorded | Expected after KG version bumps; supply the correct `--kg-path` for the entry's recorded `knowledge_graph_version` |

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
for the implementation. The replay logic shares the Symbolic Evaluator
and TelemetryBuffer with the runtime — there is no second
implementation that could drift from production.
