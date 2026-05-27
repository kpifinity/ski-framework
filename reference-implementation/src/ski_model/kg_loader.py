"""Knowledge Graph loader with signature verification.

A SKI v2.1 Knowledge Graph is a signed JSON document with shape:

  {
    "metadata": { "version": "...", "compiled_at": "...", "model_file_sha256": "...", ... },
    "rules": [ {...}, ... ],
    "tag_registry": { "<subject>": "<rule_id>", ... },
    "signature": { "algorithm": "ed25519", "public_key_pem": "...", "value_hex": "..." }
  }

The signature is computed over the SHA-256 of the canonicalised JSON of the
`metadata` + `rules` + `tag_registry` blocks (signature itself excluded).

Signature verification is REQUIRED at runtime per Phase 1 → Phase 2 boundary
rules. The reference implementation will refuse to operate on an unsigned KG
unless KG_REQUIRE_SIGNATURE=false (non-conformant local-demo only).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGraph:
    version: str
    rules: list[dict[str, Any]]
    tag_registry: dict[str, str]
    metadata: dict[str, Any]
    signature_verified: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, require_signature: bool) -> KnowledgeGraph:
        metadata = data.get("metadata") or {}
        rules = data.get("rules") or []
        tag_registry = data.get("tag_registry") or {}
        signature = data.get("signature")

        if not isinstance(rules, list) or not rules:
            raise ValueError("KG must contain a non-empty 'rules' array.")
        if not isinstance(tag_registry, dict):
            raise ValueError("KG must contain a 'tag_registry' object.")

        signature_verified = False
        if signature:
            signature_verified = _verify_signature(metadata, rules, tag_registry, signature)
        elif require_signature:
            raise ValueError(
                "KG has no signature block. Per the SKI Framework v2.1 "
                "Phase 1 → Phase 2 boundary, an unsigned KG must not be loaded "
                "at runtime. Set KG_REQUIRE_SIGNATURE=false only for local demos."
            )

        return cls(
            version=str(metadata.get("version", "unknown")),
            rules=rules,
            tag_registry=tag_registry,
            metadata=metadata,
            signature_verified=signature_verified,
        )


def load_signed_kg(path: Path, *, require_signature: bool) -> KnowledgeGraph:
    with path.open() as f:
        data = json.load(f)
    return KnowledgeGraph.from_dict(data, require_signature=require_signature)


def _verify_signature(
    metadata: dict[str, Any],
    rules: list[dict[str, Any]],
    tag_registry: dict[str, str],
    signature: dict[str, Any],
) -> bool:
    algorithm = signature.get("algorithm")
    if algorithm != "ed25519":
        raise ValueError(f"Unsupported signature algorithm: {algorithm!r}")

    public_key_pem = signature.get("public_key_pem", "").encode()
    value_hex = signature.get("value_hex", "")
    if not public_key_pem or not value_hex:
        raise ValueError("Signature block missing public_key_pem or value_hex.")

    public_key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("Signature public key is not Ed25519.")

    canonical = _canonical_bytes(metadata, rules, tag_registry)
    try:
        public_key.verify(bytes.fromhex(value_hex), canonical)
    except InvalidSignature:
        raise ValueError("KG signature verification FAILED. Refusing to load.")
    logger.info("KG signature verified (algorithm=%s)", algorithm)
    return True


def _canonical_bytes(
    metadata: dict[str, Any],
    rules: list[dict[str, Any]],
    tag_registry: dict[str, str],
) -> bytes:
    """Canonical serialization used for signing AND ledger hashing.

    Documented here so third parties can verify ledger and KG integrity
    using standard JSON canonicalization (RFC 8785-compatible subset:
    sort_keys=True, no whitespace, UTF-8). Floats are not used in KGs;
    if added, switch to RFC 8785 number rendering.
    """
    payload = {"metadata": metadata, "rules": rules, "tag_registry": tag_registry}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
