"""SKI Framework v3.0 § Axiom 2 — Replay determinism, live deployment.

Identical input must yield identical verdict across N runs against a
deployed runtime. The v3 LLM is non-deterministic at the model level;
the spec-normative claim is that ``decoder_seed`` plus the recorded
prompt template, KG version, and risk-tier policy must collapse the
output back to a deterministic envelope. This test posts the same
record three times against a live endpoint and asserts that the verdict,
the KG citations and the model provenance are stable.

The record carries a CURRENT timestamp, and every response is checked
to come from a real evaluation: up to v3.1.x the test sent a fixed
2026-05-22 timestamp (and ``telemetry_id``, which the API rejects with
422), so the clock-skew guard short-circuited every run to the same
DISCRETIONARY envelope and the test passed without evaluating anything.

Skips if no live deployment is provided (the static analogue is
``test_agreement_monitor.py``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

# Markers of the clock-skew short-circuit envelope (server.py
# ``_build_clock_skew_envelope``): no LLM ran, so it proves nothing about
# replay determinism.
_SKEW_GUARD_TEMPLATE_ID = "ski.v3.clock-skew-guard"
_SKEW_GUARD_TRANSCRIPT_REF = "transcript:none-clock-skew-guard"


def _record() -> dict[str, Any]:
    # One timestamp for all three runs (identical input), taken now so it
    # sits inside the runtime's max_clock_skew_seconds bound (default 60 s).
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "measurement_id": "conformance_determinism_001",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "subject": "facility.so2.discharge_ppm",
        "measurement": {"so2_ppm": {"value": 85, "unit": "ppm"}},
    }


def _short_circuited_by_skew_guard(envelope: dict[str, Any]) -> bool:
    provenance = envelope.get("model_provenance") or {}
    notes = envelope.get("notes") or []
    return (
        provenance.get("prompt_template_id") == _SKEW_GUARD_TEMPLATE_ID
        or envelope.get("transcript_ref") == _SKEW_GUARD_TRANSCRIPT_REF
        or any(isinstance(note, str) and note.startswith("clock_skew:") for note in notes)
    )


def _replay_key(envelope: dict[str, Any]) -> str:
    """What must be identical across runs: verdict, KG citations, provenance."""
    return json.dumps(
        {
            "verdict": envelope.get("verdict"),
            "kg_citations": envelope.get("kg_citations"),
            "model_provenance": envelope.get("model_provenance"),
        },
        sort_keys=True,
    )


@pytest.mark.durability
@pytest.mark.requires_live_deployment
def test_three_identical_evaluations_match(require_live: tuple[str, str], insecure: bool) -> None:
    endpoint, api_key = require_live
    headers = {"x-api-key": api_key, "content-type": "application/json"}
    record = _record()

    envelopes: list[dict[str, Any]] = []
    with httpx.Client(verify=not insecure, timeout=30.0) as client:
        for _ in range(3):
            r = client.post(f"{endpoint.rstrip('/')}/api/evaluate", headers=headers, json=record)
            r.raise_for_status()
            envelopes.append(r.json())

    for i, envelope in enumerate(envelopes, start=1):
        assert not _short_circuited_by_skew_guard(envelope), (
            f"Run {i} was short-circuited by the clock-skew guard (notes={envelope.get('notes')}), "
            "so it evaluated nothing. The record is stamped at test start; if the runs together "
            "take longer than the deployment's max_clock_skew_seconds, the bound is too tight "
            "for this backend's latency."
        )

    first = _replay_key(envelopes[0])
    for i, envelope in enumerate(envelopes[1:], start=2):
        assert _replay_key(envelope) == first, (
            f"Run {i} produced {_replay_key(envelope)}, expected {first} — non-determinism detected."
        )
