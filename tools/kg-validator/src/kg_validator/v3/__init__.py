"""v3 KG schema support for kg-validator.

The v3 KG is a typed graph of nodes and edges per SKI Framework
specification v3.0 §3. This subpackage implements:

* Pydantic v2 models for every node and edge type.
* A JSON loader that parses a v3 KG file into the model tree.
* A validator that runs the §3.6 validation passes.

The v2 schema (flat rule list under ``kg_validator.models``) remains
the default for ``kg-validator validate``. Pass ``--schema v3`` to
route a KG file through this subpackage instead.
"""

from .loader import KnowledgeGraphV3, load_v3_kg
from .models import (
    Citation,
    Definition,
    Edge,
    EdgeType,
    Exemption,
    Jurisdiction,
    Obligation,
    ObligationType,
    Precedent,
    RiskTier,
    Rule,
    Subject,
    V3IssueType,
    V3ValidationIssue,
    V3ValidationResult,
)
from .validator import V3Validator

__all__ = [
    "Citation",
    "Definition",
    "Edge",
    "EdgeType",
    "Exemption",
    "Jurisdiction",
    "KnowledgeGraphV3",
    "Obligation",
    "ObligationType",
    "Precedent",
    "RiskTier",
    "Rule",
    "Subject",
    "V3IssueType",
    "V3ValidationIssue",
    "V3ValidationResult",
    "V3Validator",
    "load_v3_kg",
]
