"""The suite's own machinery, checked without an implementation: checkers against the spec vectors, the LLM hook, independence.

These run in every CI job; they are what lets a black-box result be trusted.
"""

from __future__ import annotations

import ast
import json
import math
import socket
from pathlib import Path

import httpx
import pytest

from . import checkers
from .scripted_llm import serve

pytestmark = pytest.mark.blackbox

HERE = Path(__file__).resolve().parent
VECTORS = HERE.parents[1] / "spec" / "test-vectors"
# The reference implementation's packages: the suite must not depend on any of them.
_REFERENCE_PACKAGES = {"ski_model", "ski_schemas", "ski_sdk", "audit_ledger", "kg_extractor", "kg_validator"}


def _vectors(kind: str) -> list[Path]:
    return sorted(p for p in (VECTORS / kind).glob("*.json"))


@pytest.mark.parametrize("path", _vectors("canonical"), ids=lambda p: p.stem)
def test_canonicalizer_reproduces_the_vectors(path: Path) -> None:
    vector = json.loads(path.read_text(encoding="utf-8"))
    value = checkers.parse_json(json.dumps(vector["input"], ensure_ascii=False))
    canonical = checkers.canonicalize(value)
    assert canonical.decode("utf-8") == vector["canonical"]
    assert checkers.sha256_prefixed(canonical) == vector["sha256"]


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, 2**53 + 1, "\ud800", {1: "x"}],
    ids=["nan", "inf", "-inf", "inexact-int", "lone-surrogate", "non-string-key"],
)
def test_canonicalizer_rejects(value: object) -> None:
    with pytest.raises(checkers.NotCanonicalizable):
        checkers.canonicalize(value)


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '﻿{"a":1}'], ids=["duplicate-name", "bom"])
def test_parser_rejects(text: str) -> None:
    with pytest.raises(checkers.NotCanonicalizable):
        checkers.parse_json(text)


@pytest.mark.parametrize("path", _vectors("merkle"), ids=lambda p: p.stem)
def test_merkle_checker_reproduces_the_vectors(path: Path) -> None:
    vector = json.loads(path.read_text(encoding="utf-8"))
    hashes = vector["entry_hashes"]
    root = vector["root_hash"]
    assert checkers.merkle_root(hashes) == root
    for index, proof in enumerate(vector["proofs"]):
        implied = checkers.root_from_inclusion_proof(
            bytes.fromhex(hashes[index]), index, len(hashes), [bytes.fromhex(p) for p in proof]
        )
        assert implied.hex() == root
    assert (
        checkers.canonicalize(checkers.parse_json(vector["checkpoint_statement"])).decode()
        == vector["checkpoint_statement"]
    )


def test_merkle_checker_rejects_a_wrong_proof() -> None:
    vector = json.loads((VECTORS / "merkle" / "tree_size_5.json").read_text(encoding="utf-8"))
    hashes, proof = vector["entry_hashes"], [bytes.fromhex(p) for p in vector["proofs"][2]]
    implied = checkers.root_from_inclusion_proof(bytes.fromhex(hashes[3]), 2, len(hashes), proof)
    assert implied.hex() != vector["root_hash"]


def test_scripted_llm_answers_from_its_script() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = serve("scripted-test", port)
    try:
        base = f"http://127.0.0.1:{port}"
        assert httpx.get(f"{base}/v1/models").json()["data"][0]["id"] == "scripted-test"
        httpx.post(f"{base}/__script", json={"token": "tok-1", "content": "hello"}).raise_for_status()
        body = {"model": "m", "messages": [{"role": "user", "content": "record tok-1 here"}]}
        reply = httpx.post(f"{base}/v1/chat/completions", json=body).json()
        assert reply["choices"][0]["message"]["content"] == "hello"
        unscripted = {"model": "m", "messages": [{"role": "user", "content": "tok-2"}]}
        assert httpx.post(f"{base}/v1/chat/completions", json=unscripted).status_code == 503
        assert len(httpx.get(f"{base}/__requests", params={"token": "tok-1"}).json()) == 1
    finally:
        server.shutdown()


def test_suite_imports_no_reference_code() -> None:
    """The point of the suite: an implementation is judged by the spec and vectors, not by the reference's code."""
    offenders = []
    for path in sorted(HERE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in _REFERENCE_PACKAGES]
    assert not offenders, offenders
