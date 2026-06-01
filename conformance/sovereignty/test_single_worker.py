"""SKI Framework v3.0 § Concurrency — Single-worker invariant.

The runtime must refuse to start with ``SKI_MODEL_WORKERS != 1``
because process-local state (agreement monitor, telemetry buffer,
verdicts counter) would otherwise diverge across workers.

Planned. Skipped pending the subprocess harness.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_runtime_refuses_multi_worker_startup() -> None:
    pytest.skip("L3 subprocess startup harness not yet implemented.")
