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

Framework v3.2.0 adds operator trust anchors (spec §2.1.2, §3.5): a
signature must verify against an anchor the operator pinned, never merely
against the key the KG carries. Tests that load a signed KG therefore pass
an explicit :class:`KGTrustPolicy`; the trust-anchor behaviour itself is
covered at the bottom of this file.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from ski_model.kg_loader import (
    KGTrustError,
    KGTrustPolicy,
    KnowledgeGraph,
    TrustAnchor,
    ed25519_key_id,
    load_signed_kg,
    load_trust_anchors,
    parse_trust_anchor_bundle,
)


@pytest.fixture(autouse=True)
def _no_trust_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A caller that passes no policy reads the environment; keep it empty."""
    monkeypatch.delenv("SKI_KG_TRUST_ANCHORS", raising=False)
    monkeypatch.delenv("SKI_KG_ALLOW_UNANCHORED", raising=False)
    yield


def _public_pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )


def _anchored(*keys: Ed25519PrivateKey) -> KGTrustPolicy:
    """A policy whose trust anchors are exactly ``keys``."""
    return KGTrustPolicy(anchors=tuple(TrustAnchor.from_public_key(k.public_key()) for k in keys))


_UNANCHORED = KGTrustPolicy(allow_unanchored=True)


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
        payload, key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))
        assert kg.signature_verified is True
        assert kg.version == "kgtest-0001"
        assert kg.rules == _RULES

    def test_valid_signature_also_verifies_when_not_required(self) -> None:
        """A present, valid signature is always checked -- require_signature only
        controls what happens when the block is ABSENT."""
        payload, key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=False, trust=_anchored(key))
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
        assert kg.kg_trust == "unsigned"
        assert kg.signer_key_id is None

    def test_tampered_metadata_after_signing_fails_verification(self) -> None:
        payload, key = _signed_payload()
        tampered = copy.deepcopy(payload)
        tampered["metadata"]["version"] = "kgtest-0002-tampered"
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(tampered, require_signature=True, trust=_anchored(key))

    def test_tampered_rules_after_signing_fails_verification(self) -> None:
        payload, key = _signed_payload()
        tampered = copy.deepcopy(payload)
        tampered["rules"][0]["value"] = 999  # attacker raises the cap post-signature
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(tampered, require_signature=True, trust=_anchored(key))

    def test_tampered_payload_fails_even_in_unanchored_dev_mode(self) -> None:
        payload, _key = _signed_payload()
        tampered = copy.deepcopy(payload)
        tampered["rules"][0]["value"] = 999
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(tampered, require_signature=True, trust=_UNANCHORED)

    def test_signature_from_a_different_key_fails(self) -> None:
        """Unanchored dev mode: the embedded key must still match the signature."""
        payload, _key = _signed_payload()
        other_key = Ed25519PrivateKey.generate()
        forged = copy.deepcopy(payload)
        forged["signature"]["public_key_pem"] = _public_pem(other_key)
        with pytest.raises(ValueError, match="verification FAILED"):
            KnowledgeGraph.from_dict(forged, require_signature=True, trust=_UNANCHORED)

    def test_unsupported_algorithm_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["algorithm"] = "rsa-pss"
        with pytest.raises(ValueError, match="Unsupported signature algorithm"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_missing_public_key_pem_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["public_key_pem"] = ""
        with pytest.raises(ValueError, match="missing public_key_pem or value_hex"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_missing_value_hex_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["value_hex"] = ""
        with pytest.raises(ValueError, match="missing public_key_pem or value_hex"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_non_ed25519_public_key_raises(self) -> None:
        payload, key = _signed_payload()
        rsa_key = generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = (
            rsa_key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )
        payload["signature"]["public_key_pem"] = rsa_pem
        with pytest.raises(ValueError, match="not Ed25519"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_signature_block_not_an_object_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"] = "deadbeef"
        with pytest.raises(ValueError, match="'signature' must be an object"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_non_string_signature_fields_raise(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["value_hex"] = 1234
        with pytest.raises(ValueError, match="must be strings"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_malformed_embedded_pem_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["public_key_pem"] = (
            "-----BEGIN PUBLIC KEY-----\nnot base64\n-----END PUBLIC KEY-----\n"
        )
        with pytest.raises(ValueError, match="not a valid PEM public key"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))

    def test_non_hex_signature_value_raises(self) -> None:
        payload, key = _signed_payload()
        payload["signature"]["value_hex"] = "zz-not-hex"
        with pytest.raises(ValueError, match="not valid hex"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))


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
        payload, key = _signed_payload()
        path = tmp_path / "kg.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        kg = load_signed_kg(path, require_signature=True, trust=_anchored(key))
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


# ---- Trust anchors (framework v3.2.0; spec §2.1.2, §3.5) --------------------------


def _write_bundle(path: Path, *keys: Ed25519PrivateKey, preamble: str = "") -> Path:
    path.write_text(preamble + "".join(_public_pem(k) for k in keys), encoding="utf-8")
    return path


class TestTrustAnchors:
    def test_key_id_is_sha256_of_raw_public_key(self) -> None:
        key = Ed25519PrivateKey.generate()
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        assert ed25519_key_id(key.public_key()) == "sha256:" + hashlib.sha256(raw).hexdigest()

    def test_anchored_kg_loads_and_records_signer(self) -> None:
        payload, key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(key))
        assert kg.kg_trust == "anchored"
        assert kg.signer_key_id == ed25519_key_id(key.public_key())
        assert kg.signature_verified is True

    def test_kg_signed_by_any_of_several_anchors_loads(self) -> None:
        payload, key = _signed_payload()
        other = Ed25519PrivateKey.generate()
        kg = KnowledgeGraph.from_dict(payload, require_signature=True, trust=_anchored(other, key))
        assert kg.signer_key_id == ed25519_key_id(key.public_key())

    def test_kg_resigned_with_non_anchor_key_is_refused(self) -> None:
        """C2: the attacker re-signs a tampered KG with their own key and embeds
        that key. The signature is internally valid, but the key is not pinned."""
        _payload, anchor_key = _signed_payload()
        forged, _attacker_key = _signed_payload(rules=[dict(_RULES[0], value=999)])
        with pytest.raises(KGTrustError, match="not a configured trust anchor"):
            KnowledgeGraph.from_dict(forged, require_signature=True, trust=_anchored(anchor_key))

    def test_embedded_anchor_key_with_foreign_signature_is_refused(self) -> None:
        """Claiming the anchor's key while signing with another key fails verification."""
        payload, anchor_key = _signed_payload()
        attacker = Ed25519PrivateKey.generate()
        forged = copy.deepcopy(payload)
        forged["rules"][0]["value"] = 999
        forged["signature"]["value_hex"] = attacker.sign(
            _canonical(forged["metadata"], forged["rules"], forged["tag_registry"])
        ).hex()
        with pytest.raises(KGTrustError, match="FAILED against trust anchor"):
            KnowledgeGraph.from_dict(forged, require_signature=True, trust=_anchored(anchor_key))

    def test_no_anchors_and_no_escape_hatch_refuses_signed_kg(self) -> None:
        payload, _key = _signed_payload()
        with pytest.raises(KGTrustError, match="No KG trust anchors configured"):
            KnowledgeGraph.from_dict(payload, require_signature=True, trust=KGTrustPolicy())

    def test_default_policy_reads_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload, key = _signed_payload()
        with pytest.raises(KGTrustError, match="No KG trust anchors configured"):
            KnowledgeGraph.from_dict(payload, require_signature=True)
        monkeypatch.setenv("SKI_KG_TRUST_ANCHORS", str(_write_bundle(tmp_path / "anchors.pem", key)))
        kg = KnowledgeGraph.from_dict(payload, require_signature=True)
        assert kg.kg_trust == "anchored"

    def test_unanchored_escape_hatch_reports_unanchored_and_not_verified(self) -> None:
        payload, key = _signed_payload()
        kg = KnowledgeGraph.from_dict(payload, require_signature=True, trust=_UNANCHORED)
        assert kg.kg_trust == "unanchored"
        assert kg.signer_key_id == ed25519_key_id(key.public_key())
        # Integrity against the KG's own key is not a verified signature.
        assert kg.signature_verified is False

    def test_unsigned_kg_is_refused_whenever_anchors_are_configured(self) -> None:
        payload = {"metadata": _METADATA, "rules": _RULES, "tag_registry": _TAG_REGISTRY}
        anchors = _anchored(Ed25519PrivateKey.generate())
        with pytest.raises(KGTrustError, match="unsigned KG can never satisfy an anchor"):
            KnowledgeGraph.from_dict(payload, require_signature=False, trust=anchors)

    def test_anchor_for_unknown_key_is_none(self) -> None:
        assert _anchored(Ed25519PrivateKey.generate()).anchor_for("sha256:" + "0" * 64) is None


class TestTrustAnchorBundle:
    def test_parses_multiple_keys_and_ignores_comments(self) -> None:
        a, b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        bundle = "# operator KG signers, pinned 2026-10\n" + _public_pem(a) + "\nsecond:\n" + _public_pem(b)
        anchors = parse_trust_anchor_bundle(bundle)
        assert [x.key_id for x in anchors] == [ed25519_key_id(a.public_key()), ed25519_key_id(b.public_key())]

    def test_accepts_bytes_and_collapses_duplicates(self) -> None:
        a = Ed25519PrivateKey.generate()
        anchors = parse_trust_anchor_bundle((_public_pem(a) * 2).encode("ascii"))
        assert len(anchors) == 1

    def test_rejects_non_utf8(self) -> None:
        with pytest.raises(KGTrustError, match="not UTF-8"):
            parse_trust_anchor_bundle(b"\xff\xfe\x00")

    def test_rejects_empty_bundle(self) -> None:
        with pytest.raises(KGTrustError, match="contains no Ed25519 public keys"):
            parse_trust_anchor_bundle("# nothing pinned yet\n")

    def test_rejects_private_key_block(self) -> None:
        private_pem = (
            Ed25519PrivateKey.generate()
            .private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            .decode("ascii")
        )
        with pytest.raises(KGTrustError, match="'PRIVATE KEY' block"):
            parse_trust_anchor_bundle(private_pem)

    def test_rejects_truncated_block(self) -> None:
        truncated = _public_pem(Ed25519PrivateKey.generate()).split("-----END")[0]
        with pytest.raises(KGTrustError, match="no matching END line"):
            parse_trust_anchor_bundle(truncated)

    def test_rejects_malformed_begin_line(self) -> None:
        with pytest.raises(KGTrustError, match="malformed PEM BEGIN line"):
            parse_trust_anchor_bundle("-----BEGIN PUBLIC KEY\nAAAA\n")

    def test_rejects_malformed_key_body(self) -> None:
        with pytest.raises(KGTrustError, match="malformed public key"):
            parse_trust_anchor_bundle("-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n")

    def test_rejects_non_ed25519_key(self) -> None:
        rsa_pem = (
            generate_private_key(public_exponent=65537, key_size=2048)
            .public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )
        with pytest.raises(KGTrustError, match="non-Ed25519"):
            parse_trust_anchor_bundle(rsa_pem)

    def test_unreadable_bundle_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(KGTrustError, match="Cannot read KG trust-anchor bundle"):
            load_trust_anchors(tmp_path / "missing.pem")


class TestKGTrustPolicyFromEnv:
    def test_nothing_configured_refuses(self) -> None:
        policy = KGTrustPolicy.from_env({})
        assert policy.anchors == () and policy.allow_unanchored is False
        assert "every signed KG will be refused" in policy.describe()

    def test_allow_unanchored_needs_exactly_true(self) -> None:
        assert KGTrustPolicy.from_env({"SKI_KG_ALLOW_UNANCHORED": " TRUE "}).allow_unanchored is True
        assert KGTrustPolicy.from_env({"SKI_KG_ALLOW_UNANCHORED": "yes"}).allow_unanchored is False
        assert "UNANCHORED" in KGTrustPolicy.from_env({"SKI_KG_ALLOW_UNANCHORED": "true"}).describe()

    def test_anchor_bundle_is_loaded(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        path = _write_bundle(tmp_path / "anchors.pem", key)
        policy = KGTrustPolicy.from_env({"SKI_KG_TRUST_ANCHORS": str(path)})
        assert policy.anchor_key_ids == (ed25519_key_id(key.public_key()),)
        assert policy.source == str(path)
        assert policy.describe().startswith("anchored: 1 trust anchor(s)")

    def test_anchors_override_the_escape_hatch(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_bundle(tmp_path / "anchors.pem", Ed25519PrivateKey.generate())
        with caplog.at_level(logging.WARNING, logger="ski_model.kg_loader"):
            policy = KGTrustPolicy.from_env(
                {"SKI_KG_TRUST_ANCHORS": str(path), "SKI_KG_ALLOW_UNANCHORED": "true"}
            )
        assert policy.allow_unanchored is False
        assert "IGNORED" in caplog.text

    def test_configured_but_invalid_bundle_never_degrades(self, tmp_path: Path) -> None:
        empty = tmp_path / "anchors.pem"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(KGTrustError):
            KGTrustPolicy.from_env({"SKI_KG_TRUST_ANCHORS": str(empty), "SKI_KG_ALLOW_UNANCHORED": "true"})
