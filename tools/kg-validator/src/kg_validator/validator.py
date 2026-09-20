"""V3 validator — runs the spec §3.6 validation passes against a loaded KG.

Implements the subset that does not require sophisticated unit handling:

* Duplicate node IDs across all node types.
* Edges pointing at undefined node IDs (dangling edges).
* Edge target type matches what the edge type expects
  (``applies_to`` must point at a Subject, ``consists_of`` at an
  Obligation, etc.).
* Rules with no ``consists_of`` edge (every rule must have at least
  one obligation per spec §2.1.2).
* Obligations with no incoming ``consists_of`` edge from a Rule
  (orphan obligations).

Deferred to follow-up PRs:

* Contradictory obligations (needs sophisticated unit handling).
* Date-interval overlaps for mutually exclusive obligations.
* Cyclic precedent edges.
* Definition scope checking.

Obligation-type validity and missing ``effective_date_start`` are
already enforced at the Pydantic layer by :mod:`kg_validator.models`,
so they surface as :class:`pydantic.ValidationError` at
:func:`load_v3_kg` time rather than as runtime issues here.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .loader import KnowledgeGraphV3
from .models import (
    EdgeType,
    ObligationType,
    RiskTier,
    V3IssueType,
    V3ValidationIssue,
    V3ValidationResult,
)

# Expected target-type per edge type. ``cited_by`` accepts any source
# node, so it does not appear here.
_EDGE_TARGET_TYPE: Dict[EdgeType, str] = {
    EdgeType.APPLIES_TO: "Subject",
    EdgeType.CONSISTS_OF: "Obligation",
    EdgeType.DEFINED_BY: "Definition",
    EdgeType.EXEMPTED_BY: "Exemption",
    EdgeType.AMENDED_BY: "Obligation",
    EdgeType.INTERPRETED_BY: "Precedent",
    EdgeType.SCOPED_TO: "Jurisdiction",
    EdgeType.CITED_BY: "Citation",
}

# Obligation types the Symbolic Verifier can mechanically check -- mirrors
# the check-function registries in
# reference-implementation/src/ski_model/v3/verifier.py
# (_STATELESS_CHECKS' keys plus _STATEFUL_PREDICATES). Deliberately the
# verifier's *actual* implemented set, not spec §3.3's full enumeration:
# `must_be_recorded_within` is spec-defined but not yet wired to a check
# function, so it is treated as non-formalizable (qualitative) here until
# it is. Anything not in this set -- `must`, `must_not`,
# `must_be_recorded_within`, `should`, `discretionary` -- cannot be
# mechanically verified; the runtime's RiskTierGovernor can only backstop
# that with a strict enough risk_tier, which this check exists to flag.
_MECHANICALLY_CHECKABLE_OBLIGATION_TYPES: Set[str] = {
    ObligationType.MUST_NOT_EXCEED.value,
    ObligationType.MUST_BE_AT_LEAST.value,
    ObligationType.MUST_BE_BELOW.value,
    ObligationType.MUST_BE_ABOVE.value,
    ObligationType.MUST_BE_WITHIN.value,
    ObligationType.MUST_BE_ONE_OF.value,
    ObligationType.MUST_NOT_BE_ONE_OF.value,
    ObligationType.MUST_EQUAL.value,
    ObligationType.MUST_NOT_EQUAL.value,
    ObligationType.MUST_AVERAGE_WITHIN.value,
    ObligationType.MUST_NOT_EXCEED_IN_WINDOW.value,
}


class V3Validator:
    """Run the §3.6 validation passes against a loaded v3 KG.

    ``strict``: when ``True``, findings that are normally advisory
    warnings (currently just
    :attr:`~kg_validator.models.V3IssueType.UNDER_TIERED_QUALITATIVE_OBLIGATION`)
    are raised to ``HIGH`` severity, which fails
    :attr:`~kg_validator.models.V3ValidationResult.is_clean` and the CLI's
    exit code. Default ``False`` preserves prior behaviour for existing
    callers.
    """

    def __init__(self, kg: KnowledgeGraphV3, *, strict: bool = False) -> None:
        self._kg = kg
        self._strict = strict
        self._issues: List[V3ValidationIssue] = []

    def run(self) -> V3ValidationResult:
        """Execute every validation pass and return the aggregated result."""
        self._issues = []
        self._check_duplicate_node_ids()
        node_types = self._kg.all_node_ids()
        self._check_dangling_edges(node_types)
        self._check_edge_target_types(node_types)
        self._check_under_tiered_qualitative_obligations()
        self._check_rule_obligation_coverage()

        total_nodes = sum(
            (
                len(self._kg.nodes.subjects),
                len(self._kg.nodes.rules),
                len(self._kg.nodes.obligations),
                len(self._kg.nodes.definitions),
                len(self._kg.nodes.exemptions),
                len(self._kg.nodes.precedents),
                len(self._kg.nodes.jurisdictions),
                len(self._kg.nodes.citations),
            )
        )
        return V3ValidationResult(
            total_nodes=total_nodes,
            total_edges=len(self._kg.edges),
            total_issues=len(self._issues),
            issues=list(self._issues),
        )

    # ------------------------------------------------------------------ #
    # Individual validation passes                                       #
    # ------------------------------------------------------------------ #

    def _check_duplicate_node_ids(self) -> None:
        seen: Set[str] = set()
        for node_id in self._kg.all_node_ids():
            if node_id in seen:
                self._issues.append(
                    V3ValidationIssue(
                        issue_type=V3IssueType.DUPLICATE_NODE_ID,
                        severity="CRITICAL",
                        node_id=node_id,
                        message=f"Node id '{node_id}' appears more than once across node arrays.",
                        suggested_action="Rename one of the duplicates, then re-sign the KG.",
                    )
                )
            seen.add(node_id)

        # all_node_ids() is a dict so duplicates within the same array
        # are already collapsed. Detect them explicitly by counting.
        for collection in (
            self._kg.nodes.subjects,
            self._kg.nodes.rules,
            self._kg.nodes.obligations,
            self._kg.nodes.definitions,
            self._kg.nodes.exemptions,
            self._kg.nodes.precedents,
            self._kg.nodes.jurisdictions,
            self._kg.nodes.citations,
        ):
            counts: Dict[str, int] = {}
            for node in collection:
                counts[node.id] = counts.get(node.id, 0) + 1
            for node_id, count in counts.items():
                if count > 1:
                    self._issues.append(
                        V3ValidationIssue(
                            issue_type=V3IssueType.DUPLICATE_NODE_ID,
                            severity="CRITICAL",
                            node_id=node_id,
                            message=(
                                f"Node id '{node_id}' appears {count} times within the same node array."
                            ),
                            suggested_action="Rename one of the duplicates, then re-sign the KG.",
                        )
                    )

    def _check_dangling_edges(self, node_types: Dict[str, str]) -> None:
        for edge in self._kg.edges:
            if edge.from_id not in node_types:
                self._issues.append(
                    V3ValidationIssue(
                        issue_type=V3IssueType.DANGLING_EDGE,
                        severity="HIGH",
                        edge=edge,
                        message=(
                            f"Edge {edge.type} from '{edge.from_id}' references an undefined source node."
                        ),
                        suggested_action="Add the missing source node or remove the edge.",
                    )
                )
            if edge.to_id not in node_types:
                self._issues.append(
                    V3ValidationIssue(
                        issue_type=V3IssueType.DANGLING_EDGE,
                        severity="HIGH",
                        edge=edge,
                        message=(f"Edge {edge.type} to '{edge.to_id}' references an undefined target node."),
                        suggested_action="Add the missing target node or remove the edge.",
                    )
                )

    def _check_edge_target_types(self, node_types: Dict[str, str]) -> None:
        for edge in self._kg.edges:
            expected = _EDGE_TARGET_TYPE.get(EdgeType(edge.type))
            if expected is None:
                continue
            actual = node_types.get(edge.to_id)
            if actual is None:
                # Already flagged by _check_dangling_edges.
                continue
            if actual != expected:
                self._issues.append(
                    V3ValidationIssue(
                        issue_type=V3IssueType.INVALID_EDGE_TARGET_TYPE,
                        severity="HIGH",
                        edge=edge,
                        message=(
                            f"Edge '{edge.type}' from '{edge.from_id}' targets a "
                            f"'{actual}' node ('{edge.to_id}') but spec §3.2 requires a "
                            f"'{expected}' target."
                        ),
                        suggested_action=(
                            f"Repoint the edge at a {expected} node, or use a different edge type."
                        ),
                    )
                )

    def _check_rule_obligation_coverage(self) -> None:
        rule_ids: Set[str] = {r.id for r in self._kg.nodes.rules}
        obligation_ids: Set[str] = {o.id for o in self._kg.nodes.obligations}
        consists_of: List[Tuple[str, str]] = [
            (e.from_id, e.to_id) for e in self._kg.edges if e.type == EdgeType.CONSISTS_OF.value
        ]
        rules_with_obligation: Set[str] = {src for src, _ in consists_of if src in rule_ids}
        obligations_with_rule: Set[str] = {dst for _, dst in consists_of if dst in obligation_ids}

        for rule_id in rule_ids - rules_with_obligation:
            self._issues.append(
                V3ValidationIssue(
                    issue_type=V3IssueType.RULE_WITHOUT_OBLIGATION,
                    severity="HIGH",
                    node_id=rule_id,
                    message=(
                        f"Rule '{rule_id}' has no consists_of edge to any Obligation. "
                        "Spec §2.1.2 requires every rule to reference at least one typed "
                        "obligation."
                    ),
                    suggested_action="Add a consists_of edge to one or more Obligation nodes.",
                )
            )

        for obligation_id in obligation_ids - obligations_with_rule:
            self._issues.append(
                V3ValidationIssue(
                    issue_type=V3IssueType.OBLIGATION_WITHOUT_RULE,
                    severity="MEDIUM",
                    node_id=obligation_id,
                    message=(
                        f"Obligation '{obligation_id}' is not referenced by any Rule via a "
                        "consists_of edge. The obligation is unreachable from the runtime."
                    ),
                    suggested_action=("Either add a consists_of edge from a Rule, or remove the obligation."),
                )
            )

    def _check_under_tiered_qualitative_obligations(self) -> None:
        """Flag a Rule whose obligation(s) can't be mechanically verified
        but is tiered ``medium``/``low`` (declared or defaulted).

        The runtime's ``RiskTierGovernor`` derives the *effective* tier
        from this KG's ``risk_tier`` fields (strictest obligation wins) --
        a caller cannot override it (see
        ``tag_registry.registry.RiskTierGovernor``). That makes KG
        authoring the one place an under-tiered qualitative obligation can
        still slip through: a non-formalizable obligation returns
        ``UNVERIFIABLE`` from the verifier, and at tier-2/tier-3 the risk
        policy accepts ``UNVERIFIABLE`` with only a note (no forced human
        review), unlike tier-1 where anything but ``AGREED`` is forced to
        ``DISCRETIONARY``. This is advisory (``MEDIUM``) by default, and a
        hard error (``HIGH``) under ``strict=True``.
        """
        obligations_by_id = {o.id: o for o in self._kg.nodes.obligations}
        consists_of: List[Tuple[str, str]] = [
            (e.from_id, e.to_id) for e in self._kg.edges if e.type == EdgeType.CONSISTS_OF.value
        ]
        severity = "HIGH" if self._strict else "MEDIUM"

        for rule in self._kg.nodes.rules:
            if rule.risk_tier == RiskTier.HIGH.value:
                continue
            for _src, obligation_id in (pair for pair in consists_of if pair[0] == rule.id):
                obligation = obligations_by_id.get(obligation_id)
                if obligation is None:
                    continue  # dangling edge -- already flagged by _check_dangling_edges
                if obligation.obligation_type in _MECHANICALLY_CHECKABLE_OBLIGATION_TYPES:
                    continue
                self._issues.append(
                    V3ValidationIssue(
                        issue_type=V3IssueType.UNDER_TIERED_QUALITATIVE_OBLIGATION,
                        severity=severity,
                        node_id=rule.id,
                        message=(
                            f"Rule '{rule.id}' has risk_tier={rule.risk_tier!r} but its "
                            f"obligation '{obligation.id}' (obligation_type="
                            f"{obligation.obligation_type!r}) is not mechanically checkable "
                            "by the Symbolic Verifier. The runtime governor derives the "
                            "effective tier from this field, strictest-wins, so an "
                            "under-tiered qualitative obligation is the one gap the runtime "
                            "cannot backstop on its own."
                        ),
                        suggested_action=(
                            "Set this Rule's risk_tier to 'high' so any non-AGREED verifier "
                            "result (including UNVERIFIABLE) forces DISCRETIONARY with human "
                            "attestation, since nothing here can be mechanically verified."
                        ),
                    )
                )

    # ------------------------------------------------------------------ #
    # Convenience accessors                                              #
    # ------------------------------------------------------------------ #

    @property
    def issues(self) -> List[V3ValidationIssue]:
        """The issues from the most recent :meth:`run`."""
        return list(self._issues)

    @staticmethod
    def edge_target_type(edge_type: EdgeType) -> str:
        """Public accessor for the expected target type of an edge."""
        return _EDGE_TARGET_TYPE[edge_type]
