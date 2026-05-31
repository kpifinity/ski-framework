"""Tests for the v3 transcript signing keypair lifecycle (spec §6.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ski_model.v3 import TranscriptSigner, verify_signature
from ski_model.v3.transcript import signing_message


class TestAutoProvisioning:
    def test_generates_keypair_on_first_run(self, tmp_path: Path) -> None:
        key_path = tmp_path / "transcript.ed25519"
        signer = TranscriptSigner.auto_provision(key_path)
        assert key_path.exists()
        assert (tmp_path / "transcript.ed25519.pub").exists()
        assert signer.key_id.startswith("sha256:")

    def test_reuses_existing_key_on_restart(self, tmp_path: Path) -> None:
        key_path = tmp_path / "transcript.ed25519"
        first = TranscriptSigner.auto_provision(key_path)
        second = TranscriptSigner.auto_provision(key_path)
        assert first.key_id == second.key_id

    def test_uses_env_path_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = tmp_path / "custom.ed25519"
        monkeypatch.setenv("SKI_TRANSCRIPT_KEY_PATH", str(custom))
        signer = TranscriptSigner.auto_provision()
        assert custom.exists()
        assert signer.key_id.startswith("sha256:")

    def test_private_key_is_mode_600_on_posix(self, tmp_path: Path) -> None:
        if os.name != "posix":
            pytest.skip("POSIX file mode check")
        key_path = tmp_path / "transcript.ed25519"
        TranscriptSigner.auto_provision(key_path)
        mode = key_path.stat().st_mode & 0o777
        assert mode == 0o600, f"private key file mode should be 0600, got {oct(mode)}"


class TestSignVerify:
    def test_sign_then_verify_roundtrip(self, tmp_path: Path) -> None:
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        message = signing_message(request_hash="sha256:" + "a" * 64, response_hash="sha256:" + "b" * 64)
        signature = signer.sign(message)
        assert verify_signature(
            public_key_pem=signer.public_key_pem,
            message=message,
            signature_hex=signature,
        )

    def test_tampered_message_fails_verification(self, tmp_path: Path) -> None:
        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        message = signing_message(request_hash="sha256:" + "a" * 64, response_hash="sha256:" + "b" * 64)
        signature = signer.sign(message)
        tampered = signing_message(request_hash="sha256:" + "a" * 64, response_hash="sha256:" + "c" * 64)
        assert not verify_signature(
            public_key_pem=signer.public_key_pem,
            message=tampered,
            signature_hex=signature,
        )

    def test_different_signer_cannot_verify(self, tmp_path: Path) -> None:
        signer_a = TranscriptSigner.auto_provision(tmp_path / "a.ed25519")
        signer_b = TranscriptSigner.auto_provision(tmp_path / "b.ed25519")
        message = signing_message(request_hash="sha256:" + "1" * 64, response_hash="sha256:" + "2" * 64)
        signature = signer_a.sign(message)
        assert not verify_signature(
            public_key_pem=signer_b.public_key_pem,
            message=message,
            signature_hex=signature,
        )

    def test_two_signers_have_distinct_key_ids(self, tmp_path: Path) -> None:
        signer_a = TranscriptSigner.auto_provision(tmp_path / "a.ed25519")
        signer_b = TranscriptSigner.auto_provision(tmp_path / "b.ed25519")
        assert signer_a.key_id != signer_b.key_id
