"""kg-validator — schema and §3.6 cross-cutting validation for v3 KGs."""

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

__version__ = "3.1.0a2"
__author__ = "KpiFinity"

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
