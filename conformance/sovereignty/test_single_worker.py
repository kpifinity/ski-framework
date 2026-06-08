"""SKI Framework v3.0 § Concurrency — Single-worker invariant.

The runtime must refuse to start with ``SKI_MODEL_WORKERS != 1`` because
process-local state (agreement monitor, telemetry buffer, verdicts
counter) would otherwise diverge silently across workers and break the
audit guarantees. Black-box: we assert the guard is present in the
runtime entrypoint and that uvicorn is pinned to a single worker.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.sovereignty
def test_entrypoint_rejects_multi_worker(repo_root: Path) -> None:
    server = (repo_root / "reference-implementation" / "src" / "ski_model" / "server.py").read_text()
    assert "SKI_MODEL_WORKERS" in server, "server entrypoint does not read SKI_MODEL_WORKERS."
    assert "workers != 1" in server, "server entrypoint does not guard against SKI_MODEL_WORKERS != 1."
    assert "raise RuntimeError" in server, (
        "server entrypoint does not refuse (raise) on a multi-worker start."
    )


@pytest.mark.sovereignty
def test_uvicorn_pinned_to_single_worker(repo_root: Path) -> None:
    server = (repo_root / "reference-implementation" / "src" / "ski_model" / "server.py").read_text()
    assert "workers=1" in server, "uvicorn.run is not pinned to workers=1."
