"""SKI Framework v2.1 § B3.4 — Determinism Enforcement Controls (canary).

A Level 1 conformant implementation runs a determinism canary on a
fixed input and exposes its status. If the canary cannot exist (e.g.
backend missing), the test skips; if the backend is present and the
canary reports FAILED, the test fails.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.level1
def test_canary_module_present() -> None:
    from pathlib import Path

    canary = (
        Path(__file__).resolve().parents[2] / "reference-implementation" / "src" / "ski_model" / "canary.py"
    )
    assert canary.exists(), "canary.py is missing from the reference implementation."
    text = canary.read_text()
    assert "DeterminismCanary" in text, "DeterminismCanary class must be defined."
    assert "_FIXED_INPUT" in text, "Canary must compare against a fixed input."


@pytest.mark.level1
@pytest.mark.requires_live_deployment
def test_live_canary_endpoint(require_live: tuple[str, str], insecure: bool) -> None:
    endpoint, api_key = require_live
    with httpx.Client(verify=not insecure, timeout=10.0) as client:
        r = client.get(f"{endpoint.rstrip('/')}/api/canary", headers={"x-api-key": api_key})
        r.raise_for_status()
        data = r.json()
    assert "status" in data, "/api/canary must return a `status` field."
    assert "FAILED" not in str(data.get("status", "")).upper(), f"Determinism canary reports FAILED: {data}"
