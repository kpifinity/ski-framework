"""verify_transcript: a valid transcript verifies; a tampered one does not."""

from __future__ import annotations

import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ski_sdk import verify_transcript


def _h(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _build_signed_transcript(key: Ed25519PrivateKey) -> dict:
    request_canonical = "PROMPT: evaluate so2_ppm=50 against energy.so2.lte_100ppm"
    response_canonical = {"verdict": "CLEAR", "kg_citations": [{"node_id": "energy.so2.lte_100ppm"}]}
    req_hash = _h(request_canonical.encode("utf-8"))
    resp_hash = _h(
        json.dumps(response_canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    sig = key.sign(f"{req_hash}|{resp_hash}".encode("ascii")).hex()
    return {
        "transcript_id": "t-1",
        "request_canonical": request_canonical,
        "request_hash": req_hash,
        "response_canonical": response_canonical,
        "response_hash": resp_hash,
        "signature_hex": sig,
        "signing_key_id": "sha256:" + "0" * 64,
        "backend_name": "fake-llm",
        "backend_metadata": {},
        "started_at": "2026-06-05T12:00:00Z",
        "completed_at": "2026-06-05T12:00:01Z",
    }


def _pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode("ascii")
    )


def test_valid_transcript_verifies() -> None:
    key = Ed25519PrivateKey.generate()
    report = verify_transcript(_build_signed_transcript(key), _pem(key))
    assert report.signature_valid and report.hashes_match and report.ok and bool(report)


def test_tampered_response_fails() -> None:
    key = Ed25519PrivateKey.generate()
    t = _build_signed_transcript(key)
    t["response_canonical"]["verdict"] = "FLAG"  # tamper after signing
    report = verify_transcript(t, _pem(key))
    assert not report.hashes_match
    assert not report.ok


def test_wrong_key_fails() -> None:
    t = _build_signed_transcript(Ed25519PrivateKey.generate())
    report = verify_transcript(t, _pem(Ed25519PrivateKey.generate()))
    assert not report.signature_valid
    assert not report.ok
