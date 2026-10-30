#!/usr/bin/env python3
"""Convert a flat Knowledge Graph (``rules`` + ``tag_registry``) to the spec §3 graph shape.

The flat shape still loads in compatibility mode (spec §11.2); this script
moves a KG to the graph shape the spec, kg-validator and the runtime share.
Each flat rule becomes one Obligation (same id, so recorded citations still
resolve) owned by one Rule (``rule.<id>``):

* ``predicate`` -> ``obligation_type``; ``effective_date`` / ``sunset_date``
  -> ``effective_date_start`` / ``effective_date_end``; ``name`` -> ``summary``;
  ``metric``, ``value``, ``unit``, ``window_seconds`` and
  ``requires_recent_within_seconds`` are kept;
* ``jurisdiction`` (a string or a list) becomes Jurisdiction nodes and
  ``scoped_to`` edges from the Obligation; ``global`` / ``*`` / empty means
  no edge (applies everywhere);
* ``risk_tier`` moves to the Rule, mapped to spec §5.4's ``high`` /
  ``medium`` / ``low``; no tier stays no tier (the runtime applies tier-1);
* each ``tag_registry`` subject becomes a Subject with an ``applies_to``
  edge from the rules it routed to.

Node versions are the SHA-256 of each node's §7.3 canonical content (spec
§3.1). The output is unsigned: sign it with ``ski-model-deploy sign``.

Usage:
    python scripts/flat-kg-to-graph.py IN.json OUT.json [--default-effective-date 2026-01-01T00:00:00Z]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "ski-schemas" / "src"))

from ski_schemas.canonical import sha256_canonical

_UNIVERSAL = {"global", "*", ""}
_TIERS = {
    "tier-1": "high",
    "tier1": "high",
    "high": "high",
    "high-risk": "high",
    "tier-2": "medium",
    "tier2": "medium",
    "standard": "medium",
    "default": "medium",
    "medium": "medium",
    "tier-3": "low",
    "tier3": "low",
    "low": "low",
    "low-risk": "low",
}
_KEPT = ("metric", "value", "unit", "window_seconds", "requires_recent_within_seconds")


def _versioned(node: Dict[str, Any]) -> Dict[str, Any]:
    return {**node, "version": sha256_canonical(node)}


def convert(flat: Dict[str, Any], default_effective_date: Optional[str] = None) -> Dict[str, Any]:
    """The graph-shape KG for a flat ``{metadata, rules, tag_registry}`` KG."""
    metadata = dict(flat.get("metadata") or {})
    metadata.setdefault("name", str(metadata.get("version") or "converted-kg"))
    metadata["schema_version"] = "3.0"
    rules: List[Dict[str, Any]] = flat.get("rules") or []
    edges: List[Dict[str, str]] = []
    nodes: Dict[str, List[Dict[str, Any]]] = {
        "subjects": [],
        "rules": [],
        "obligations": [],
        "jurisdictions": [],
    }
    jurisdictions: Dict[str, Dict[str, Any]] = {}

    for flat_rule in rules:
        ob_id = str(flat_rule["id"])
        rule_id = f"rule.{ob_id}"
        obligation: Dict[str, Any] = {
            "id": ob_id,
            "type": "Obligation",
            "obligation_type": flat_rule.get("predicate", "must_not_exceed"),
        }
        obligation.update({k: flat_rule[k] for k in _KEPT if flat_rule.get(k) is not None})
        start = flat_rule.get("effective_date") or default_effective_date
        if start:
            obligation["effective_date_start"] = start
        if flat_rule.get("sunset_date"):
            obligation["effective_date_end"] = flat_rule["sunset_date"]
        if flat_rule.get("name"):
            obligation["summary"] = flat_rule["name"]
        nodes["obligations"].append(_versioned(obligation))

        rule: Dict[str, Any] = {"id": rule_id, "type": "Rule", "name": str(flat_rule.get("name") or ob_id)}
        tier = flat_rule.get("risk_tier")
        if isinstance(tier, str) and tier.strip().lower() in _TIERS:
            rule["risk_tier"] = _TIERS[tier.strip().lower()]
        nodes["rules"].append(_versioned(rule))
        edges.append({"type": "consists_of", "from": rule_id, "to": ob_id})

        scope = flat_rule.get("jurisdiction")
        for jurisdiction in [scope] if isinstance(scope, str) else (scope or []):
            if jurisdiction in _UNIVERSAL:
                continue
            jurisdictions.setdefault(
                jurisdiction, _versioned({"id": jurisdiction, "type": "Jurisdiction", "name": jurisdiction})
            )
            edges.append({"type": "scoped_to", "from": ob_id, "to": jurisdiction})

    for subject, routed_rule in sorted((flat.get("tag_registry") or {}).items()):
        nodes["subjects"].append(_versioned({"id": subject, "type": "Subject", "name": subject}))
        edges.append({"type": "applies_to", "from": f"rule.{routed_rule}", "to": subject})
    nodes["jurisdictions"] = [jurisdictions[j] for j in sorted(jurisdictions)]
    return {"metadata": metadata, "nodes": nodes, "edges": edges}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--default-effective-date",
        help="effective_date_start for rules that have no effective_date (spec §3.4 requires one).",
    )
    args = parser.parse_args(argv)
    flat = json.loads(args.input.read_text(encoding="utf-8"))
    if "nodes" in flat:
        parser.error(f"{args.input} is already a graph KG.")
    graph = convert(flat, args.default_effective_date)
    args.output.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(graph['nodes']['obligations'])} obligations (unsigned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
