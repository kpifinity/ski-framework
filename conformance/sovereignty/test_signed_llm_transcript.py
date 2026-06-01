"""SKI Framework v3.0 §4.7 — End-to-end signed LLM transcript.

The runtime must sign every ``LLMTranscript`` with an ed25519 key so
that an auditor can verify the transcript came from the SKI Model
process that produced the envelope. PR 11 wired the signer; this L3
test will verify the signature on a transcript pulled from a live
ledger.

Planned. Skipped pending a live-deployment harness.
"""

from __future__ import annotations

import pytest


@pytest.mark.sovereignty
def test_recorded_transcript_signature_verifies() -> None:
    pytest.skip("L3 transcript-signature harness not yet implemented.")
