"""RFC 6962 Merkle checkpoints: roots, inclusion proofs, and what a forward rewrite does to them."""

from __future__ import annotations

import hashlib

import pytest
from ski_schemas.merkle import checkpoint_statement, inclusion_proof, merkle_root, verify_inclusion


def _hashes(n: int) -> list[str]:
    return [hashlib.sha256(f"e{i}".encode()).hexdigest() for i in range(n)]


def test_single_leaf_root_is_the_rfc6962_leaf_hash() -> None:
    (h,) = _hashes(1)
    assert merkle_root([h]) == hashlib.sha256(b"\x00" + bytes.fromhex(h)).hexdigest()


def test_two_leaf_root_is_one_node() -> None:
    a, b = _hashes(2)
    leaf = lambda x: hashlib.sha256(b"\x00" + bytes.fromhex(x)).digest()  # noqa: E731
    assert merkle_root([a, b]) == hashlib.sha256(b"\x01" + leaf(a) + leaf(b)).hexdigest()


def test_empty_tree_is_the_hash_of_nothing() -> None:
    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("n", range(1, 34))
def test_every_inclusion_proof_verifies(n: int) -> None:
    hashes = _hashes(n)
    root = merkle_root(hashes)
    for i, h in enumerate(hashes):
        assert verify_inclusion(h, i, n, inclusion_proof(hashes, i), root)


@pytest.mark.parametrize("n", [2, 3, 7, 16])
def test_a_proof_does_not_verify_another_entry_or_position(n: int) -> None:
    hashes = _hashes(n)
    root = merkle_root(hashes)
    proof = inclusion_proof(hashes, 1)
    assert not verify_inclusion(hashes[0], 1, n, proof, root)
    assert not verify_inclusion(hashes[1], 0, n, proof, root)
    assert not verify_inclusion(hashes[1], 1, n, proof, merkle_root(hashes[:-1]))


def test_rewriting_any_entry_changes_the_root() -> None:
    """A forward rewrite that keeps the chain consistent still moves every later root."""
    hashes = _hashes(10)
    root = merkle_root(hashes)
    for i in range(10):
        rewritten = [*hashes[:i], hashlib.sha256(b"forged").hexdigest(), *hashes[i + 1 :]]
        assert merkle_root(rewritten) != root


def test_entry_hashes_must_be_sha256() -> None:
    with pytest.raises(ValueError, match="64 hex"):
        merkle_root(["abcd"])


def test_checkpoint_statement_is_canonical_json() -> None:
    statement = checkpoint_statement(
        tenant_id="t",
        tree_size=2,
        root_hash="a" * 64,
        last_entry_hash="b" * 64,
        created_at="2026-11-01T00:00:00+00:00",
    )
    assert statement == (
        b'{"checkpoint_format":1,"created_at":"2026-11-01T00:00:00+00:00","last_entry_hash":"'
        + b"b" * 64
        + b'","root_hash":"'
        + b"a" * 64
        + b'","tenant_id":"t","tree_size":2}'
    )
