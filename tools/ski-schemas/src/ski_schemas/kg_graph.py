"""The one Knowledge Graph shape (spec §3) and its one version hash.

The runtime, ``kg-validator`` and ``kg-extractor`` share the spec §3 graph:
``{"metadata", "nodes", "edges"}`` plus a ``signature`` block. Its version
hash, recorded as ``model_provenance.kg_version_hash`` and in every ledger
entry, is :func:`kg_version_hash`: ``"sha256:"`` + SHA-256 of the §7.3
canonical JSON of ``{"metadata", "nodes", "edges"}`` (exactly the signed
content, without the signature).

The earlier flat shape (``{"metadata", "rules", "tag_registry"}``, spec §11.2)
is converted to the graph by :func:`flat_to_graph`. Each flat rule becomes one
Obligation (same id, so recorded citations still resolve) owned by one Rule
(``rule.<id>``):

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
§3.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from .canonical import sha256_canonical

__all__ = ["flat_to_graph", "kg_version_hash"]


def kg_version_hash(graph: Mapping[str, Any]) -> str:
    """``sha256:<hex>`` of the §7.3 canonical ``{metadata, nodes, edges}`` (any ``signature`` excluded)."""
    return sha256_canonical({k: graph[k] for k in ("metadata", "nodes", "edges")})


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


def flat_to_graph(flat: Mapping[str, Any], default_effective_date: Optional[str] = None) -> Dict[str, Any]:
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
