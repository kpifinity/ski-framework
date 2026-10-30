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

Trust anchors (spec §2.1.2, §3.5; framework v3.2.0)
---------------------------------------------------
A valid signature only proves the KG was signed by *some* key. The trust
root is a bundle of Ed25519 public keys pinned by the operator:
``SKI_KG_TRUST_ANCHORS`` is the path to a PEM file holding one or more
``-----BEGIN PUBLIC KEY-----`` blocks (text outside the blocks is ignored,
so the file may carry comments). A KG loads only if its signature verifies
against one of those anchors.

The ``public_key_pem`` embedded in the KG's signature block only *selects*
an anchor: its key ID must equal a configured anchor's key ID, and the
signature is then verified with the anchor's key. A KG re-signed with any
other key is refused even though its embedded key "verifies" it.

Key IDs are ``sha256:<hex sha256 of the raw 32-byte Ed25519 public key>``.

Every loaded KG records how far it is trusted (``kg_trust``):

* ``"anchored"``   — verified against an operator-pinned anchor.
* ``"unanchored"`` — no anchors configured and the operator set
  ``SKI_KG_ALLOW_UNANCHORED=true`` (dev only): the signature is checked
  against the KG's own embedded key, which proves integrity, not authorship.
* ``"unsigned"``   — no signature block, loaded only because the caller
  passed ``require_signature=False`` (server: ``KG_REQUIRE_SIGNATURE=false``)
  and no anchors are configured.

With no anchors and neither escape hatch, every KG is refused.

``KnowledgeGraph.signature_verified`` is ``True`` only for ``"anchored"``:
an integrity check against the KG's own key is not a verified signature in
the spec §3.5 sense, so health and the ``ski_kg_signature_verified`` gauge
never report an unanchored KG as verified.

Library callers that pass no ``trust`` policy get
:meth:`KGTrustPolicy.from_env`, so ``tools/ski-model-deploy`` and the
``audit-ledger`` replay honour the same operator configuration as the
runtime and fail closed when nothing is configured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Optional

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)


_UNIVERSAL_JURISDICTION_VALUES = frozenset({"global", "*", ""})

# ---- Trust anchors -------------------------------------------------------------

KGTrust = Literal["anchored", "unanchored", "unsigned"]

KG_TRUST_ANCHORED: Final = "anchored"
KG_TRUST_UNANCHORED: Final = "unanchored"
KG_TRUST_UNSIGNED: Final = "unsigned"

TRUST_ANCHORS_ENV: Final = "SKI_KG_TRUST_ANCHORS"
ALLOW_UNANCHORED_ENV: Final = "SKI_KG_ALLOW_UNANCHORED"

_PEM_BEGIN: Final = "-----BEGIN "
_PEM_END: Final = "-----END "
_PUBLIC_KEY_LABEL: Final = "PUBLIC KEY"


class KGTrustError(ValueError):
    """A KG, or the trust configuration itself, fails the trust-anchor policy.

    Subclasses :class:`ValueError` so every existing ``except ValueError``
    refusal path keeps treating it as a hard load failure.
    """


def ed25519_key_id(public_key: Ed25519PublicKey) -> str:
    """Return the SKI key ID: ``sha256:`` + hex sha256 of the raw 32-byte public key."""
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class TrustAnchor:
    """One operator-pinned Ed25519 public key that may sign Knowledge Graphs."""

    key_id: str
    public_key: Ed25519PublicKey

    @classmethod
    def from_public_key(cls, public_key: Ed25519PublicKey) -> TrustAnchor:
        return cls(key_id=ed25519_key_id(public_key), public_key=public_key)


def _pem_blocks(text: str, *, source: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(label, full_block)`` pairs, failing closed.

    A BEGIN line without its matching END (a truncated or hand-mangled
    bundle) raises rather than silently dropping a key.
    """
    blocks: list[tuple[str, str]] = []
    pos = 0
    while True:
        begin = text.find(_PEM_BEGIN, pos)
        if begin < 0:
            break
        label_end = text.find("-----", begin + len(_PEM_BEGIN))
        if label_end < 0:
            raise KGTrustError(f"KG trust-anchor bundle {source} has a malformed PEM BEGIN line.")
        label = text[begin + len(_PEM_BEGIN) : label_end]
        end_marker = f"{_PEM_END}{label}-----"
        end = text.find(end_marker, label_end)
        if end < 0:
            raise KGTrustError(
                f"KG trust-anchor bundle {source} has a '{label}' block with no matching END line."
            )
        pos = end + len(end_marker)
        blocks.append((label, text[begin:pos]))
    return blocks


def parse_trust_anchor_bundle(pem: str | bytes, *, source: str = "<bundle>") -> tuple[TrustAnchor, ...]:
    """Parse a PEM bundle of one or more Ed25519 ``PUBLIC KEY`` blocks.

    Fails closed: a bundle with no key, a truncated block, a non-Ed25519
    key, a malformed key, or any block that is not a ``PUBLIC KEY`` (a
    private key or certificate pasted by mistake) is rejected outright
    rather than partially honoured. Duplicate keys collapse to one anchor.
    """
    try:
        text = pem.decode("utf-8") if isinstance(pem, bytes) else pem
    except UnicodeDecodeError as exc:
        raise KGTrustError(f"KG trust-anchor bundle {source} is not UTF-8 PEM text: {exc}") from exc
    anchors: dict[str, TrustAnchor] = {}
    for label, block in _pem_blocks(text, source=source):
        if label != _PUBLIC_KEY_LABEL:
            raise KGTrustError(
                f"KG trust-anchor bundle {source} contains a '{label}' block; only Ed25519 "
                "'PUBLIC KEY' blocks are allowed (never put private keys or certificates here)."
            )
        try:
            key = serialization.load_pem_public_key(block.encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError, UnsupportedAlgorithm) as exc:
            raise KGTrustError(f"KG trust-anchor bundle {source} has a malformed public key: {exc}") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise KGTrustError(f"KG trust-anchor bundle {source} contains a non-Ed25519 public key.")
        anchor = TrustAnchor.from_public_key(key)
        anchors.setdefault(anchor.key_id, anchor)
    if not anchors:
        raise KGTrustError(f"KG trust-anchor bundle {source} contains no Ed25519 public keys.")
    return tuple(anchors.values())


def load_trust_anchors(path: Path) -> tuple[TrustAnchor, ...]:
    """Read and parse the PEM bundle at ``path`` (see :func:`parse_trust_anchor_bundle`)."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KGTrustError(f"Cannot read KG trust-anchor bundle {path}: {exc}") from exc
    return parse_trust_anchor_bundle(data, source=str(path))


def _env_true(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() == "true"


@dataclass(frozen=True)
class KGTrustPolicy:
    """Which keys a KG signature must verify against.

    * ``anchors`` non-empty: the KG must be signed by one of them
      (``kg_trust="anchored"``). ``allow_unanchored`` is then ignored,
      because configuring anchors is an explicit statement of who may sign.
    * no anchors and ``allow_unanchored=True``: integrity-only check
      against the KG's embedded key (``kg_trust="unanchored"``, dev only).
    * no anchors and ``allow_unanchored=False`` (the default): every
      signed KG is refused. An unsigned KG still loads as ``"unsigned"``
      when the caller passed ``require_signature=False``.
    """

    anchors: tuple[TrustAnchor, ...] = ()
    allow_unanchored: bool = False
    source: Optional[str] = None

    @property
    def anchor_key_ids(self) -> tuple[str, ...]:
        return tuple(a.key_id for a in self.anchors)

    def anchor_for(self, key_id: str) -> Optional[TrustAnchor]:
        for anchor in self.anchors:
            if anchor.key_id == key_id:
                return anchor
        return None

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> KGTrustPolicy:
        """Build the policy from ``SKI_KG_TRUST_ANCHORS`` and ``SKI_KG_ALLOW_UNANCHORED``.

        A bundle path that is configured but unreadable, empty or invalid
        raises :class:`KGTrustError`. It never degrades to "unanchored".
        """
        env = os.environ if environ is None else environ
        allow_unanchored = _env_true(env, ALLOW_UNANCHORED_ENV)
        bundle_path = env.get(TRUST_ANCHORS_ENV, "").strip()
        if not bundle_path:
            return cls(allow_unanchored=allow_unanchored)
        anchors = load_trust_anchors(Path(bundle_path))
        if allow_unanchored:
            logger.warning(
                "%s=true is IGNORED because %s is configured: every KG must verify against an anchor.",
                ALLOW_UNANCHORED_ENV,
                TRUST_ANCHORS_ENV,
            )
        return cls(anchors=anchors, allow_unanchored=False, source=bundle_path)

    def describe(self) -> str:
        if self.anchors:
            return f"anchored: {len(self.anchors)} trust anchor(s) [{', '.join(self.anchor_key_ids)}]"
        if self.allow_unanchored:
            return (
                f"UNANCHORED ({ALLOW_UNANCHORED_ENV}=true): KG signatures are checked only against "
                "the KG's own embedded key. Dev only; NOT conformant."
            )
        return f"no trust anchors ({TRUST_ANCHORS_ENV} unset): every signed KG will be refused"


def _no_anchor_refusal() -> KGTrustError:
    return KGTrustError(
        f"No KG trust anchors configured. Set {TRUST_ANCHORS_ENV} to a PEM bundle of the "
        "Ed25519 public key(s) allowed to sign Knowledge Graphs. For local development only, "
        f"{ALLOW_UNANCHORED_ENV}=true loads a KG checked against its own embedded key "
        '(reported as kg_trust="unanchored"). Refusing to load.'
    )


@dataclass
class KnowledgeGraph:
    version: str
    rules: list[dict[str, Any]]
    tag_registry: dict[str, str]
    metadata: dict[str, Any]
    signature_verified: bool
    # Framework v3.2.0: the key the signature verified against, and how far
    # that key is trusted. signer_key_id is None for an unsigned KG; both
    # are None for KGs constructed directly (tests), which never went
    # through signature verification.
    signer_key_id: Optional[str] = None
    kg_trust: Optional[KGTrust] = None

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        require_signature: bool,
        trust: Optional[KGTrustPolicy] = None,
    ) -> KnowledgeGraph:
        """Validate ``data`` and load it under the ``trust`` policy.

        ``trust`` defaults to :meth:`KGTrustPolicy.from_env`, which with
        nothing configured refuses every signed KG. ``require_signature``
        keeps its v3.1 meaning: it decides only what happens when the
        signature block is ABSENT. An unsigned KG never loads while anchors
        are configured.
        """
        policy = trust if trust is not None else KGTrustPolicy.from_env()
        metadata = data.get("metadata") or {}
        rules = data.get("rules") or []
        tag_registry = data.get("tag_registry") or {}
        signature = data.get("signature")

        if not isinstance(rules, list) or not rules:
            raise ValueError("KG must contain a non-empty 'rules' array.")
        if not isinstance(tag_registry, dict):
            raise ValueError("KG must contain a 'tag_registry' object.")
        if signature is not None and not isinstance(signature, dict):
            raise ValueError("KG 'signature' must be an object.")

        signature_verified = False
        signer_key_id: Optional[str] = None
        kg_trust: KGTrust
        if signature:
            signer_key_id, kg_trust = _verify_signature(metadata, rules, tag_registry, signature, policy)
            signature_verified = kg_trust == KG_TRUST_ANCHORED
        elif require_signature:
            raise ValueError(
                "KG has no signature block. Per the SKI Framework v3 "
                "Phase 1 → Phase 2 boundary, an unsigned KG must not be loaded "
                "at runtime. Set KG_REQUIRE_SIGNATURE=false only for local demos."
            )
        elif policy.anchors:
            raise KGTrustError(
                "KG has no signature block but KG trust anchors are configured "
                f"({TRUST_ANCHORS_ENV}); an unsigned KG can never satisfy an anchor. "
                "Sign it with an anchored key. Refusing to load."
            )
        else:
            kg_trust = KG_TRUST_UNSIGNED
            logger.warning(
                "Loaded an UNSIGNED Knowledge Graph (version=%s, kg_trust=unsigned). Signature "
                "verification is disabled for this load (KG_REQUIRE_SIGNATURE=false); NOT conformant.",
                metadata.get("version", "unknown"),
            )

        return cls(
            version=str(metadata.get("version", "unknown")),
            rules=rules,
            tag_registry=tag_registry,
            metadata=metadata,
            signature_verified=signature_verified,
            signer_key_id=signer_key_id,
            kg_trust=kg_trust,
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


def load_signed_kg(
    path: Path,
    *,
    require_signature: bool,
    trust: Optional[KGTrustPolicy] = None,
) -> KnowledgeGraph:
    with path.open() as f:
        data = json.load(f)
    return KnowledgeGraph.from_dict(data, require_signature=require_signature, trust=trust)


def _verify_signature(
    metadata: dict[str, Any],
    rules: list[dict[str, Any]],
    tag_registry: dict[str, str],
    signature: dict[str, Any],
    policy: KGTrustPolicy,
) -> tuple[str, KGTrust]:
    """Verify the KG signature under ``policy``; return ``(signer_key_id, kg_trust)``.

    The embedded ``public_key_pem`` only selects which anchor to use. The
    signature is verified with the anchor's own key, never with a key the
    KG supplied, unless the operator explicitly allowed unanchored loads.
    """
    algorithm = signature.get("algorithm")
    if algorithm != "ed25519":
        raise ValueError(f"Unsupported signature algorithm: {algorithm!r}")
    if not policy.anchors and not policy.allow_unanchored:
        raise _no_anchor_refusal()

    public_key_pem = signature.get("public_key_pem") or ""
    value_hex = signature.get("value_hex") or ""
    if not public_key_pem or not value_hex:
        raise ValueError("Signature block missing public_key_pem or value_hex.")
    if not isinstance(public_key_pem, str) or not isinstance(value_hex, str):
        raise ValueError("Signature block public_key_pem and value_hex must be strings.")

    try:
        embedded = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ValueError(f"Signature public_key_pem is not a valid PEM public key: {exc}") from exc
    if not isinstance(embedded, Ed25519PublicKey):
        raise ValueError("Signature public key is not Ed25519.")
    try:
        signature_bytes = bytes.fromhex(value_hex)
    except ValueError as exc:
        raise ValueError("Signature value_hex is not valid hex.") from exc

    embedded_key_id = ed25519_key_id(embedded)
    canonical = _canonical_bytes(metadata, rules, tag_registry)

    if policy.anchors:
        anchor = policy.anchor_for(embedded_key_id)
        if anchor is None:
            raise KGTrustError(
                f"KG is signed by key {embedded_key_id}, which is not a configured trust anchor "
                f"({', '.join(policy.anchor_key_ids)}). The key embedded in a KG is never a trust "
                "root. Refusing to load."
            )
        try:
            anchor.public_key.verify(signature_bytes, canonical)
        except InvalidSignature:
            raise KGTrustError(
                f"KG signature verification FAILED against trust anchor {anchor.key_id}. Refusing to load."
            ) from None
        logger.info("KG signature verified against trust anchor %s (kg_trust=anchored)", anchor.key_id)
        return anchor.key_id, KG_TRUST_ANCHORED

    # No anchors, SKI_KG_ALLOW_UNANCHORED=true: integrity-only, dev mode.
    try:
        embedded.verify(signature_bytes, canonical)
    except InvalidSignature:
        raise ValueError("KG signature verification FAILED. Refusing to load.") from None
    logger.warning(
        "KG signature verified against its OWN embedded key %s (kg_trust=unanchored). This proves "
        "integrity only, not authorship. Configure %s for any conformant deployment.",
        embedded_key_id,
        TRUST_ANCHORS_ENV,
    )
    return embedded_key_id, KG_TRUST_UNANCHORED


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
