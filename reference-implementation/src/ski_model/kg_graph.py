"""The spec §3 typed-graph Knowledge Graph, compiled to the evaluator's obligations.

A graph KG is ``{"metadata": {...}, "nodes": {...}, "edges": [...]}`` plus a
``signature`` block (spec §3): ``nodes`` holds lists of typed nodes
(``subjects``, ``rules``, ``obligations``, ``definitions``, ``exemptions``,
``precedents``, ``jurisdictions``, ``citations``) and ``edges`` holds
``{"type", "from", "to"}`` relations between their ids.

The evaluator and verifier work on a flat list of obligations. This module
derives that list from the graph; the graph itself is what is signed and
hashed. Each ``Obligation`` node becomes one obligation:

* ``id``, ``metric``, ``value``, ``unit``, ``summary``, ``window_seconds`` and
  ``requires_recent_within_seconds`` are copied from the node;
* ``predicate`` is the node's ``obligation_type`` (spec §3.3);
* ``effective_date`` / ``sunset_date`` are ``effective_date_start`` /
  ``effective_date_end`` (spec §3.4);
* ``jurisdiction`` lists every jurisdiction the obligation is ``scoped_to``
  (spec §3.2: Obligation → Jurisdiction; an edge from the owning Rule is
  also honoured) together with their descendants by ``parent``, so an
  obligation scoped to a country applies to its states. With no
  ``scoped_to`` edge the key is absent and the obligation is global;
* ``risk_tier`` is the strictest ``risk_tier`` (spec §5.4: ``low`` /
  ``medium`` / ``high``) of the Rules that ``consists_of`` it, absent when
  no Rule declares one (the risk-tier governor then applies tier-1);
* ``rule_ids`` lists those Rules.

Every Rule must ``consists_of`` at least one Obligation (spec §3.3); a Rule
without one has nothing the verifier can check, so the graph is refused.

Malformed graphs fail closed with :class:`ValueError`; full structural
validation is ``kg-validator``'s job.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The node lists a graph KG may carry (spec §3.1).
NODE_KINDS = (
    "subjects",
    "rules",
    "obligations",
    "definitions",
    "exemptions",
    "precedents",
    "jurisdictions",
    "citations",
)

_TIER_RANK = {"high": 0, "medium": 1, "low": 2}

# Obligation-node fields copied as-is into the compiled obligation.
_COPIED_FIELDS = ("metric", "value", "unit", "summary", "window_seconds", "requires_recent_within_seconds")


def is_graph_kg(data: Mapping[str, Any]) -> bool:
    """True for the spec §3 graph shape (``nodes``/``edges``), False for the flat ``rules`` shape."""
    return "nodes" in data


def compile_graph(nodes: Any, edges: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(obligations, definitions)`` for the evaluator from a graph's ``nodes`` and ``edges``."""
    if not isinstance(nodes, dict):
        raise ValueError("KG 'nodes' must be an object of node lists.")
    if not isinstance(edges, list):
        raise ValueError("KG 'edges' must be an array.")
    unknown = sorted(set(nodes) - set(NODE_KINDS))
    if unknown:
        raise ValueError(f"KG 'nodes' has unknown node list(s): {unknown}.")

    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for kind in NODE_KINDS:
        items = nodes.get(kind, [])
        if not isinstance(items, list):
            raise ValueError(f"KG nodes.{kind} must be an array.")
        for node in items:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
                raise ValueError(f"KG nodes.{kind} has a node without a string 'id'.")
            if node["id"] in by_id:
                raise ValueError(f"KG node id {node['id']!r} is not unique.")
            by_id[node["id"]] = (kind, node)

    def ids_of(kind: str) -> set[str]:
        return {node_id for node_id, (k, _) in by_id.items() if k == kind}

    rule_ids, jurisdiction_ids = ids_of("rules"), ids_of("jurisdictions")
    owners: dict[str, list[str]] = {}  # obligation id -> rule ids (consists_of)
    scoped: dict[str, set[str]] = {}  # obligation or rule id -> jurisdiction ids (scoped_to)
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("KG edges must be objects.")
        edge_type, source, target = edge.get("type"), edge.get("from"), edge.get("to")
        if not isinstance(edge_type, str) or not isinstance(source, str) or not isinstance(target, str):
            raise ValueError(f"KG edge {edge!r} needs string 'type', 'from' and 'to'.")
        if source not in by_id or target not in by_id:
            raise ValueError(f"KG edge {edge_type} {source!r} -> {target!r} references an unknown node.")
        if edge_type == "consists_of" and source in rule_ids:
            owners.setdefault(target, []).append(source)
        elif edge_type == "scoped_to" and target in jurisdiction_ids:
            scoped.setdefault(source, set()).add(target)

    obligation_ids = ids_of("obligations")
    ruled = {rule_id for target, rules in owners.items() if target in obligation_ids for rule_id in rules}
    empty_rules = sorted(rule_ids - ruled)
    if empty_rules:
        raise ValueError(
            f"KG rule(s) {empty_rules} consist of no obligation; spec §3.3 requires at least one "
            "typed obligation per rule (a consists_of edge to an Obligation node)."
        )

    children: dict[str, set[str]] = {}
    for jurisdiction_id in jurisdiction_ids:
        parent = by_id[jurisdiction_id][1].get("parent")
        if isinstance(parent, str):
            children.setdefault(parent, set()).add(jurisdiction_id)

    def with_descendants(roots: set[str]) -> list[str]:
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(children.get(current, ()))
        return sorted(seen)

    obligations: list[dict[str, Any]] = []
    for node in nodes.get("obligations", []):
        ob_id = node["id"]
        if not isinstance(node.get("metric"), str) or not isinstance(node.get("obligation_type"), str):
            raise ValueError(f"KG obligation {ob_id!r} needs string 'metric' and 'obligation_type'.")
        compiled: dict[str, Any] = {"id": ob_id, "predicate": node["obligation_type"]}
        for field in _COPIED_FIELDS:
            if node.get(field) is not None:
                compiled[field] = node[field]
        if node.get("effective_date_start") is not None:
            compiled["effective_date"] = node["effective_date_start"]
        if node.get("effective_date_end") is not None:
            compiled["sunset_date"] = node["effective_date_end"]

        rules_of = owners.get(ob_id, [])
        roots = set(scoped.get(ob_id, set()))
        for rule_id in rules_of:
            roots |= scoped.get(rule_id, set())
        if roots:
            compiled["jurisdiction"] = with_descendants(roots)
        tiers = [by_id[r][1].get("risk_tier") for r in rules_of]
        ranked = [t for t in tiers if isinstance(t, str) and t in _TIER_RANK]
        if ranked:
            compiled["risk_tier"] = min(ranked, key=_TIER_RANK.__getitem__)
        if rules_of:
            compiled["rule_ids"] = sorted(rules_of)
        obligations.append(compiled)

    if not obligations:
        raise ValueError("KG must contain at least one node in nodes.obligations.")
    definitions = [dict(d) for d in nodes.get("definitions", [])]
    return obligations, definitions
