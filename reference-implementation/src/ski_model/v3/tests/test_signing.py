"""Tests for the v3 transcript signing keypair lifecycle (spec §6.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ski_model.v3 import TranscriptSigner, verify_signature
from ski_model.v3.signing import TranscriptKeyError, transcript_key_path
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


class TestKeyGenerationGuard:
    """Framework v3.2.0: no silent key regeneration (C6)."""

    @pytest.fixture(autouse=True)
    def _generation_not_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_ALLOW_KEY_GENERATION", raising=False)

    def test_missing_key_without_opt_in_refuses(self, tmp_path: Path) -> None:
        key_path = tmp_path / "keys" / "transcript.ed25519"
        with pytest.raises(TranscriptKeyError, match="SKI_ALLOW_KEY_GENERATION=true"):
            TranscriptSigner.auto_provision(key_path)
        assert not key_path.exists()

    def test_env_opt_in_generates_on_first_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SKI_ALLOW_KEY_GENERATION", "true")
        key_path = tmp_path / "keys" / "transcript.ed25519"
        signer = TranscriptSigner.auto_provision(key_path)
        assert key_path.exists()
        assert signer.key_id.startswith("sha256:")

    def test_explicit_parameter_overrides_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_ALLOW_KEY_GENERATION", "true")
        with pytest.raises(TranscriptKeyError):
            TranscriptSigner.auto_provision(tmp_path / "a.ed25519", allow_generation=False)
        assert TranscriptSigner.auto_provision(tmp_path / "b.ed25519", allow_generation=True).key_id

    def test_missing_key_with_signed_ledger_refuses_even_with_opt_in(self, tmp_path: Path) -> None:
        key_path = tmp_path / "transcript.ed25519"
        with pytest.raises(TranscriptKeyError, match="already holds signed transcripts"):
            TranscriptSigner.auto_provision(
                key_path, allow_generation=True, ledger_has_signed_transcripts=True
            )
        assert not key_path.exists()

    def test_existing_key_loads_without_opt_in_even_with_signed_ledger(self, tmp_path: Path) -> None:
        key_path = tmp_path / "transcript.ed25519"
        first = TranscriptSigner.auto_provision(key_path, allow_generation=True)
        again = TranscriptSigner.auto_provision(key_path, ledger_has_signed_transcripts=True)
        assert again.key_id == first.key_id

    def test_transcript_key_path_follows_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_TRANSCRIPT_KEY_PATH", str(tmp_path / "k.ed25519"))
        assert transcript_key_path() == tmp_path / "k.ed25519"


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

    def test_non_ed25519_public_key_is_rejected(self, tmp_path: Path) -> None:
        """verify_signature must fail closed on a wrong key *type*, not just
        a wrong key value -- a caller passing an RSA PEM must get a clear
        error, never a silent False from a mismatched-type comparison."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

        rsa_key = generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = (
            rsa_key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )

        signer = TranscriptSigner.auto_provision(tmp_path / "k.ed25519")
        message = signing_message(request_hash="sha256:" + "a" * 64, response_hash="sha256:" + "b" * 64)
        signature = signer.sign(message)

        with pytest.raises(ValueError, match="not an ed25519 key"):
            verify_signature(public_key_pem=rsa_pem, message=message, signature_hex=signature)
