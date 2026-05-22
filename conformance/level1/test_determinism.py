"""SKI Framework v2.1 § Axiom 2 + B3.4 — Determinism.

Identical input must yield identical verdict across N runs. This test
sends the same telemetry record three times and asserts the verdict
plus rule_id are stable.

Skips if no live deployment is provided (the static analogue is
test_canary_active.py).
"""

from __future__ import annotations

import pytest
import httpx


_RECORD = {
    "telemetry_id": "conformance_determinism_001",
    "timestamp": "2026-05-22T10:00:00Z",
    "subject": "facility.so2.discharge_ppm",
    "measurement": {"so2_ppm": {"value": 85, "unit": "ppm"}},
}


@pytest.mark.level1
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
