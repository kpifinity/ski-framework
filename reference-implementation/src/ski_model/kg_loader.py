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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)


_UNIVERSAL_JURISDICTION_VALUES = frozenset({"global", "*", ""})


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
                "KG has no signature block. Per the SKI Framework v3 "
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

    def scope_to(
        self,
        *,
        jurisdiction: Optional[str],
        as_of: datetime,
    ) -> dict[str, Any]:
        """Return a v3 snapshot dict containing only applicable obligations.

        An obligation is included when **all** of these hold:

          * Its ``effective_date`` (if present) is ``<= as_of``.
          * Its ``sunset_date`` (if present and not ``null``) is ``>= as_of``.
          * Its ``jurisdiction`` field is either absent, set to a universal
            sentinel (``"global"``, ``"*"``, empty string), or matches the
            ``jurisdiction`` argument exactly. If ``jurisdiction`` is
            ``None`` (no tenant restriction supplied) all jurisdictions
            pass through.

        The returned dict is the v3 evaluator's expected snapshot shape:
        ``{"version": ..., "obligations": [...], "definitions": [...],
        "scope": {"jurisdiction": ..., "as_of": ..., "n_in": ..., "n_out": ...}}``.
        The ``scope`` block is recorded so the LLM transcript carries the
        framework's view of *what was sent* — an auditor can replay the
        same scope and confirm.
        """
        n_in = len(self.rules)
        kept: list[dict[str, Any]] = [
            rule for rule in self.rules if _rule_is_in_scope(rule, jurisdiction=jurisdiction, as_of=as_of)
        ]
        snapshot: dict[str, Any] = {
            "version": self.version,
            "obligations": kept,
            "definitions": self.metadata.get("definitions", []),
            "scope": {
                "jurisdiction": jurisdiction,
                "as_of": as_of.isoformat(),
                "n_in": n_in,
                "n_out": len(kept),
            },
        }
        return snapshot


def _parse_iso_date(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 date or datetime string; return None on failure.

    Bare dates (``YYYY-MM-DD``) are read as midnight UTC so they compare
    cleanly against the measurement timestamp.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        # Accept both date-only and full datetimes.
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value + "T00:00:00+00:00")
    except ValueError:
        return None


def _rule_is_in_scope(
    rule: dict[str, Any],
    *,
    jurisdiction: Optional[str],
    as_of: datetime,
) -> bool:
    """True iff ``rule`` is effective at ``as_of`` and applies to ``jurisdiction``."""
    effective_at = _parse_iso_date(rule.get("effective_date"))
    if effective_at is not None and effective_at > as_of:
        return False

    sunset_raw = rule.get("sunset_date")
    if sunset_raw is not None:
        sunset_at = _parse_iso_date(sunset_raw)
        if sunset_at is not None and sunset_at < as_of:
            return False

    if jurisdiction is None:
        return True

    rule_jurisdiction = rule.get("jurisdiction")
    if rule_jurisdiction is None:
        return True
    if isinstance(rule_jurisdiction, str):
        normalised = rule_jurisdiction.strip().lower()
        if normalised in _UNIVERSAL_JURISDICTION_VALUES:
            return True
        return normalised == jurisdiction.strip().lower()
    if isinstance(rule_jurisdiction, list):
        # KG authors can list multiple jurisdictions. Any match wins.
        wanted = jurisdiction.strip().lower()
        for item in rule_jurisdiction:
            if isinstance(item, str):
                norm = item.strip().lower()
                if norm in _UNIVERSAL_JURISDICTION_VALUES or norm == wanted:
                    return True
        return False
    return False


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
