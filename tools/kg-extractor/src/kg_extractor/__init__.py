"""
KG Extractor - Extract compliance rules from regulatory documents
"""

from .extractor import Extractor
from .models import ComplianceRule, ExtractionResult

__version__ = "1.0.0"
__author__ = "KpiFinity"

__all__ = [
    "ComplianceRule",
    "ExtractionResult",
    "Extractor",
]
