"""SKI Framework v3.0 § Pillar S — Sovereignty boundary.

A sovereign deployment makes ZERO outbound HTTP calls during a CLEAR-
path evaluation when the LLM backend is local (Ollama, llama.cpp). This
test will harness ``pytest-httpx`` to assert that no unmocked transport
is touched during ``/api/evaluate``.

Planned. Skipped pending the network-sandbox harness.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_runtime_makes_no_outbound_http_in_clear_path() -> None:
    pytest.skip("L3 network-sandbox harness not yet implemented — tracked in CONFORMANCE.md.")
