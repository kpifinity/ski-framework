"""Ed25519 signing for v3 LLM transcripts.

Every ``LLMTranscript`` is signed before it lands in the audit ledger so an
auditor can prove the LLM input/output pair we recorded is the one the
runtime actually saw. The signing key is the runtime's own — not the LLM
provider's — which keeps the framework LLM-agnostic: an Anthropic-backed
deployment, an Ollama-backed deployment, and a FakeLLM-backed deployment
all sign identically.

Key lifecycle (spec v3.0 §6.3):

  * On first start, if no keypair exists at ``SKI_TRANSCRIPT_KEY_PATH``
    (default ``/app/keys/transcript.ed25519``), a fresh ed25519 keypair is
    generated and persisted with mode ``0600``.
  * The public key is written alongside as ``<name>.pub`` and exposed
    over the API for auditors.
  * The ``signing_key_id`` is the sha256 of the public-key bytes,
    prefixed with ``sha256:`` — same shape as every other v3 hash.
  * Key rotation: provision a new private key at the path; the previous
    public key remains valid for verifying historical transcripts via
    the ``signing_key_id`` recorded on each entry.

The signing algorithm is ed25519 — same as the KG signature scheme so
deployments only need to manage one signing primitive.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger(__name__)


def _default_key_path() -> Path:
    return Path(os.getenv("SKI_TRANSCRIPT_KEY_PATH", "/app/keys/transcript.ed25519"))


def _pub_path(private_path: Path) -> Path:
    return private_path.with_suffix(private_path.suffix + ".pub")


def _compute_key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class TranscriptSigner:
    """Ed25519 signer for v3 LLM transcripts.

    Construct via :meth:`auto_provision` to get the spec §6.3 first-run
    behaviour, or via :meth:`from_private_key_path` if the key was placed
    by external orchestration.
    """

    def __init__(self, private_key: Ed25519PrivateKey, public_key: Ed25519PublicKey) -> None:
        self._private_key = private_key
        self._public_key = public_key
        self._key_id = _compute_key_id(public_key)

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def public_key_pem(self) -> str:
        pem_bytes: bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem_bytes.decode("ascii")

    @classmethod
    def auto_provision(cls, private_key_path: Optional[Path] = None) -> TranscriptSigner:
        """First-run-friendly provisioning.

        If a private key exists at ``private_key_path`` (or the default
        ``$SKI_TRANSCRIPT_KEY_PATH``), load it. Otherwise generate a fresh
        keypair and persist it with restrictive permissions, plus the
        matching public key alongside.
        """
        path = private_key_path or _default_key_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return cls.from_private_key_path(path)

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Create the key file with 0600 from the outset so the private key is
        # never briefly world-readable in the window between writing it and
        # chmod-ing it. os.open honours the mode on creation (subject to the
        # process umask). The explicit chmod afterwards also tightens an
        # over-permissive pre-existing file on platforms that ignore the mode.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key_bytes)
        finally:
            os.close(fd)
        with suppress_oserror():
            os.chmod(path, 0o600)

        _pub_path(path).write_text(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii")
        )

        signer = cls(private_key, public_key)
        logger.info(
            "Generated new transcript signing keypair at %s (key_id=%s)",
            path,
            signer.key_id[:24] + "…",
        )
        return signer

    @classmethod
    def from_private_key_path(cls, path: Path) -> TranscriptSigner:
        raw = path.read_bytes()
        private_key = Ed25519PrivateKey.from_private_bytes(raw)
        return cls(private_key, private_key.public_key())

    def sign(self, message: bytes) -> str:
        """Return a hex-encoded ed25519 signature over ``message``."""
        signature_bytes: bytes = self._private_key.sign(message)
        return signature_bytes.hex()


def verify_signature(
    *,
    public_key_pem: str,
    message: bytes,
    signature_hex: str,
) -> bool:
    """Standalone verification helper — auditors use this without a signer."""
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("Public key is not an ed25519 key.")
    try:
        public_key.verify(bytes.fromhex(signature_hex), message)
    except InvalidSignature:
        return False
    return True


class suppress_oserror:
    """Context manager: swallow OSError (e.g. chmod fails on Windows host mount)."""

    def __enter__(self) -> suppress_oserror:
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: object,
    ) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


__all__ = ["TranscriptSigner", "verify_signature"]
