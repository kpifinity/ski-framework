"""Deterministic CBOR (RFC 8949 §4.2.1) and COSE_Sign1 with EdDSA (RFC 9052, RFC 9053).

Just enough of both for SKI's standards-native evidence (:mod:`ski_schemas.scitt`):
SCITT signed statements and COSE Receipts. The encoder emits the core
deterministic encoding (shortest-form integers and lengths, definite
lengths, map keys sorted by their encoded bytes), so the same object always
encodes to the same bytes; the decoder accepts the subset the encoder
produces. Only Ed25519 (``alg`` -8, EdDSA) is used, the algorithm of the
runtime's deployment key.

Interoperability is tested against independent implementations (``cbor2``,
``pycose``) in ``tools/ski-schemas/tests/test_cose.py``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

__all__ = [
    "ALG_EDDSA",
    "COSE_SIGN1_TAG",
    "CborError",
    "CoseSign1",
    "Tag",
    "cbor_decode",
    "cbor_encode",
    "sig_structure",
    "sign1",
]

#: COSE algorithm identifier for EdDSA (RFC 9053 §2.2).
ALG_EDDSA = -8
#: CBOR tag of a COSE_Sign1 message (RFC 9052 §4.2).
COSE_SIGN1_TAG = 18

# Common header labels (RFC 9052 §3.1).
HEADER_ALG = 1
HEADER_CONTENT_TYPE = 3
HEADER_KID = 4


class CborError(ValueError):
    """Bytes that are not (the supported subset of) CBOR."""


@dataclass(frozen=True)
class Tag:
    """A CBOR tagged item."""

    tag: int
    value: Any


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    for info, fmt in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
        if n < 1 << (8 * struct.calcsize(fmt)):
            return bytes([major << 5 | info]) + struct.pack(fmt, n)
    raise CborError(f"integer {n} does not fit in 64 bits")


def cbor_encode(value: Any) -> bytes:
    """Deterministic CBOR of ``value`` (None, bool, int, bytes, str, list/tuple, dict, :class:`Tag`)."""
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, (bytes, bytearray)):
        return _head(2, len(value)) + bytes(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _head(3, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        return _head(4, len(value)) + b"".join(cbor_encode(v) for v in value)
    if isinstance(value, dict):
        items = sorted((cbor_encode(k), cbor_encode(v)) for k, v in value.items())
        return _head(5, len(items)) + b"".join(k + v for k, v in items)
    if isinstance(value, Tag):
        return _head(6, value.tag) + cbor_encode(value.value)
    raise CborError(f"cannot CBOR-encode {type(value).__name__}")


def cbor_decode(data: bytes) -> Any:
    """Decode one CBOR item that fills ``data`` exactly."""
    value, end = _decode(data, 0)
    if end != len(data):
        raise CborError("trailing bytes after the CBOR item")
    return value


def _decode(data: bytes, i: int) -> tuple[Any, int]:
    if i >= len(data):
        raise CborError("truncated CBOR")
    major, info = data[i] >> 5, data[i] & 0x1F
    i += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if info in simple:
            return simple[info], i
        raise CborError(f"unsupported simple value or float (info {info})")
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise CborError("truncated CBOR")
        n = int.from_bytes(data[i : i + size], "big")
        i += size
    else:
        raise CborError("indefinite lengths are not supported")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(data):
            raise CborError("truncated CBOR")
        raw = data[i : i + n]
        return (bytes(raw) if major == 2 else raw.decode("utf-8")), i + n
    if major == 4:
        items = []
        for _ in range(n):
            item, i = _decode(data, i)
            items.append(item)
        return items, i
    if major == 5:
        result: dict[Any, Any] = {}
        for _ in range(n):
            key, i = _decode(data, i)
            result[key], i = _decode(data, i)
        return result, i
    value, i = _decode(data, i)
    return Tag(n, value), i


def sig_structure(protected: bytes, payload: bytes, external_aad: bytes = b"") -> bytes:
    """The bytes a COSE_Sign1 signature covers (RFC 9052 §4.4)."""
    return cbor_encode(["Signature1", protected, external_aad, payload])


@dataclass(frozen=True)
class CoseSign1:
    """A decoded COSE_Sign1 message."""

    protected: dict[Any, Any]
    protected_bytes: bytes
    unprotected: dict[Any, Any]
    payload: Optional[bytes]
    signature: bytes

    @classmethod
    def decode(cls, data: bytes) -> CoseSign1:
        item = cbor_decode(data)
        if isinstance(item, Tag):
            if item.tag != COSE_SIGN1_TAG:
                raise CborError(f"CBOR tag {item.tag} is not COSE_Sign1 ({COSE_SIGN1_TAG})")
            item = item.value
        if not (isinstance(item, list) and len(item) == 4):
            raise CborError("COSE_Sign1 must be a four-element array")
        protected_bytes, unprotected, payload, signature = item
        if not isinstance(protected_bytes, bytes) or not isinstance(unprotected, dict):
            raise CborError("malformed COSE_Sign1 headers")
        if not (payload is None or isinstance(payload, bytes)) or not isinstance(signature, bytes):
            raise CborError("malformed COSE_Sign1 payload or signature")
        protected = cbor_decode(protected_bytes) if protected_bytes else {}
        if not isinstance(protected, dict):
            raise CborError("COSE protected header is not a map")
        return cls(protected, protected_bytes, unprotected, payload, signature)

    def to_be_signed(self, detached_payload: Optional[bytes] = None) -> bytes:
        payload = self.payload if self.payload is not None else detached_payload
        if payload is None:
            raise CborError("detached COSE_Sign1 payload not supplied")
        return sig_structure(self.protected_bytes, payload)

    def verify(
        self, verify_fn: Callable[[bytes, bytes], bool], detached_payload: Optional[bytes] = None
    ) -> bool:
        """``verify_fn(signature, message)`` over the Sig_structure; EdDSA only."""
        if self.protected.get(HEADER_ALG) != ALG_EDDSA:
            return False
        return verify_fn(self.signature, self.to_be_signed(detached_payload))

    def encode(self) -> bytes:
        return cbor_encode(
            Tag(COSE_SIGN1_TAG, [self.protected_bytes, self.unprotected, self.payload, self.signature])
        )


def sign1(
    *,
    protected: dict[Any, Any],
    payload: bytes,
    sign_fn: Callable[[bytes], bytes],
    unprotected: Optional[dict[Any, Any]] = None,
    detached: bool = False,
) -> bytes:
    """A tagged COSE_Sign1 over ``payload``; ``detached`` leaves the payload out (``nil``)."""
    protected = {HEADER_ALG: ALG_EDDSA, **protected}
    protected_bytes = cbor_encode(protected)
    signature = sign_fn(sig_structure(protected_bytes, payload))
    message: list[Union[bytes, dict[Any, Any], None]] = [
        protected_bytes,
        unprotected or {},
        None if detached else payload,
        signature,
    ]
    return cbor_encode(Tag(COSE_SIGN1_TAG, message))
