"""verify_sovereignty_attestation: a signed attestation verifies offline against a pinned key."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ski_schemas.canonical import canonicalize
from ski_sdk import verify_sovereignty_attestation


def _pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )


def _key_id(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _attestation(key: Ed25519PrivateKey, **document: Any) -> Dict[str, Any]:
    doc = {
        "sovereignty_mode": "strict",
        "model_weight_hash": "sha256:" + "a" * 64,
        "egress_guard": {"attempts_total": 0, "tripped": False},
        "signed_at": "2026-10-30T12:00:00.000000Z",
        **document,
    }
    return {
        "document": doc,
        "signature": {
            "algorithm": "ed25519",
            "signing_key_id": _key_id(key),
            "public_key_pem": _pem(key),
            "value_hex": key.sign(canonicalize(doc)).hex(),
        },
    }


def test_valid_attestation_verifies_against_the_pinned_key_id() -> None:
    key = Ed25519PrivateKey.generate()
    report = verify_sovereignty_attestation(_attestation(key), trusted_key_id=_key_id(key))
    assert report.ok and report.signature_valid and report.key_trusted and report.strict
    assert report.document["model_weight_hash"] == "sha256:" + "a" * 64


def test_valid_attestation_verifies_against_a_pinned_pem() -> None:
    key = Ed25519PrivateKey.generate()
    assert verify_sovereignty_attestation(_attestation(key), trusted_public_key_pem=_pem(key))


def test_advisory_attestation_verifies_but_is_not_strict() -> None:
    key = Ed25519PrivateKey.generate()
    report = verify_sovereignty_attestation(
        _attestation(key, sovereignty_mode="advisory"), trusted_key_id=_key_id(key)
    )
    assert report.ok and not report.strict


def test_edited_document_fails() -> None:
    key = Ed25519PrivateKey.generate()
    attestation = _attestation(key)
    attestation["document"]["egress_guard"]["attempts_total"] = 1
    report = verify_sovereignty_attestation(attestation, trusted_key_id=_key_id(key))
    assert not report.signature_valid and not report


def test_a_self_consistent_attestation_from_another_key_is_not_trusted() -> None:
    """An attacker can sign with their own key and embed it; pinning the key id catches that."""
    pinned, attacker = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    report = verify_sovereignty_attestation(_attestation(attacker), trusted_key_id=_key_id(pinned))
    assert report.signature_valid and not report.key_trusted and not report


def test_pinned_pem_ignores_the_embedded_key() -> None:
    pinned, attacker = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    attestation = _attestation(attacker)
    forged = copy.deepcopy(attestation)
    forged["signature"]["signing_key_id"] = _key_id(pinned)
    report = verify_sovereignty_attestation(forged, trusted_public_key_pem=_pem(pinned))
    assert not report.signature_valid and not report


def test_a_key_must_be_pinned() -> None:
    with pytest.raises(ValueError, match="Pin the runtime's key"):
        verify_sovereignty_attestation(_attestation(Ed25519PrivateKey.generate()))
