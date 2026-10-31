"""Verify a verdict's signed LLM transcript (spec §6.2) and a sovereignty attestation (§6.4).

Re-implements the framework's canonicalisation and Ed25519 verification so the
SDK depends only on `cryptography` — not on the reference implementation. The
runtime signs ``request_hash || "|" || response_hash``; an auditor recomputes
those hashes from the canonical request/response, then verifies the signature
against the runtime's public key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from ski_schemas.canonical import canonicalize

from .models import LLMTranscript


def _sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_response(response: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(response), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class VerificationReport:
    """Result of verifying a transcript."""

    signature_valid: bool
    hashes_match: bool
    ok: bool

    def __bool__(self) -> bool:
        return self.ok


def verify_transcript(
    transcript: Union[LLMTranscript, Dict[str, Any]],
    public_key_pem: Union[str, bytes],
    *,
    strict: bool = True,
) -> VerificationReport:
    """Verify a transcript's Ed25519 signature (and, in strict mode, its hashes).

    ``strict=True`` (default) also recomputes ``request_hash``/``response_hash``
    from the canonical request/response and confirms they match the recorded
    values — catching a response that was altered after signing.
    """
    t = transcript if isinstance(transcript, LLMTranscript) else LLMTranscript.model_validate(transcript)

    recomputed_req = _sha256_prefixed(t.request_canonical.encode("utf-8"))
    recomputed_resp = _sha256_prefixed(_canonical_response(t.response_canonical))
    hashes_match = recomputed_req == t.request_hash and recomputed_resp == t.response_hash

    pem = public_key_pem.encode("ascii") if isinstance(public_key_pem, str) else public_key_pem
    key = load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public_key_pem is not an Ed25519 public key.")

    message = f"{t.request_hash}|{t.response_hash}".encode("ascii")
    try:
        key.verify(bytes.fromhex(t.signature_hex), message)
        signature_valid = True
    except (InvalidSignature, ValueError):
        signature_valid = False

    ok = signature_valid and (hashes_match or not strict)
    return VerificationReport(signature_valid=signature_valid, hashes_match=hashes_match, ok=ok)


@dataclass(frozen=True)
class AttestationReport:
    """Result of verifying a ``/api/sovereignty`` attestation offline."""

    signature_valid: bool
    key_trusted: bool
    strict: bool
    document: Dict[str, Any]

    @property
    def ok(self) -> bool:
        """The trusted key signed this document. Whether its posture is acceptable is ``strict`` and the fields."""
        return self.signature_valid and self.key_trusted

    def __bool__(self) -> bool:
        return self.ok


def _key_id(key: Ed25519PublicKey) -> str:
    return _sha256_prefixed(key.public_bytes(Encoding.Raw, PublicFormat.Raw))


def verify_sovereignty_attestation(
    attestation: Mapping[str, Any],
    *,
    trusted_key_id: Optional[str] = None,
    trusted_public_key_pem: Union[str, bytes, None] = None,
) -> AttestationReport:
    """Verify a ``GET /api/sovereignty`` response without contacting the runtime.

    The response embeds its public key, which on its own proves nothing, so
    the caller pins the key: ``trusted_key_id`` (the ``signing_key_id`` the
    runtime records on every ledger entry) and/or ``trusted_public_key_pem``.
    The signature is Ed25519 over the spec §7.3 canonical JSON of
    ``document``.
    """
    if trusted_key_id is None and trusted_public_key_pem is None:
        raise ValueError("Pin the runtime's key: pass trusted_key_id and/or trusted_public_key_pem.")
    document = dict(attestation["document"])
    signature = attestation["signature"]
    if signature.get("algorithm") != "ed25519":
        raise ValueError(f"Unsupported attestation algorithm {signature.get('algorithm')!r}.")

    pem = trusted_public_key_pem if trusted_public_key_pem is not None else signature["public_key_pem"]
    key = load_pem_public_key(pem.encode("ascii") if isinstance(pem, str) else pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("The attestation key is not an Ed25519 public key.")
    key_id = _key_id(key)
    key_trusted = key_id == signature.get("signing_key_id") and trusted_key_id in (None, key_id)
    try:
        key.verify(bytes.fromhex(signature["value_hex"]), canonicalize(document))
        signature_valid = True
    except (InvalidSignature, ValueError):
        signature_valid = False
    return AttestationReport(
        signature_valid=signature_valid,
        key_trusted=key_trusted,
        strict=document.get("sovereignty_mode") == "strict",
        document=document,
    )


__all__ = ["AttestationReport", "VerificationReport", "verify_sovereignty_attestation", "verify_transcript"]
