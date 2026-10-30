#!/usr/bin/env python3
"""Regenerate the ledger-v4 entry-hash test vectors.

Each vector gives the stored columns of one ledger entry, with the envelope
and transcript as the JSON *text* the database returns for them, and pins:

* ``envelope_hash`` / ``transcript_hash``: ``"sha256:"`` + SHA-256 of the
  §7.3 canonical form of that text, parsed as ``JSON.parse`` does;
* ``entry_payload``: the §7.3 canonical v4 payload (UTF-8);
* ``entry_hash``: lowercase hex SHA-256 of ``entry_payload``.

Any implementation claiming conformance MUST reproduce all four from
``columns``. ``ski_schemas.ledger`` documents the payload. Run
``python generate.py`` to rewrite the files; the drift check re-derives them.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ski-schemas" / "src"))

from ski_schemas.ledger import entry_payload_v4, evidence_hash  # noqa: E402

_OUT = Path(__file__).resolve().parent

# Stored as JSONB, ``85.0`` reads back as ``85.0`` and ``1e+300`` as a
# 301-digit integer literal; both must hash as the same double they were.
_ENVELOPE_TEXT = (
    '{"verdict": "FLAG", "reasoning": "SO2 above cap.", "kg_citations": ["energy.so2.cap"], '
    '"formalizable_assertions": [{"metric": "so2_ppm", "observed": 142.5, "predicate": '
    '"must_not_exceed", "satisfied": false, "value": 100.0, "window_seconds": null}, '
    '{"metric": "flow", "observed": 1' + "0" * 300 + ', "predicate": "must_not_exceed", '
    '"satisfied": false, "value": 85.0, "window_seconds": null}], '
    '"verifier_result": {"status": "AGREED", "checked_assertions": 2, "divergences": []}}'
)

_TRANSCRIPT_TEXT = (
    '{"transcript_id": "transcript:0001", "request_hash": "sha256:' + "a" * 64 + '", '
    '"response_hash": "sha256:' + "b" * 64 + '", "signature_hex": "' + "c" * 128 + '", '
    '"signing_key_id": "sha256:' + "d" * 64 + '", "backend_name": "fake-llm"}'
)


def _columns(**overrides: Any) -> Dict[str, Any]:
    columns: Dict[str, Any] = {
        "sequence_number": 7,
        "previous_hash": "e" * 64,
        "timestamp": "2026-10-30T12:00:00.123456+00:00",
        "verdict": "FLAG",
        "telemetry_id": "meas-0007",
        "telemetry_hash": "f" * 64,
        "rule_id": "energy.so2.cap",
        "knowledge_graph_version": "kg-2026.10",
        "ski_model_version": "3.2.0",
        "reasoning": "SO2 above cap.",
        "track": "v3-evaluator",
        "envelope_json": _ENVELOPE_TEXT,
        "transcript_json": _TRANSCRIPT_TEXT,
        "transcript_signature": "c" * 128,
        "signing_key_id": "sha256:" + "d" * 64,
        "verifier_status": "AGREED",
    }
    columns.update(overrides)
    return columns


def derive(columns: Dict[str, Any]) -> Dict[str, Any]:
    """The four values a conformant implementation computes from ``columns``."""
    envelope_hash = evidence_hash(columns["envelope_json"])
    transcript_hash = evidence_hash(columns["transcript_json"])
    payload = entry_payload_v4(
        sequence_number=columns["sequence_number"],
        previous_hash=columns["previous_hash"],
        timestamp_iso=columns["timestamp"],
        verdict=columns["verdict"],
        telemetry_id=columns["telemetry_id"],
        telemetry_hash=columns["telemetry_hash"],
        rule_id=columns["rule_id"],
        kg_version=columns["knowledge_graph_version"],
        ski_model_version=columns["ski_model_version"],
        reasoning=columns["reasoning"],
        track=columns["track"],
        envelope_hash=envelope_hash,
        transcript_hash=transcript_hash,
        transcript_signature=columns["transcript_signature"],
        signing_key_id=columns["signing_key_id"],
        verifier_status=columns["verifier_status"],
    )
    return {
        "envelope_hash": envelope_hash,
        "transcript_hash": transcript_hash,
        "entry_payload": payload.decode("utf-8"),
        "entry_hash": hashlib.sha256(payload).hexdigest(),
    }


VECTORS = {
    "v4_entry_with_transcript": (
        "A v4 evaluator entry: envelope and signed transcript, with JSONB-spelled numbers.",
        _columns(),
    ),
    "v4_entry_without_transcript": (
        "A v4 entry with no transcript (the clock-skew guard path): null transcript fields.",
        _columns(
            verdict="DISCRETIONARY",
            rule_id=None,
            track="v3-clock-skew-guard",
            transcript_json=None,
            transcript_signature=None,
            signing_key_id=None,
            verifier_status="UNVERIFIABLE",
        ),
    ),
}


def main() -> int:
    for name, (description, columns) in VECTORS.items():
        vector = {"name": name, "description": description, "columns": columns, **derive(columns)}
        (_OUT / f"{name}.json").write_text(
            json.dumps(vector, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
