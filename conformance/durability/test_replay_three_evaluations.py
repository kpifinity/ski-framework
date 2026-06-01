"""SKI Framework v3.0 § Axiom 2 — Replay determinism, live deployment.

Identical input must yield identical verdict across N runs against a
deployed runtime. The v3 LLM is non-deterministic at the model level;
the spec-normative claim is that ``decoder_seed`` plus the recorded
prompt template, KG version, and risk-tier policy must collapse the
output back to a deterministic envelope. This test posts the same
record three times against a live endpoint and asserts the verdict +
rule_id are stable.

Skips if no live deployment is provided (the static analogue is
``test_agreement_monitor.py``).
"""

from __future__ import annotations

import httpx
import pytest

_RECORD = {
    "telemetry_id": "conformance_determinism_001",
    "timestamp": "2026-05-22T10:00:00Z",
    "subject": "facility.so2.discharge_ppm",
    "measurement": {"so2_ppm": {"value": 85, "unit": "ppm"}},
}


@pytest.mark.durability
@pytest.mark.requires_live_deployment
def test_three_identical_evaluations_match(require_live: tuple[str, str], insecure: bool) -> None:
    endpoint, api_key = require_live
    headers = {"x-api-key": api_key, "content-type": "application/json"}

    verdicts: list[tuple[str, str | None]] = []
    with httpx.Client(verify=not insecure, timeout=30.0) as client:
        for _ in range(3):
            r = client.post(f"{endpoint.rstrip('/')}/api/evaluate", headers=headers, json=_RECORD)
            r.raise_for_status()
            data = r.json()
            verdicts.append((data.get("verdict"), data.get("rule_id")))

    first = verdicts[0]
    for i, v in enumerate(verdicts[1:], start=2):
        assert v == first, f"Run {i} produced {v}, expected {first} — non-determinism detected."
