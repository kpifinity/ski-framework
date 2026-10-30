"""The spec §3 graph-shape Knowledge Graph: compilation, signing and scoping.

A graph KG (``metadata`` / ``nodes`` / ``edges``) is signed over the §7.3
canonical JSON of that content and compiled to the evaluator's obligations.
The flat ``rules`` / ``tag_registry`` shape still loads (compatibility mode,
spec §11.2) and keeps its own signing bytes.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ski_schemas.canonical import canonicalize, sha256_canonical

from ski_model import server
from ski_model.kg_graph import compile_graph
from ski_model.kg_loader import (
    KGTrustError,
    KGTrustPolicy,
    KnowledgeGraph,
    TrustAnchor,
    _canonical_bytes,
    signing_bytes,
)

_REPO = Path(__file__).resolve().parents[5]
_AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _graph() -> Dict[str, Any]:
    return {
        "metadata": {"name": "Graph test KG", "schema_version": "3.0", "version": "g-1"},
        "nodes": {
            "subjects": [{"id": "stack", "type": "Subject", "version": "1", "name": "Stack"}],
            "rules": [
                {"id": "r.so2", "type": "Rule", "version": "1", "name": "SO2", "risk_tier": "low"},
                {"id": "r.strict", "type": "Rule", "version": "1", "name": "Strict", "risk_tier": "high"},
            ],
            "obligations": [
                {
                    "id": "ob.so2",
                    "type": "Obligation",
                    "version": "1",
                    "obligation_type": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "unit": "ppm",
                    "effective_date_start": "2026-01-01T00:00:00Z",
                    "effective_date_end": "2027-01-01T00:00:00Z",
                    "requires_recent_within_seconds": 300,
                },
                {
                    "id": "ob.avg",
                    "type": "Obligation",
                    "version": "1",
                    "obligation_type": "must_average_within",
                    "metric": "nox_ppm",
                    "value": [0, 50],
                    "effective_date_start": "2026-01-01T00:00:00Z",
                    "window_seconds": 3600,
                },
            ],
            "definitions": [{"id": "def.ppm", "type": "Definition", "version": "1", "term": "ppm"}],
            "jurisdictions": [
                {"id": "us", "type": "Jurisdiction", "version": "1", "name": "US"},
                {"id": "us.tx", "type": "Jurisdiction", "version": "1", "name": "Texas", "parent": "us"},
                {"id": "eu", "type": "Jurisdiction", "version": "1", "name": "EU"},
            ],
        },
        "edges": [
            {"type": "applies_to", "from": "r.so2", "to": "stack"},
            {"type": "consists_of", "from": "r.so2", "to": "ob.so2"},
            {"type": "consists_of", "from": "r.strict", "to": "ob.so2"},
            {"type": "consists_of", "from": "r.so2", "to": "ob.avg"},
            {"type": "scoped_to", "from": "ob.so2", "to": "us"},
        ],
    }


def _sign(data: Dict[str, Any], key: Ed25519PrivateKey) -> Dict[str, Any]:
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {
        **data,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": pem.decode("ascii"),
            "value_hex": key.sign(signing_bytes(data)).hex(),
        },
    }


def _anchored(key: Ed25519PrivateKey) -> KGTrustPolicy:
    return KGTrustPolicy(anchors=(TrustAnchor.from_public_key(key.public_key()),))


# ---- compilation -------------------------------------------------------------------


def test_obligation_nodes_compile_to_evaluator_obligations() -> None:
    graph = _graph()
    obligations, definitions = compile_graph(graph["nodes"], graph["edges"])
    by_id = {ob["id"]: ob for ob in obligations}
    assert by_id["ob.so2"] == {
        "id": "ob.so2",
        "predicate": "must_not_exceed",
        "metric": "so2_ppm",
        "value": 100,
        "unit": "ppm",
        "requires_recent_within_seconds": 300,
        "effective_date": "2026-01-01T00:00:00Z",
        "sunset_date": "2027-01-01T00:00:00Z",
        "jurisdiction": ["us", "us.tx"],  # scoped to the US, so its states too
        "risk_tier": "high",  # strictest owning Rule
        "rule_ids": ["r.so2", "r.strict"],
    }
    assert by_id["ob.avg"]["window_seconds"] == 3600
    assert "jurisdiction" not in by_id["ob.avg"]  # no scoped_to edge: global
    assert definitions == [{"id": "def.ppm", "type": "Definition", "version": "1", "term": "ppm"}]


def test_obligation_without_a_tiered_rule_has_no_risk_tier() -> None:
    graph = _graph()
    graph["edges"] = [e for e in graph["edges"] if e["type"] != "consists_of"]
    obligations, _ = compile_graph(graph["nodes"], graph["edges"])
    assert all("risk_tier" not in ob and "rule_ids" not in ob for ob in obligations)


def test_scoped_to_from_the_rule_is_honoured() -> None:
    graph = _graph()
    graph["edges"].append({"type": "scoped_to", "from": "r.so2", "to": "eu"})
    by_id = {ob["id"]: ob for ob in compile_graph(graph["nodes"], graph["edges"])[0]}
    assert by_id["ob.avg"]["jurisdiction"] == ["eu"]
    assert by_id["ob.so2"]["jurisdiction"] == ["eu", "us", "us.tx"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda g: g["nodes"]["obligations"].append(dict(g["nodes"]["obligations"][0])), "not unique"),
        (
            lambda g: g["edges"].append({"type": "consists_of", "from": "r.so2", "to": "missing"}),
            "unknown node",
        ),
        (lambda g: g["nodes"]["obligations"][0].pop("metric"), "metric"),
        (lambda g: g["nodes"].__setitem__("widgets", []), "unknown node list"),
        (lambda g: g.update(edges=[]) or g["nodes"].__setitem__("obligations", []), "at least one"),
        (lambda g: g.__setitem__("edges", {}), "'edges' must be an array"),
    ],
)
def test_malformed_graph_is_refused(mutate: Any, message: str) -> None:
    graph = _graph()
    mutate(graph)
    with pytest.raises(ValueError, match=message):
        KnowledgeGraph.from_dict(graph, require_signature=False, trust=KGTrustPolicy())


# ---- signing -----------------------------------------------------------------------


def test_graph_signing_bytes_are_the_canonical_graph_content() -> None:
    graph = _graph()
    assert signing_bytes(graph) == canonicalize(
        {"metadata": graph["metadata"], "nodes": graph["nodes"], "edges": graph["edges"]}
    )


def test_signed_graph_loads_against_its_anchor() -> None:
    key = Ed25519PrivateKey.generate()
    kg = KnowledgeGraph.from_dict(_sign(_graph(), key), require_signature=True, trust=_anchored(key))
    assert kg.signature_verified and kg.kg_trust == "anchored"
    assert kg.version == "g-1"
    assert [ob["id"] for ob in kg.rules] == ["ob.so2", "ob.avg"]


@pytest.mark.parametrize(
    "edit",
    [
        lambda g: g["nodes"]["obligations"][0].__setitem__("value", 1000),
        lambda g: g["edges"].pop(),  # drop a scoped_to edge: the obligation would go global
        lambda g: g["nodes"]["rules"][1].__setitem__("risk_tier", "low"),
        lambda g: g["metadata"].__setitem__("version", "g-2"),
    ],
)
def test_any_edit_to_a_signed_graph_is_refused(edit: Any) -> None:
    key = Ed25519PrivateKey.generate()
    signed = _sign(_graph(), key)
    tampered = copy.deepcopy(signed)
    edit(tampered)
    with pytest.raises(KGTrustError):
        KnowledgeGraph.from_dict(tampered, require_signature=True, trust=_anchored(key))


def test_flat_kg_keeps_its_signing_bytes() -> None:
    flat: Dict[str, Any] = {
        "metadata": {"version": "f-1"},
        "rules": [{"id": "r", "metric": "m"}],
        "tag_registry": {"s": "r"},
    }
    assert signing_bytes(flat) == _canonical_bytes(flat["metadata"], flat["rules"], flat["tag_registry"])
    key = Ed25519PrivateKey.generate()
    kg = KnowledgeGraph.from_dict(_sign(flat, key), require_signature=True, trust=_anchored(key))
    assert kg.graph is None and kg.tag_registry == {"s": "r"}


# ---- runtime use -------------------------------------------------------------------


def test_scope_to_uses_compiled_jurisdictions_dates_and_definitions() -> None:
    kg = KnowledgeGraph.from_dict(_graph(), require_signature=False, trust=KGTrustPolicy())
    in_texas = kg.scope_to(jurisdiction="us.tx", as_of=_AS_OF)
    assert [ob["id"] for ob in in_texas["obligations"]] == ["ob.so2", "ob.avg"]
    assert in_texas["definitions"] == [{"id": "def.ppm", "type": "Definition", "version": "1", "term": "ppm"}]
    in_eu = kg.scope_to(jurisdiction="eu", as_of=_AS_OF)
    assert [ob["id"] for ob in in_eu["obligations"]] == ["ob.avg"]
    after_sunset = kg.scope_to(jurisdiction="us", as_of=datetime(2027, 6, 1, tzinfo=timezone.utc))
    assert [ob["id"] for ob in after_sunset["obligations"]] == ["ob.avg"]


def test_kg_version_hash_of_a_graph_is_the_digest_of_its_signed_content() -> None:
    graph = _graph()
    kg = KnowledgeGraph.from_dict(graph, require_signature=False, trust=KGTrustPolicy())
    expected = sha256_canonical(
        {"metadata": graph["metadata"], "nodes": graph["nodes"], "edges": graph["edges"]}
    )
    assert server._compute_kg_version_hash(kg) == expected


@pytest.mark.parametrize("path", sorted((_REPO / "examples").glob("*/knowledge-graphs/*-v3-demo.json")))
def test_every_committed_demo_kg_loads(path: Path) -> None:
    kg = KnowledgeGraph.from_dict(
        json.loads(path.read_text(encoding="utf-8")), require_signature=False, trust=KGTrustPolicy()
    )
    assert kg.rules and all(ob["metric"] and ob["predicate"] for ob in kg.rules)
    assert kg.scope_to(jurisdiction="us.federal", as_of=_AS_OF)["obligations"]
