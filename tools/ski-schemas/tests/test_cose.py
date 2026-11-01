"""COSE_Sign1, SCITT signed statements and COSE Receipts, checked against independent implementations.

``cbor2`` (an independent CBOR implementation) decodes what
:mod:`ski_schemas.cose` encodes, and the statements and receipts
:mod:`ski_schemas.scitt` produces are re-verified from cbor2's decoding with
RFC 9052's Sig_structure, so a generic COSE/SCITT verifier accepts them.
(``pycose`` 1.1.0 also accepts them; it is not a CI dependency because its
``ecdsa`` dependency carries an unfixed advisory.)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ski_schemas.cose import CborError, CoseSign1, Tag, cbor_decode, cbor_encode
from ski_schemas.merkle import merkle_root
from ski_schemas.scitt import (
    CONTENT_TYPE,
    HEADER_RECEIPTS,
    ReceiptError,
    make_receipt,
    make_signed_statement,
    receipt_root,
    transparent_statement,
    verify_transparent_statement,
)

cbor2 = pytest.importorskip("cbor2")


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"ski-cose-test").digest())


def _verifier(key: Ed25519PrivateKey) -> Any:
    def verify(signature: bytes, message: bytes) -> bool:
        try:
            key.public_key().verify(signature, message)
        except InvalidSignature:
            return False
        return True

    return verify


def _cose_verify(message: bytes, raw_key: bytes, detached: Optional[bytes] = None) -> dict[Any, Any]:
    """Verify a COSE_Sign1 independently of ski_schemas.cose: cbor2 decodes it and builds RFC 9052's
    Sig_structure; raises on a bad signature. Returns the protected header."""
    import cbor2
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Key

    tagged = cbor2.loads(message)
    assert tagged.tag == 18, "not a tagged COSE_Sign1"
    protected, _unprotected, payload, signature = tagged.value
    header = cbor2.loads(protected)
    assert header[1] == -8, "not EdDSA"
    to_be_signed = cbor2.dumps(["Signature1", protected, b"", payload if payload is not None else detached])
    _Key.from_public_bytes(raw_key).verify(signature, to_be_signed)
    return dict(header)


@pytest.mark.parametrize(
    "value",
    [
        0,
        23,
        24,
        255,
        256,
        65536,
        2**32,
        2**64 - 1,
        -1,
        -25,
        -(2**64),
        b"",
        b"\x00\xff",
        "",
        "ünïcode",
        [],
        [1, [2, b"3"], "4"],
        {},
        {1: "a", -1: "b", "k": [None, True, False]},
        {10: 1, 100: 2, -1: 3, "z": 4, "aa": 5},
    ],
)
def test_cbor_round_trips_and_matches_cbor2(value: Any) -> None:
    encoded = cbor_encode(value)
    assert cbor_decode(encoded) == value
    assert cbor2.loads(encoded) == value


def test_map_keys_use_rfc8949_core_deterministic_order() -> None:
    """Keys sort by their encoded bytes (RFC 8949 §4.2.1, what COSE uses), not length-first (§4.2.3)."""
    value = {"aa": 1, 100: 2, -1: 3, 10: 4}
    encoded = cbor_encode(value)
    keys = [cbor_encode(k) for k in cbor2.loads(encoded)]  # cbor2 keeps the wire order
    assert keys == sorted(keys) == [b"\x0a", b"\x18\x64", b"\x20", b"\x62aa"]


def test_tags_and_rejections() -> None:
    assert cbor_decode(cbor_encode(Tag(18, [b"", {}, None, b"s"]))) == Tag(18, [b"", {}, None, b"s"])
    for bad in (b"", b"\x18", b"\x5f", b"\xf9\x00\x00", b"\x01\x02"):
        with pytest.raises(CborError):
            cbor_decode(bad)


def _entry(seq: int, entry_hash: str) -> dict[str, Any]:
    return {"sequence_number": seq, "entry_hash": entry_hash, "tenant_id": "plant-7", "verdict": "FLAG"}


def test_signed_statement_verifies_independently() -> None:
    key = _key()
    statement = make_signed_statement(
        entry=_entry(2, "ab" * 32),
        envelope={"verdict": "FLAG", "reasoning": "SO2 above cap"},
        key_id="sha256:" + "0" * 64,
        issued_at=1_793_500_000,
        sign_fn=key.sign,
    )
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    _cose_verify(statement, raw)
    claims = cbor2.loads(statement).value
    protected = cbor2.loads(claims[0])
    assert protected[3] == CONTENT_TYPE and protected[1] == -8
    assert protected[15] == {1: "ski:key:sha256:" + "0" * 64, 2: "ski:ledger:plant-7:2", 6: 1_793_500_000}
    assert json.loads(claims[2])["ledger_entry"]["entry_hash"] == "ab" * 32


def _hashes(n: int) -> list[str]:
    return [hashlib.sha256(f"e{i}".encode()).hexdigest() for i in range(n)]


@pytest.mark.parametrize("n, index", [(1, 0), (2, 1), (5, 3), (8, 0), (13, 12)])
def test_receipt_verifies_independently_against_an_independently_computed_root(n: int, index: int) -> None:
    key, hashes = _key(), _hashes(n)
    receipt = make_receipt(entry_hashes=hashes, leaf_index=index, key_id="k", sign_fn=key.sign)
    assert cbor2.loads(receipt).value[2] is None  # detached: the verifier recomputes the root
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    header = _cose_verify(receipt, raw, detached=bytes.fromhex(merkle_root(hashes)))
    assert header[395] == 1  # vds: RFC9162_SHA256
    root, size, leaf = receipt_root(CoseSign1.decode(receipt), hashes[index])
    assert (root.hex(), size, leaf) == (merkle_root(hashes), n, index)


def test_transparent_statement_verifies_and_binds_entry_and_position() -> None:
    key, hashes = _key(), _hashes(6)
    statement = make_signed_statement(
        entry=_entry(4, hashes[3]), envelope=None, key_id="k", issued_at=1, sign_fn=key.sign
    )
    receipt = make_receipt(entry_hashes=hashes, leaf_index=3, key_id="k", sign_fn=key.sign)
    transparent = transparent_statement(statement, [receipt])
    payload, roots = verify_transparent_statement(transparent, _verifier(key))
    assert payload["ledger_entry"]["sequence_number"] == 4
    assert roots == [(bytes.fromhex(merkle_root(hashes)), 6)]
    assert list(cbor2.loads(transparent).value[1][HEADER_RECEIPTS]) == [receipt]

    wrong_position = transparent_statement(
        statement, [make_receipt(entry_hashes=hashes, leaf_index=2, key_id="k", sign_fn=key.sign)]
    )
    with pytest.raises(ReceiptError):
        verify_transparent_statement(wrong_position, _verifier(key))


def test_tampering_is_detected() -> None:
    key, other = _key(), Ed25519PrivateKey.generate()
    hashes = _hashes(4)
    statement = make_signed_statement(
        entry=_entry(1, hashes[0]), envelope={"verdict": "FLAG"}, key_id="k", issued_at=1, sign_fn=key.sign
    )
    with pytest.raises(ReceiptError, match="statement signature"):
        verify_transparent_statement(statement, _verifier(other))
    forged_receipt = make_receipt(entry_hashes=hashes, leaf_index=0, key_id="k", sign_fn=other.sign)
    with pytest.raises(ReceiptError, match="receipt signature"):
        verify_transparent_statement(transparent_statement(statement, [forged_receipt]), _verifier(key))
    protected, unprotected, payload, signature = cbor2.loads(statement).value
    edited = cbor2.CBORTag(18, [protected, unprotected, payload.replace(b"FLAG", b"CLEA"), signature])
    with pytest.raises(ReceiptError):
        verify_transparent_statement(cbor2.dumps(edited), _verifier(key))
