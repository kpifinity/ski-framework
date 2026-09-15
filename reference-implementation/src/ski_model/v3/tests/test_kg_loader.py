"""Tests for ``ski_model.kg_loader`` — signed Knowledge Graph loading.

Signature verification is the Phase 1 -> Phase 2 boundary control (spec
v3.0): a KG with no signature block MUST NOT load when
``require_signature=True``, and a KG whose signature doesn't verify
(wrong key, tampered payload, unsupported algorithm) MUST be refused
outright -- never loaded "best effort". These are the safety-critical,
fail-closed branches this module exists for; before this file,
``kg_loader.py`` had zero direct unit tests (only ``scope_to()`` was
covered, via ``test_kg_scoping.py``) and the signature-verification and
file-loading code paths were entirely unexercised.

The signing convention mirrors ``scripts/make-demo-kg.py``: canonical
bytes are ``json.dumps({"metadata", "rules", "tag_registry"},
sort_keys=True, separators=(",", ":"))``, signed with an ed25519 key.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from ski_model.kg_loader import KnowledgeGraph, load_signed_kg

_METADATA: Dict[str, Any] = {"version": "kgtest-0001"}
_RULES: List[Dict[str, Any]] = [
    {"id": "r.a", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
]
_TAG_REGISTRY: Dict[str, str] = {"emissions": "r.a"}


def _canonical(metadata: Dict[str, Any], rules: List[Dict[str, Any]], tag_registry: Dict[str, str]) -> bytes:
    payload = {"metadata": metadata, "rules": rules, "tag_registry": tag_registry}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _signed_payload(
    *,
    metadata: Dict[str, Any] | None = None,
    rules: List[Dict[str, Any]] | None = None,
    tag_registry: Dict[str, str] | None = None,
) -> Tuple[Dict[str, Any], Ed25519PrivateKey]:
    """Build a KG dict signed with a freshly generated ed25519 key."""
    metadata = _METADATA if metadata is None else metadata
    rules = _RULES if rules is None else rules
    tag_registry = _TAG_REGISTRY if tag_registry is None else tag_registry

    key = Ed25519PrivateKey.generate()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
    signature_hex = key.sign(_canonical(metadata, rules, tag_registry)).hex()

    payload = {
        "metadata": metadata,
        "rules": rules,
        "tag_registry": tag_registry,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": public_pem,
            "value_hex": signature_hex,
        },
    }
    return payload, key


# ---- Signature verification: happy path ---------------------------------------


class TestValidSignature:
    def test_valid_signature_verifies(self) -> None:
        payload, _key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=True)
        assert kg.signature_verified is True
        assert kg.version == "kgtest-0001"
        assert kg.rules == _RULES

    def test_valid_signature_also_verifies_when_not_required(self) -> None:
        """A present, valid signature is always checked -- require_signature only
        controls what happens when the block is ABSENT."""
        payload, _key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=False)
        assert kg.signature_verified is True


# ---- Signature verification: fail-closed branches ------------------------------


class TestSignatureRefusal:
    def test_missing_signature_with_require_true_raises(self) -> None:
        """The exact Phase 1 -> Phase 2 boundary rule: no signature, required -> refuse."""
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": _TAG_REGISTRY}
        with pytest.raises(ValueError, match="no signature block"):
            KnowledgeGraph.from_dict(payload, require_signature=True)

    def test_missing_signature_with_require_false_loads_unverified(self) -> None:
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": _TAG_REGISTRY}
        kg = KnowledgeGraph.from_dict(payload, require_signature=False)
        assert kg.signature_verified is False
        assert kg.rules == _RULES

    def test_tampered_metadata_after_signing_fails_verification(self) -> None:
        payload, _key = _signed_payload()
        tampered = copy.deepcopy(payload)
        tampered["metadata"]["version"] = "kgtest-0002-tampered"
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(tampered, require_signature=True)

    def test_tampered_rules_after_signing_fails_verification(self) -> None:
        payload, _key = _signed_payload()
        tampered = copy.deepcopy(payload)
        tampered["rules"][0]["value"] = 999  # attacker raises the cap post-signature
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(tampered, require_signature=True)

    def test_signature_from_a_different_key_fails(self) -> None:
        payload, _key = _signed_payload()
        other_key = Ed25519PrivateKey.generate()
        forged = copy.deepcopy(payload)
        forged["signature"]["public_key_pem"] = (
            other_key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(forged, require_signature=True)

    def test_unsupported_algorithm_raises(self) -> None:
        payload, _key = _signed_payload()
        payload["signature"]["algorithm"] = "rsa-pss"
        with pytest.raises(ValueError, match="Unsupported signature algorithm"):
            KnowledgeGraph.from_dict(payload, require_signature=True)

    def test_missing_public_key_pem_raises(self) -> None:
        payload, _key = _signed_payload()
        payload["signature"]["public_key_pem"] = ""
        with pytest.raises(ValueError, match="missing public_key_pem or value_hex"):
            KnowledgeGraph.from_dict(payload, require_signature=True)

    def test_missing_value_hex_raises(self) -> None:
        payload, _key = _signed_payload()
        payload["signature"]["value_hex"] = ""
        with pytest.raises(ValueError, match="missing public_key_pem or value_hex"):
            KnowledgeGraph.from_dict(payload, require_signature=True)

    def test_non_ed25519_public_key_raises(self) -> None:
        payload, _key = _signed_payload()
        rsa_key = generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = (
            rsa_key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )
        payload["signature"]["public_key_pem"] = rsa_pem
        with pytest.raises(ValueError, match="not Ed25519"):
            KnowledgeGraph.from_dict(payload, require_signature=True)


# ---- Structural validation ------------------------------------------------------


class TestStructuralValidation:
    def test_empty_rules_raises(self) -> None:
        payload = {"metadata": _METADATA, "rules": [], "tag_registry": _TAG_REGISTRY}
        with pytest.raises(ValueError, match="non-empty 'rules'"):
            KnowledgeGraph.from_dict(payload, require_signature=False)

    def test_missing_rules_key_raises(self) -> None:
        payload = {"metadata": _METADATA, "tag_registry": _TAG_REGISTRY}
        with pytest.raises(ValueError, match="non-empty 'rules'"):
            KnowledgeGraph.from_dict(payload, require_signature=False)

    def test_tag_registry_not_a_dict_raises(self) -> None:
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": ["not", "a", "dict"]}
        with pytest.raises(ValueError, match="'tag_registry' object"):
            KnowledgeGraph.from_dict(payload, require_signature=False)


# ---- load_signed_kg: file-based loading ------------------------------------------


class TestLoadSignedKG:
    def test_loads_signed_file_and_verifies(self, tmp_path: Path) -> None:
        payload, _key = _signed_payload()
        path = tmp_path / "kg.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        kg = load_signed_kg(path, require_signature=True)
        assert kg.signature_verified is True
        assert kg.rules == _RULES

    def test_loads_unsigned_file_when_not_required(self, tmp_path: Path) -> None:
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": _TAG_REGISTRY}
        path = tmp_path / "kg.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        kg = load_signed_kg(path, require_signature=False)
        assert kg.signature_verified is False

    def test_refuses_unsigned_file_when_required(self, tmp_path: Path) -> None:
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": _TAG_REGISTRY}
        path = tmp_path / "kg.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="no signature block"):
            load_signed_kg(path, require_signature=True)

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_signed_kg(tmp_path / "does-not-exist.json", require_signature=False)


# ---- scope_to: date parsing and jurisdiction edge cases --------------------------


class TestScopeToEdgeCases:
    _AS_OF = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    def _kg(self, rules: List[Dict[str, Any]]) -> KnowledgeGraph:
        return KnowledgeGraph(
            version="v3test-0001",
            rules=rules,
            tag_registry={},
            metadata={"version": "v3test-0001"},
            signature_verified=True,
        )

    def test_malformed_effective_date_string_is_ignored_not_crashed(self) -> None:
        """An unparsable date string must not raise -- it degrades to
        'always effective' (matches the missing-date behaviour) rather than
        crashing the scoping pass on one bad rule."""
        kg = self._kg([{"id": "r.a", "effective_date": "not-a-real-date"}])
        out = kg.scope_to(jurisdiction=None, as_of=self._AS_OF)
        assert len(out["obligations"]) == 1

    def test_malformed_sunset_date_string_is_ignored_not_crashed(self) -> None:
        kg = self._kg([{"id": "r.a", "sunset_date": "also-not-a-date"}])
        out = kg.scope_to(jurisdiction=None, as_of=self._AS_OF)
        assert len(out["obligations"]) == 1

    def test_non_string_non_list_jurisdiction_excludes_the_rule(self) -> None:
        """A jurisdiction field of an unexpected type (neither str nor list)
        must fail closed -- excluded, not silently treated as universal."""
        kg = self._kg([{"id": "r.a", "jurisdiction": 42}])
        out = kg.scope_to(jurisdiction="us-ca", as_of=self._AS_OF)
        assert out["obligations"] == []
