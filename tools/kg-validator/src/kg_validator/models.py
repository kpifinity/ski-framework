"""Pydantic v2 models for the v3 KG schema.

Mirrors SKI Framework specification v3.0 §3:

* §3.1 Node types: Subject, Rule, Obligation, Definition, Exemption,
  Precedent, Jurisdiction, Citation.
* §3.2 Edge types: applies_to, consists_of, defined_by, exempted_by,
  amended_by, interpreted_by, scoped_to, cited_by.
* §3.3 Typed obligations: the closed enumeration.
* §3.4 Jurisdictional scope and effective-date intervals.

These models are the source of truth for kg-validator's schema parsing.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ObligationType(str, Enum):
    """Spec v3.0 §3.3 — typed obligations (closed enumeration)."""

    MUST = "must"
    MUST_NOT = "must_not"
    MUST_NOT_EXCEED = "must_not_exceed"
    MUST_BE_AT_LEAST = "must_be_at_least"
    MUST_BE_BELOW = "must_be_below"
    MUST_BE_ABOVE = "must_be_above"
    MUST_BE_WITHIN = "must_be_within"
    MUST_BE_ONE_OF = "must_be_one_of"
    MUST_NOT_BE_ONE_OF = "must_not_be_one_of"
    MUST_BE_RECORDED_WITHIN = "must_be_recorded_within"
    SHOULD = "should"
    DISCRETIONARY = "discretionary"


class RiskTier(str, Enum):
    """Spec v3.0 §5.4 — risk tier governor."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EdgeType(str, Enum):
    """Spec v3.0 §3.2 — edge types."""

    APPLIES_TO = "applies_to"
    CONSISTS_OF = "consists_of"
    DEFINED_BY = "defined_by"
    EXEMPTED_BY = "exempted_by"
    AMENDED_BY = "amended_by"
    INTERPRETED_BY = "interpreted_by"
    SCOPED_TO = "scoped_to"
    CITED_BY = "cited_by"


# ---------------------------------------------------------------------------
# Node base
# ---------------------------------------------------------------------------


class _NodeBase(BaseModel):
    """Common fields every node carries (spec §3.1)."""

    id: str = Field(..., description="Stable globally-unique identifier")
    version: str = Field(
        ...,
        description=(
            "Content-addressed SHA-256 of the canonical serialization of this "
            "node's content excluding the version field itself."
        ),
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------


class Subject(_NodeBase):
    """A telemetry subject a rule can apply to."""

    type: Literal["Subject"] = "Subject"
    name: str = Field(..., description="Human-readable label")
    description: Optional[str] = None


class Rule(_NodeBase):
    """A regulatory requirement composed of one or more obligations.

    Carries the ``risk_tier`` field consumed by the risk-tier governor
    (spec §5.4).
    """

    type: Literal["Rule"] = "Rule"
    name: str
    risk_tier: RiskTier = RiskTier.MEDIUM
    description: Optional[str] = None


class Obligation(_NodeBase):
    """A typed normative statement (spec §3.3).

    The operand (``value``) is loosely typed because different
    obligation types carry different operand shapes: a numeric value
    for bound-style relations, a list for set membership, a
    duration-in-seconds for temporal predicates.
    """

    type: Literal["Obligation"] = "Obligation"
    obligation_type: ObligationType
    metric: str = Field(
        ...,
        description="Dotted-path identifier into the telemetry record's measurement object",
    )
    value: Union[float, int, str, List[Any], None] = None
    unit: Optional[str] = None
    effective_date_start: datetime = Field(
        ...,
        description="RFC 3339 timestamp; required per spec §3.4.",
    )
    effective_date_end: Optional[datetime] = None
    summary: Optional[str] = None


class Definition(_NodeBase):
    """A regulatory term and its scope-restricted meaning."""

    type: Literal["Definition"] = "Definition"
    term: str
    definition_text: str
    scope: Optional[str] = Field(
        default=None,
        description="The scope within which this definition applies (e.g., a regulation section).",
    )


class Exemption(_NodeBase):
    """A condition under which an obligation does not apply."""

    type: Literal["Exemption"] = "Exemption"
    condition: str
    description: Optional[str] = None


class Precedent(_NodeBase):
    """A prior obligation that the present one amends, supersedes, or interprets."""

    type: Literal["Precedent"] = "Precedent"
    summary: str
    relation: Literal["amends", "supersedes", "interprets"]


class Jurisdiction(_NodeBase):
    """A scope identifier (country, state, regulatory body, internal policy)."""

    type: Literal["Jurisdiction"] = "Jurisdiction"
    name: str
    parent: Optional[str] = Field(
        default=None,
        description="Parent jurisdiction id (e.g., 'us.federal' is parent of 'us.federal.epa').",
    )


class Citation(_NodeBase):
    """A reference to the originating regulatory text."""

    type: Literal["Citation"] = "Citation"
    source_document: str
    source_clause: str
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


class Edge(BaseModel):
    """A typed, directed edge between two nodes (spec §3.2)."""

    type: EdgeType
    from_id: str = Field(..., alias="from")
    to_id: str = Field(..., alias="to")

    model_config = ConfigDict(
        use_enum_values=True,
        extra="forbid",
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


class V3IssueType(str, Enum):
    """Issue categories surfaced by the v3 validator."""

    DUPLICATE_NODE_ID = "DUPLICATE_NODE_ID"
    UNKNOWN_OBLIGATION_TYPE = "UNKNOWN_OBLIGATION_TYPE"
    MISSING_EFFECTIVE_DATE = "MISSING_EFFECTIVE_DATE"
    DANGLING_EDGE = "DANGLING_EDGE"
    INVALID_EDGE_TARGET_TYPE = "INVALID_EDGE_TARGET_TYPE"
    RULE_WITHOUT_OBLIGATION = "RULE_WITHOUT_OBLIGATION"
    OBLIGATION_WITHOUT_RULE = "OBLIGATION_WITHOUT_RULE"
    UNKNOWN_RISK_TIER = "UNKNOWN_RISK_TIER"


class V3ValidationIssue(BaseModel):
    """A single finding produced by the v3 validator."""

    issue_type: V3IssueType
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    node_id: Optional[str] = None
    edge: Optional[Edge] = None
    message: str
    suggested_action: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class V3ValidationResult(BaseModel):
    """The aggregated output of one v3 validation run."""

    schema_version: str = "3.0"
    total_nodes: int = 0
    total_edges: int = 0
    total_issues: int = 0
    issues: List[V3ValidationIssue] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True iff no CRITICAL or HIGH severity issues were found."""
        return not any(i.severity in ("CRITICAL", "HIGH") for i in self.issues)
