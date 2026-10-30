"""scripts/flat-kg-to-graph.py: a converted KG compiles to the same obligations as the flat one."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "reference-implementation" / "src"))
_spec = importlib.util.spec_from_file_location("flat_kg_to_graph", _REPO / "scripts" / "flat-kg-to-graph.py")
assert _spec and _spec.loader
converter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(converter)

from ski_model.kg_loader import KGTrustPolicy, KnowledgeGraph

_FLAT: Dict[str, Any] = {
    "metadata": {"version": "flat-1"},
    "rules": [
        {
            "id": "a",
            "name": "A cap",
            "metric": "a_ppm",
            "predicate": "must_not_exceed",
            "value": 5,
            "unit": "ppm",
            "jurisdiction": "us.federal",
            "effective_date": "2026-01-01T00:00:00Z",
            "risk_tier": "tier-2",
        },
        {
            "id": "b",
            "metric": "b",
            "predicate": "must_be_within",
            "value": [1, 2],
            "jurisdiction": "global",
            "sunset_date": "2026-03-01T00:00:00Z",
            "requires_recent_within_seconds": 60,
        },
        {
            "id": "c",
            "metric": "c",
            "predicate": "must_be_at_least",
            "value": 3,
            "jurisdiction": ["ca.alberta", "us.federal"],
        },
    ],
    "tag_registry": {"stack.a": "a"},
}


def _load(data: Dict[str, Any]) -> KnowledgeGraph:
    return KnowledgeGraph.from_dict(data, require_signature=False, trust=KGTrustPolicy())


@pytest.mark.parametrize("jurisdiction", ["us.federal", "ca.alberta", "eu", None])
@pytest.mark.parametrize(
    "as_of", [datetime(2026, 2, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)]
)
def test_converted_kg_scopes_like_the_flat_one(jurisdiction: Any, as_of: datetime) -> None:
    flat = _load(_FLAT).scope_to(jurisdiction=jurisdiction, as_of=as_of)["obligations"]
    graph = _load(converter.convert(_FLAT)).scope_to(jurisdiction=jurisdiction, as_of=as_of)["obligations"]
    assert [ob["id"] for ob in graph] == [ob["id"] for ob in flat]
    for f, g in zip(flat, graph, strict=True):
        for key in ("metric", "predicate", "value", "unit", "requires_recent_within_seconds"):
            assert g.get(key) == f.get(key), (f["id"], key)


def test_tiers_subjects_and_versions() -> None:
    graph = converter.convert(_FLAT)
    rules = {r["id"]: r for r in graph["nodes"]["rules"]}
    assert rules["rule.a"]["risk_tier"] == "medium" and "risk_tier" not in rules["rule.b"]
    assert {"type": "applies_to", "from": "rule.a", "to": "stack.a"} in graph["edges"]
    from ski_schemas.canonical import sha256_canonical

    for nodes in graph["nodes"].values():
        for node in nodes:
            assert node["version"] == sha256_canonical({k: v for k, v in node.items() if k != "version"})


def test_default_effective_date_only_when_asked() -> None:
    undated = {"id": "x", "metric": "x", "predicate": "must_not_exceed", "value": 1}
    flat = {"metadata": {}, "rules": [undated], "tag_registry": {}}
    assert "effective_date_start" not in converter.convert(flat)["nodes"]["obligations"][0]
    dated = converter.convert(flat, "2026-01-01T00:00:00Z")["nodes"]["obligations"][0]
    assert dated["effective_date_start"] == "2026-01-01T00:00:00Z"
