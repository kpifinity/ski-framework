"""SKI Framework v3.0 § Pillar S — Air-gapped operability.

The runtime must boot, accept evaluations, and persist to the ledger
in a process with no network access at all. This test will spin a
container with ``--network=none`` and replay a fixed conformance
workload.

Planned. Skipped pending the containerised harness.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_runtime_boots_with_no_network() -> None:
    pytest.skip("L3 air-gapped container harness not yet implemented.")
