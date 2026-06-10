"""Verify the signed provenance of a verdict's LLM transcript (spec §6.2).

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
from typing import Any, Dict, Mapping, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

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


__all__ = ["VerificationReport", "verify_transcript"]
