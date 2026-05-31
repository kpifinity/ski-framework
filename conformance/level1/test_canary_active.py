"""SKI Framework v3.0 §7.2 — Neuro-symbolic agreement monitor.

A Level 1 conformant v3 implementation runs a continuous LLM↔verifier
agreement-rate monitor and exposes its snapshot. The v2 ``DeterminismCanary``
(periodic fixed-input replay against the LLM backend) is gone; PR 12
replaced it with the on-evaluation :class:`AgreementMonitor` which tracks
how often the LLM and the symbolic verifier agree.

This test asserts the runtime ships the new monitor module and exposes
the expected snapshot keys.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

_EXPECTED_SNAPSHOT_KEYS = {
    "window_size",
    "threshold",
    "observed",
    "counts",
    "agreement_rate",
    "is_healthy",
}


@pytest.mark.level1
def test_agreement_monitor_module_present() -> None:
    """The v3 runtime must ship the agreement-monitor module per spec §7.2."""
    monitor = (
        Path(__file__).resolve().parents[2]
        / "reference-implementation"
        / "src"
        / "ski_model"
        / "v3"
        / "agreement_monitor.py"
    )
    assert monitor.exists(), "v3/agreement_monitor.py is missing from the reference implementation."
    text = monitor.read_text()
    assert "class AgreementMonitor" in text, "AgreementMonitor class must be defined."
    assert "agreement_rate" in text, "Monitor must expose an agreement_rate."
    assert "is_healthy" in text, "Monitor must expose an is_healthy signal."


@pytest.mark.level1
def test_legacy_canary_module_is_removed() -> None:
    """The v2 ``canary.py`` and ``backends.py`` modules must be gone.

    PR 12 deleted both. This guard fails if either reappears, catching
    accidental reverts of the v2 monitor path.
    """
    repo_root = Path(__file__).resolve().parents[2]
    canary = repo_root / "reference-implementation" / "src" / "ski_model" / "canary.py"
    backends = repo_root / "reference-implementation" / "src" / "ski_model" / "backends.py"
    assert not canary.exists(), (
        "Legacy ski_model/canary.py still present. PR 12 replaced it with "
        "ski_model.v3.agreement_monitor.AgreementMonitor."
    )
    assert not backends.exists(), (
        "Legacy ski_model/backends.py still present. PR 12 removed it; v3 "
        "backends live under ski_model.v3.backends."
    )


@pytest.mark.level1
@pytest.mark.requires_live_deployment
def test_live_agreement_monitor_endpoint(require_live: tuple[str, str], insecure: bool) -> None:
    """``/api/canary`` returns the agreement-monitor snapshot (path preserved)."""
    endpoint, api_key = require_live
    with httpx.Client(verify=not insecure, timeout=10.0) as client:
        r = client.get(f"{endpoint.rstrip('/')}/api/canary", headers={"x-api-key": api_key})
        r.raise_for_status()
        data = r.json()
    # Either the monitor is fully populated or the server is reporting
    # not_started (no evaluations yet). Both shapes are conformant.
    if data.get("status") == "not_started":
        return
    missing = _EXPECTED_SNAPSHOT_KEYS - set(data.keys())
    assert not missing, f"/api/canary missing snapshot keys: {sorted(missing)!r}."
    assert "FAILED" not in str(data.get("status", "")).upper(), f"Agreement monitor reports failure: {data}"
