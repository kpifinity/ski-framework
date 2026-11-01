"""Independent checkers for the black-box suite: RFC 8785 canonical JSON, RFC 6962 Merkle proofs, COSE_Sign1.

Written from the specification and the RFCs, not from the reference
implementation, and checked against ``spec/test-vectors/`` by
``test_checkers_against_vectors.py``. Third-party dependencies are
``cryptography`` (Ed25519) and ``cbor2`` (CBOR decoding) only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Optional, Sequence

import cbor2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class NotCanonicalizable(ValueError):
    """The value has no canonical form (spec §7.3 rule 3)."""


# --------------------------------------------------------------------------
# RFC 8785 (JCS) with SKI's NFC rule for string values (spec §7.3)
# --------------------------------------------------------------------------

_NUMBER = re.compile(r"^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$")


def _number(value: float | int) -> str:
    if isinstance(value, int):
        as_float = float(value)
        if int(as_float) != value:
            raise NotCanonicalizable(f"integer {value} has no exact IEEE-754 double")
        value = as_float
    if math.isnan(value) or math.isinf(value):
        raise NotCanonicalizable("NaN and infinities have no canonical form")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    match = _NUMBER.match(repr(abs(value)))  # repr is the shortest round-tripping digit string
    assert match is not None
    int_part, frac_part, exp = match.group(1), match.group(2) or "", int(match.group(3) or 0)
    all_digits = int_part + frac_part
    stripped = all_digits.lstrip("0")
    point = len(int_part) + exp - (len(all_digits) - len(stripped))
    digits = stripped.rstrip("0")
    k, n = len(digits), point  # value = 0.digits * 10**n
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        text = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + text


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _string(value: str) -> str:
    out = ['"']
    for ch in value:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise NotCanonicalizable("lone surrogate")
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _string(unicodedata.normalize("NFC", value))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise NotCanonicalizable("member names must be strings")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))  # UTF-16 code units
        return "{" + ",".join(_string(k) + ":" + _serialize(value[k]) for k in keys) + "}"
    raise NotCanonicalizable(f"type {type(value).__name__} has no JSON form")


def canonicalize(value: Any) -> bytes:
    """The spec §7.3 canonical bytes of a JSON value."""
    return _serialize(value).encode("utf-8")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in pairs:
        if key in out:
            raise NotCanonicalizable(f"duplicate member name {key!r}")
        out[key] = val
    return out


def parse_json(text: str | bytes) -> Any:
    """Parse JSON text the way ``JSON.parse`` reads numbers, rejecting duplicate names and a BOM."""
    if isinstance(text, bytes):
        if text.startswith(b"\xef\xbb\xbf"):
            raise NotCanonicalizable("byte-order mark")
        text = text.decode("utf-8")
    elif text.startswith("﻿"):
        raise NotCanonicalizable("byte-order mark")
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_int=lambda s: float(int(s)))


def sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def kg_version_hash(kg: dict[str, Any]) -> str:
    """Spec §7.3 hash of a graph KG: ``sha256:`` + SHA-256 of the canonical ``{metadata, nodes, edges}``."""
    return sha256_prefixed(canonicalize({k: kg[k] for k in ("metadata", "nodes", "edges")}))


# --------------------------------------------------------------------------
# RFC 6962 / RFC 9162 Merkle trees over ledger entry hashes (spec §7.1)
# --------------------------------------------------------------------------


def _leaf(raw: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + raw).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def merkle_root(entry_hashes: Sequence[str]) -> str:
    """Hex Merkle tree head over the 32-byte entry hashes, in sequence order."""
    if not entry_hashes:
        return hashlib.sha256(b"").hexdigest()

    def mth(items: Sequence[bytes]) -> bytes:
        if len(items) == 1:
            return _leaf(items[0])
        k = 1
        while k * 2 < len(items):
            k *= 2
        return _node(mth(items[:k]), mth(items[k:]))

    return mth([bytes.fromhex(h) for h in entry_hashes]).hex()


def root_from_inclusion_proof(
    entry_hash: bytes, leaf_index: int, tree_size: int, path: Sequence[bytes]
) -> bytes:
    """RFC 9162 §2.1.3.2: the root an inclusion proof implies, or ValueError for a malformed proof."""
    if leaf_index >= tree_size:
        raise ValueError("leaf index outside the tree")
    fn, sn = leaf_index, tree_size - 1
    r = _leaf(entry_hash)
    for p in path:
        if sn == 0:
            raise ValueError("proof too long")
        if fn & 1 or fn == sn:
            r = _node(p, r)
            if not fn & 1:
                while fn != 0 and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = _node(r, p)
        fn >>= 1
        sn >>= 1
    if sn != 0:
        raise ValueError("proof too short")
    return r


# --------------------------------------------------------------------------
# COSE_Sign1 (RFC 9052) with EdDSA, and base64url
# --------------------------------------------------------------------------

ALG_EDDSA = -8


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def ed25519_verify(raw_public_key: bytes, signature: bytes, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(raw_public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


class Sign1:
    """A decoded COSE_Sign1 message (tag 18 optional)."""

    def __init__(self, encoded: bytes) -> None:
        item = cbor2.loads(encoded)
        if isinstance(item, cbor2.CBORTag):
            if item.tag != 18:
                raise ValueError(f"CBOR tag {item.tag} is not COSE_Sign1 (18)")
            item = item.value
        if not isinstance(item, list) or len(item) != 4:
            raise ValueError("COSE_Sign1 must be a four-element array")
        self.protected_bytes: bytes = item[0]
        self.protected: dict[Any, Any] = cbor2.loads(item[0]) if item[0] else {}
        self.unprotected: dict[Any, Any] = item[1]
        self.payload: Optional[bytes] = item[2]
        self.signature: bytes = item[3]

    def verify(self, raw_public_key: bytes, detached_payload: Optional[bytes] = None) -> bool:
        if self.protected.get(1) != ALG_EDDSA:
            return False
        payload = self.payload if self.payload is not None else detached_payload
        if payload is None:
            return False
        to_be_signed = cbor2.dumps(["Signature1", self.protected_bytes, b"", payload])
        return ed25519_verify(raw_public_key, self.signature, to_be_signed)
