"""
KG Extractor - Extract compliance rules from regulatory documents
"""

from .extractor import Extractor
from .models import ExtractionResult, ComplianceRule

__version__ = "1.0.0"
__author__ = "KpiFinity"

__all__ = [
    "Extractor",
    "ExtractionResult",
    "ComplianceRule",
]
