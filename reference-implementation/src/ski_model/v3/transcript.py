"""Provider-neutral LLM transcript record (spec v3.0 §6).

An :class:`LLMTranscript` captures the canonical input/output pair of a
single LLM evaluation call so the verdict can be independently replayed by
an auditor. The transcript is **provider-neutral by design**: no
Anthropic Messages blob, no OpenAI ChatCompletion shape, no Ollama
response envelope leaks into the audit trail. Each backend is responsible
for normalising its own request / response into the canonical strings the
transcript records.

Fields (spec §6.2):

  * ``request_canonical`` — the prompt as actually sent to the LLM,
    UTF-8 text. For chat-style APIs this is the formatted single string
    the backend constructed; for raw-completion APIs it is the prompt
    itself.
  * ``request_hash`` — sha256 of ``request_canonical``.
  * ``response_canonical`` — the structured-output dict matching
    :data:`ski_model.v3.evaluator.RESPONSE_GRAMMAR`. Vendor-specific
    fields MUST be filtered out before canonicalisation.
  * ``response_hash`` — sha256 of the canonical JSON serialisation of
    ``response_canonical`` (sort_keys, compact separators).
  * ``signature_hex`` — ed25519 signature over
    ``request_hash || "|" || response_hash`` produced by the runtime's
    :class:`ski_model.v3.signing.TranscriptSigner`.
  * ``signing_key_id`` — sha256 of the public-key bytes; auditors look
    up the corresponding public key to verify.
  * ``backend_name`` — opaque observability tag (e.g. ``"fake-llm"``,
    ``"ollama-v3:qwen2.5-7b"``). Not part of the audit contract.
  * ``backend_metadata`` — opaque per-backend dict. Use freely for
    observability; NEVER for contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Tuple

from pydantic import BaseModel, ConfigDict, Field


def canonical_request(request_text: str) -> bytes:
    """Canonical request bytes — UTF-8 encoding of the request string."""
    return request_text.encode("utf-8")


def canonical_response(response: Dict[str, Any]) -> bytes:
    """Canonical response bytes — sorted-keys compact JSON, UTF-8.

    Vendor-specific fields are NOT filtered here — callers MUST construct
    ``response`` from the structured-output portion of the LLM reply only.
    The :data:`ski_model.v3.evaluator.RESPONSE_GRAMMAR` is the contract.
    """
    return json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_pair(*, request_text: str, response: Dict[str, Any]) -> Tuple[str, str]:
    """Compute ``(request_hash, response_hash)`` as sha256-prefixed hex."""
    req_hash = "sha256:" + hashlib.sha256(canonical_request(request_text)).hexdigest()
    resp_hash = "sha256:" + hashlib.sha256(canonical_response(response)).hexdigest()
    return req_hash, resp_hash


def signing_message(*, request_hash: str, response_hash: str) -> bytes:
    """Bytes to be signed — concatenation of the two hashes with a separator."""
    return f"{request_hash}|{response_hash}".encode("ascii")


class LLMTranscript(BaseModel):
    """A signed transcript of one LLM evaluation call.

    Round-trips through JSON; auditors deserialise from the ledger and call
    :func:`ski_model.v3.signing.verify_signature` to prove integrity.
    """

    model_config = ConfigDict(extra="forbid")

    transcript_id: str = Field(..., description="Globally unique id for this transcript.")
    request_canonical: str = Field(..., description="The prompt as actually sent.")
    request_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    response_canonical: Dict[str, Any] = Field(
        ..., description="Structured output matching RESPONSE_GRAMMAR."
    )
    response_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    signature_hex: str = Field(..., description="Ed25519 signature, hex-encoded.")
    signing_key_id: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    backend_name: str = Field(..., description="Observability tag for the LLM backend; not contract.")
    backend_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque backend-specific metadata. Never contract.",
    )
    started_at: datetime
    completed_at: datetime


__all__ = [
    "LLMTranscript",
    "canonical_request",
    "canonical_response",
    "hash_pair",
    "signing_message",
]
