"""SKI Framework v3.0 §3.6 + §6 — Jurisdiction scope captured in ledger.

PR 11.7 added ``KnowledgeGraph.scope_to(jurisdiction, as_of)`` which
emits a ``scope`` block (jurisdiction, as_of, n_in, n_out) on every
snapshot. For sovereignty conformance, the recorded LLM transcript
must include this scope block so an auditor in jurisdiction X can
confirm the runtime sent ONLY X-applicable obligations to the LLM.

Planned. Skipped pending a live-deployment harness that inspects a
ledger row's transcript.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_recorded_transcript_carries_jurisdiction_scope() -> None:
    pytest.skip("L3 transcript-inspection harness not yet implemented.")
