"""SKI Framework v3.0 §4.7 — End-to-end signed LLM transcript.

Every ``LLMTranscript`` is ed25519-signed over ``request_hash || "|" ||
response_hash`` by the runtime's own key, and a standalone
``verify_signature`` lets an auditor confirm it. Black-box: we assert the
signing primitive, the signed message construction, and that the
evaluator signs the transcript. The *functional* sign -> verify -> tamper
proof lives in the runtime suite (``v3/tests/test_signing.py`` and
``test_transcript.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

V3 = ("reference-implementation", "src", "ski_model", "v3")


@pytest.mark.sovereignty
def test_transcript_is_signed_over_the_hash_pair(repo_root: Path) -> None:
    transcript = (repo_root.joinpath(*V3, "transcript.py")).read_text()
    assert "def signing_message" in transcript, "no signing_message() defining the signed bytes."
    body = transcript.split("def signing_message", 1)[1].split("class ", 1)[0]
    assert "request_hash" in body and "response_hash" in body, (
        "the signed message is not the request_hash|response_hash pair."
    )


@pytest.mark.sovereignty
def test_signing_uses_ed25519_and_exposes_verify(repo_root: Path) -> None:
    signing = (repo_root.joinpath(*V3, "signing.py")).read_text()
    assert "Ed25519" in signing, "transcript signing is not ed25519."
    assert "def verify_signature" in signing, (
        "no standalone verify_signature() for auditors to verify a recorded transcript."
    )


@pytest.mark.sovereignty
def test_evaluator_signs_the_transcript(repo_root: Path) -> None:
    evaluator = (repo_root.joinpath(*V3, "evaluator.py")).read_text()
    assert ".sign(" in evaluator and "signature_hex" in evaluator, (
        "the evaluator does not sign the transcript it emits."
    )
