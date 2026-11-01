#!/usr/bin/env python3
"""Regenerate the ledger entry-hash test vectors (formats 4 and 5).

Each vector gives the stored columns of one ledger entry, with the envelope
and transcript as the JSON *text* the database returns for them, and pins:

* ``envelope_hash`` / ``transcript_hash``: ``"sha256:"`` + SHA-256 of the
  §7.3 canonical form of that text, parsed as ``JSON.parse`` does;
* ``entry_payload``: the §7.3 canonical payload (UTF-8);
* ``entry_hash``: lowercase hex SHA-256 of ``entry_payload``;
* format 5 only (columns carry ``tenant_id``): ``verdict_signing_payload``,
  the canonical bytes the entry's ``verdict_signature`` signs.

Any implementation claiming conformance MUST reproduce all of them from
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

from ski_schemas.ledger import (  # noqa: E402
    LEDGER_SCHEMA_VERSION,
    entry_payload_v4,
    entry_payload_v5,
    evidence_hash,
    verdict_signing_bytes,
)

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
    """The values a conformant implementation computes from ``columns``."""
    envelope_hash = evidence_hash(columns["envelope_json"])
    transcript_hash = evidence_hash(columns["transcript_json"])
    common: Dict[str, Any] = {
        "sequence_number": columns["sequence_number"],
        "previous_hash": columns["previous_hash"],
        "timestamp_iso": columns["timestamp"],
        "verdict": columns["verdict"],
        "telemetry_id": columns["telemetry_id"],
        "telemetry_hash": columns["telemetry_hash"],
        "rule_id": columns["rule_id"],
        "kg_version": columns["knowledge_graph_version"],
        "ski_model_version": columns["ski_model_version"],
        "reasoning": columns["reasoning"],
        "track": columns["track"],
        "envelope_hash": envelope_hash,
        "transcript_hash": transcript_hash,
        "transcript_signature": columns["transcript_signature"],
        "signing_key_id": columns["signing_key_id"],
        "verifier_status": columns["verifier_status"],
    }
    if "tenant_id" not in columns:
        payload = entry_payload_v4(**common)
        return {
            "envelope_hash": envelope_hash,
            "transcript_hash": transcript_hash,
            "entry_payload": payload.decode("utf-8"),
            "entry_hash": hashlib.sha256(payload).hexdigest(),
        }
    payload = entry_payload_v5(
        **common,
        tenant_id=columns["tenant_id"],
        kg_version_hash=columns["kg_version_hash"],
        model_weight_hash=columns["model_weight_hash"],
        schema_version=columns["schema_version"],
    )
    entry_hash = hashlib.sha256(payload).hexdigest()
    return {
        "envelope_hash": envelope_hash,
        "transcript_hash": transcript_hash,
        "entry_payload": payload.decode("utf-8"),
        "entry_hash": entry_hash,
        "verdict_signing_payload": verdict_signing_bytes(
            sequence_number=columns["sequence_number"],
            entry_hash=entry_hash,
            telemetry_id=columns["telemetry_id"],
            transcript_id=columns["transcript_id"],
        ).decode("utf-8"),
    }


def _v5(**overrides: Any) -> Dict[str, Any]:
    v5: Dict[str, Any] = {
        "tenant_id": "default",
        "kg_version_hash": "sha256:" + "1" * 64,
        "model_weight_hash": "sha256:" + "2" * 64,
        "schema_version": LEDGER_SCHEMA_VERSION,
        "transcript_id": "transcript:0001",
    }
    return _columns(**{**v5, **overrides})


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
    "v5_entry_with_transcript": (
        "A v5 evaluator entry: v4 plus the spec §7.1 columns, and its verdict-signature payload.",
        _v5(),
    ),
    "v5_entry_without_transcript": (
        "A v5 entry with no transcript (clock-skew guard path): transcript_id is null in the signed payload.",
        _v5(
            verdict="DISCRETIONARY",
            rule_id=None,
            track="v3-clock-skew-guard",
            transcript_json=None,
            transcript_signature=None,
            signing_key_id=None,
            verifier_status="UNVERIFIABLE",
            model_weight_hash=None,
            transcript_id=None,
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
