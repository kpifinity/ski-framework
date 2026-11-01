"""Ledger checkpoints: an RFC 6962 Merkle tree over the entry hashes (spec §7).

The hash chain proves each entry follows the one before it, but whoever can
write the table can rewrite an entry *and every entry after it* and leave a
consistent chain. A checkpoint closes that gap: at regular intervals the
runtime signs the Merkle root of every entry so far, and the checkpoint is
exported outside the database (WORM storage, an RFC 3161 timestamp). A
forward rewrite then no longer reproduces an exported root.

Hashing is RFC 6962 §2.1 (Certificate Transparency), over the 32 raw bytes
of each ``entry_hash`` in sequence order:

* leaf: ``SHA-256(0x00 || entry_hash)``;
* node: ``SHA-256(0x01 || left || right)``;
* a tree of ``n > 1`` leaves splits at ``k``, the largest power of two
  ``< n``: ``node(MTH(D[0:k]), MTH(D[k:n]))``.

The signed **checkpoint statement** is the §7.3 canonical JSON of::

    {
      "checkpoint_format": 1,
      "tenant_id": <str>,
      "tree_size": <int: entries 1..tree_size are covered>,
      "root_hash": <64 hex>,
      "last_entry_hash": <64 hex: entry_hash of sequence tree_size>,
      "created_at": <ISO-8601 with offset>
    }

The language-neutral vectors are ``spec/test-vectors/merkle/``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .canonical import canonicalize

__all__ = [
    "CHECKPOINT_FORMAT",
    "checkpoint_statement",
    "inclusion_proof",
    "merkle_root",
    "verify_inclusion",
]

CHECKPOINT_FORMAT = 1


def _leaf(entry_hash: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + entry_hash).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _raw(entry_hashes: Sequence[str]) -> list[bytes]:
    raw = [bytes.fromhex(h) for h in entry_hashes]
    if any(len(r) != 32 for r in raw):
        raise ValueError("Every entry_hash must be 64 hex characters (SHA-256).")
    return raw


def _root(leaves: Sequence[bytes]) -> bytes:
    if len(leaves) == 1:
        return _leaf(leaves[0])
    k = _split(len(leaves))
    return _node(_root(leaves[:k]), _root(leaves[k:]))


def merkle_root(entry_hashes: Sequence[str]) -> str:
    """Hex RFC 6962 Merkle tree head of ``entry_hashes`` (sequence order). Empty is ``sha256("")``."""
    if not entry_hashes:
        return hashlib.sha256(b"").hexdigest()
    return _root(_raw(entry_hashes)).hex()


def inclusion_proof(entry_hashes: Sequence[str], index: int) -> list[str]:
    """The RFC 6962 audit path (hex, leaf to root) for the entry at zero-based ``index``."""
    leaves = _raw(entry_hashes)
    if not 0 <= index < len(leaves):
        raise IndexError(f"index {index} outside a tree of {len(leaves)} entries.")

    def path(nodes: Sequence[bytes], m: int) -> list[bytes]:
        if len(nodes) == 1:
            return []
        k = _split(len(nodes))
        if m < k:
            return [*path(nodes[:k], m), _root(nodes[k:])]
        return [*path(nodes[k:], m - k), _root(nodes[:k])]

    return [p.hex() for p in path(leaves, index)]


def verify_inclusion(
    entry_hash: str, index: int, tree_size: int, proof: Sequence[str], root_hash: str
) -> bool:
    """True when ``proof`` shows ``entry_hash`` at ``index`` in the tree of ``tree_size`` with ``root_hash``.

    RFC 9162 §2.1.3.2 verification algorithm.
    """
    if not 0 <= index < tree_size:
        return False
    fn, sn = index, tree_size - 1
    r = _leaf(bytes.fromhex(entry_hash))
    for p_hex in proof:
        p = bytes.fromhex(p_hex)
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            if not fn & 1:
                while fn & 1 == 0 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = _node(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r.hex() == root_hash


def checkpoint_statement(
    *, tenant_id: str, tree_size: int, root_hash: str, last_entry_hash: str, created_at: str
) -> bytes:
    """The §7.3 canonical bytes a checkpoint signature (and its RFC 3161 timestamp) covers."""
    return canonicalize(
        {
            "checkpoint_format": CHECKPOINT_FORMAT,
            "tenant_id": tenant_id,
            "tree_size": tree_size,
            "root_hash": root_hash,
            "last_entry_hash": last_entry_hash,
            "created_at": created_at,
        }
    )
