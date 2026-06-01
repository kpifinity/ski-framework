"""SKI Framework v3.0 §6 — Ledger tamper resistance.

Modify a ledger row in place, recompute the chain forward, and confirm
that ``verify_integrity`` STILL fails — proving entry-hash recomputation
catches the tamper, not just chain linkage.

Planned. Skipped pending a destructive-DB fixture.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_modified_ledger_row_fails_verify_integrity() -> None:
    pytest.skip("L3 destructive-DB tamper harness not yet implemented.")
