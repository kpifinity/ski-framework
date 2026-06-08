"""SKI Framework v3.0 § Pillar S — Sovereignty boundary (no egress).

A sovereign deployment makes ZERO outbound HTTP calls during a CLEAR-path
evaluation: the default LLM backend is local/hermetic, network backends
are opt-in only, and an unknown backend name fails closed rather than
silently reaching the network. Black-box: we assert the backend factory
enforces that boundary by construction. The matching *functional* proof
— a full evaluation completing with all outbound sockets blocked — lives
in the runtime suite (``v3/tests/test_no_egress.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKENDS = ("reference-implementation", "src", "ski_model", "v3", "backends", "__init__.py")


@pytest.mark.sovereignty
def test_default_backend_is_local_and_hermetic(repo_root: Path) -> None:
    factory = (repo_root.joinpath(*BACKENDS)).read_text()
    assert 'getenv("SKI_V3_LLM_BACKEND", "fake")' in factory, (
        "default v3 LLM backend is not the hermetic 'fake' backend."
    )


@pytest.mark.sovereignty
def test_unknown_backend_fails_closed(repo_root: Path) -> None:
    factory = (repo_root.joinpath(*BACKENDS)).read_text()
    assert "raise" in factory and "is not a known v3 backend" in factory, (
        "backend factory does not fail closed on an unknown SKI_V3_LLM_BACKEND."
    )


@pytest.mark.sovereignty
def test_fake_backend_declares_no_network(repo_root: Path) -> None:
    evaluator = (
        repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "evaluator.py"
    ).read_text()
    fake = evaluator.split("class FakeLLM", 1)[1].split("class ", 1)[0]
    for net in ("import httpx", "import requests", "import socket", "aiohttp", "urllib.request"):
        assert net not in fake, f"FakeLLM (default backend) performs network I/O via {net!r}."
