"""Canonical serialization used to compute the audit-ledger entry hash.

This module is duplicated (deliberately and exactly) between the
reference-implementation and the audit-ledger tool so that third parties
can re-verify the ledger using either codebase — or by reimplementing the
function from this docstring alone.

Algorithm
---------
1. Build a JSON object with the following keys in any order:
     sequence_number, previous_hash, timestamp, verdict, telemetry_id,
     telemetry_hash, rule_id, kg_version, ski_model_version, reasoning, track.
2. Serialise using:
     json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
3. Encode as UTF-8.
4. Hash with SHA-256.

`timestamp` is the ISO-8601 string with timezone offset, as written to the
database. `previous_hash` is the prior entry's entry_hash; for sequence 1
it is "0" * 64.
"""

from __future__ import annotations

import json
from typing import Optional


def canonical_entry_payload(
    *,
    sequence_number: int,
    previous_hash: str,
    timestamp_iso: str,
    verdict: str,
    telemetry_id: str,
    telemetry_hash: str,
    rule_id: Optional[str],
    kg_version: Optional[str],
    ski_model_version: str,
    reasoning: Optional[str],
    track: Optional[str],
) -> bytes:
    payload = {
        "sequence_number": sequence_number,
        "previous_hash": previous_hash,
        "timestamp": timestamp_iso,
        "verdict": verdict,
        "telemetry_id": telemetry_id,
        "telemetry_hash": telemetry_hash,
        "rule_id": rule_id,
        "kg_version": kg_version,
        "ski_model_version": ski_model_version,
        "reasoning": reasoning,
        "track": track,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
