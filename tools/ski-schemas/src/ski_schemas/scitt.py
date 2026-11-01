"""SKI verdicts as SCITT signed statements with COSE Receipts (RFC 9943; COSE Receipts draft).

The SCITT architecture (RFC 9943) carries supply-chain claims as COSE_Sign1
*signed statements*; a transparency service vouches that a statement is in
its append-only log with a *receipt*. SKI's ledger already is an append-only
log with RFC 6962 Merkle checkpoints (:mod:`ski_schemas.merkle`), so a SKI
runtime can issue both for every verdict, verifiable by any COSE/SCITT tool.

**Signed statement** (COSE_Sign1, EdDSA, payload attached):

* protected header: ``alg`` -8, ``content_type``
  ``application/vnd.ski.ledger-entry+json``, ``kid`` (the runtime's key id,
  UTF-8 bytes) and ``CWT_Claims`` (label 15, RFC 9597) with ``iss`` (1)
  ``ski:key:<key id>``, ``sub`` (2) ``ski:ledger:<tenant>:<sequence>`` and
  ``iat`` (6);
* payload: the §7.3 canonical JSON of :func:`statement_payload`, which carries
  the entry's ``entry_hash`` and the verdict envelope.

**Receipt** (COSE_Sign1, EdDSA, payload detached), following the COSE Receipts
draft for verifiable data structure ``RFC9162_SHA256`` (1):

* protected header: ``alg`` -8, ``kid``, ``vds`` (395) = 1;
* unprotected header: ``vdp`` (396) = ``{-1: [bstr .cbor [tree_size,
  leaf_index, [path...]]]}``;
* detached payload: the 32-byte Merkle root of the ledger's first
  ``tree_size`` entries, whose leaves are the raw ``entry_hash`` bytes.

A *transparent statement* is the signed statement with its receipts in the
unprotected ``receipts`` header (394). Header labels 394-396 are the values
the COSE Receipts draft requests; they are constants here so a change on
registration is one edit.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

from .canonical import canonicalize
from .cose import (
    ALG_EDDSA,
    HEADER_CONTENT_TYPE,
    HEADER_KID,
    CborError,
    CoseSign1,
    Tag,
    cbor_decode,
    cbor_encode,
    sign1,
)
from .merkle import inclusion_proof

__all__ = [
    "CONTENT_TYPE",
    "HEADER_RECEIPTS",
    "HEADER_VDP",
    "HEADER_VDS",
    "VDS_RFC9162_SHA256",
    "ReceiptError",
    "make_receipt",
    "make_signed_statement",
    "receipt_root",
    "statement_payload",
    "transparent_statement",
    "verify_transparent_statement",
]

CONTENT_TYPE = "application/vnd.ski.ledger-entry+json"
HEADER_CWT_CLAIMS = 15
HEADER_RECEIPTS = 394
HEADER_VDS = 395
HEADER_VDP = 396
VDS_RFC9162_SHA256 = 1
_INCLUSION_PROOFS = -1
_CWT_ISS, _CWT_SUB, _CWT_IAT = 1, 2, 6


class ReceiptError(ValueError):
    """A statement or receipt that does not verify."""


def statement_payload(*, entry: dict[str, Any], envelope: Optional[dict[str, Any]]) -> bytes:
    """Canonical JSON of the ledger entry's verdict line (with its ``entry_hash``) and envelope."""
    return canonicalize({"ski_statement": 1, "ledger_entry": entry, "envelope": envelope})


def make_signed_statement(
    *,
    entry: dict[str, Any],
    envelope: Optional[dict[str, Any]],
    key_id: str,
    issued_at: int,
    sign_fn: Callable[[bytes], bytes],
) -> bytes:
    """A SCITT signed statement for one ledger entry (``entry`` carries ``tenant_id``, ``sequence_number``)."""
    claims = {
        _CWT_ISS: f"ski:key:{key_id}",
        _CWT_SUB: f"ski:ledger:{entry.get('tenant_id') or 'default'}:{entry['sequence_number']}",
        _CWT_IAT: issued_at,
    }
    return sign1(
        protected={
            HEADER_CONTENT_TYPE: CONTENT_TYPE,
            HEADER_KID: key_id.encode("utf-8"),
            HEADER_CWT_CLAIMS: claims,
        },
        payload=statement_payload(entry=entry, envelope=envelope),
        sign_fn=sign_fn,
    )


def make_receipt(
    *, entry_hashes: list[str], leaf_index: int, key_id: str, sign_fn: Callable[[bytes], bytes]
) -> bytes:
    """A COSE Receipt (RFC9162_SHA256) proving entry ``leaf_index`` is in the tree of ``entry_hashes``."""
    from .merkle import merkle_root

    proof = [
        len(entry_hashes),
        leaf_index,
        [bytes.fromhex(p) for p in inclusion_proof(entry_hashes, leaf_index)],
    ]
    return sign1(
        protected={HEADER_KID: key_id.encode("utf-8"), HEADER_VDS: VDS_RFC9162_SHA256},
        unprotected={HEADER_VDP: {_INCLUSION_PROOFS: [cbor_encode(proof)]}},
        payload=bytes.fromhex(merkle_root(entry_hashes)),
        sign_fn=sign_fn,
        detached=True,
    )


def transparent_statement(statement: bytes, receipts: list[bytes]) -> bytes:
    """``statement`` with ``receipts`` in its unprotected ``receipts`` header (394)."""
    message = CoseSign1.decode(statement)
    unprotected = {**message.unprotected, HEADER_RECEIPTS: receipts}
    return cbor_encode(Tag(18, [message.protected_bytes, unprotected, message.payload, message.signature]))


def _leaf(entry_hash: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + entry_hash).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def receipt_root(receipt: CoseSign1, entry_hash: str) -> tuple[bytes, int, int]:
    """``(root, tree_size, leaf_index)`` the receipt's inclusion proof gives for ``entry_hash`` (RFC 9162 §2.1.3.2)."""
    if receipt.protected.get(HEADER_VDS) != VDS_RFC9162_SHA256:
        raise ReceiptError("receipt is not for the RFC9162_SHA256 verifiable data structure")
    proofs = (receipt.unprotected.get(HEADER_VDP) or {}).get(_INCLUSION_PROOFS)
    if not (isinstance(proofs, list) and proofs and isinstance(proofs[0], bytes)):
        raise ReceiptError("receipt carries no inclusion proof")
    content = cbor_decode(proofs[0])
    if not (isinstance(content, list) and len(content) == 3):
        raise ReceiptError("malformed inclusion proof")
    tree_size, leaf_index, path = content
    if not (isinstance(tree_size, int) and isinstance(leaf_index, int) and 0 <= leaf_index < tree_size):
        raise ReceiptError("inclusion proof index is outside the tree")
    fn, sn = leaf_index, tree_size - 1
    r = _leaf(bytes.fromhex(entry_hash))
    for p in path:
        if sn == 0 or not isinstance(p, bytes):
            raise ReceiptError("inclusion proof path is too long or malformed")
        if fn & 1 or fn == sn:
            r = _node(p, r)
            while not fn & 1 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = _node(r, p)
        fn >>= 1
        sn >>= 1
    if sn != 0:
        raise ReceiptError("inclusion proof path is too short")
    return r, tree_size, leaf_index


def verify_transparent_statement(
    data: bytes, verify_fn: Callable[[bytes, bytes], bool]
) -> tuple[dict[str, Any], list[tuple[bytes, int]]]:
    """Verify a (transparent) statement and every receipt on it with ``verify_fn(signature, message)``.

    Returns the decoded payload and ``(root, tree_size)`` per receipt; the
    caller compares a root with a checkpoint it trusts. Raises
    :class:`ReceiptError` on any failure.
    """
    import json

    try:
        statement = CoseSign1.decode(data)
    except CborError as exc:
        raise ReceiptError(f"not a COSE_Sign1 statement: {exc}") from exc
    if statement.payload is None or not statement.verify(verify_fn):
        raise ReceiptError("statement signature does not verify")
    if statement.protected.get(HEADER_CONTENT_TYPE) != CONTENT_TYPE:
        raise ReceiptError("statement is not a SKI ledger entry")
    payload = json.loads(statement.payload)
    entry_hash = str(payload["ledger_entry"]["entry_hash"])
    roots: list[tuple[bytes, int]] = []
    for raw in statement.unprotected.get(HEADER_RECEIPTS) or []:
        receipt = CoseSign1.decode(raw)
        root, tree_size, leaf_index = receipt_root(receipt, entry_hash)
        if leaf_index != int(payload["ledger_entry"]["sequence_number"]) - 1:
            raise ReceiptError("receipt proves a different ledger position than the statement")
        if receipt.protected.get(1) != ALG_EDDSA or not receipt.verify(verify_fn, detached_payload=root):
            raise ReceiptError("receipt signature does not verify")
        roots.append((root, tree_size))
    return payload, roots
