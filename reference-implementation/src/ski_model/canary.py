"""Determinism canary.

Periodically re-runs a fixed, well-known input against the inference backend
and verifies that the output is identical to the first call. A divergence
flips the canary status to FAILED, which is exported via /api/canary and
Prometheus `ski_canary_status`.

This is one of the v2.1 B3.4 Determinism Enforcement Controls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


_FIXED_INPUT: dict[str, Any] = {
    "telemetry_id": "canary_fixed_001",
    "timestamp": "2026-01-01T00:00:00Z",
    "subject": "_canary",
    "measurement": {"value": 42, "unit": "ppm"},
}


class DeterminismCanary:
    def __init__(self, backend: Any, interval_seconds: int):
        self._backend = backend
        self._interval = interval_seconds
        self._baseline: Optional[dict[str, Any]] = None
        self.last_status: str = "pending"
        self.last_checked: Optional[str] = None
        self.failures: int = 0

    async def run(self) -> None:
        try:
            self._baseline = await self._backend.canary_eval(_FIXED_INPUT)
            self.last_status = "baseline_recorded"
            logger.info("Canary baseline recorded.")
        except Exception as exc:  # pragma: no cover — backend might not be up
            logger.warning("Canary baseline failed: %s", exc)
            self.last_status = "backend_unavailable"

        while True:
            await asyncio.sleep(self._interval)
            await self._check()

    async def _check(self) -> None:
        if self._baseline is None:
            try:
                self._baseline = await self._backend.canary_eval(_FIXED_INPUT)
                self.last_status = "baseline_recorded"
            except Exception as exc:
                self.last_status = f"backend_error: {exc}"
            return

        try:
            current = await self._backend.canary_eval(_FIXED_INPUT)
        except Exception as exc:
            self.last_status = f"backend_error: {exc}"
            return

        self.last_checked = datetime.now(timezone.utc).isoformat()
        if current == self._baseline:
            self.last_status = "ok"
        else:
            self.failures += 1
            self.last_status = "FAILED — non-determinism detected"
            logger.error("Determinism canary FAILED. baseline=%s current=%s", self._baseline, current)

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.last_status,
            "last_checked": self.last_checked,
            "failures": self.failures,
            "interval_seconds": self._interval,
        }
