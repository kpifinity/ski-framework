"""
KG Validator - Validate and review extracted compliance rules
"""

from .models import ConflictPair, ValidationIssue, ValidationResult
from .validator import Validator

__version__ = "1.0.0"
__author__ = "KpiFinity"

__all__ = [
    "ConflictPair",
    "ValidationIssue",
    "ValidationResult",
    "Validator",
]
