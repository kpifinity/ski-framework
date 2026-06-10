"""kg-extractor — extract compliance rules from regulatory text and emit v3 KGs."""

from .extractor import Extractor
from .models import ComplianceRule, ExtractionQuality, ExtractionResult
from .v3_emitter import emit_v3_kg

__version__ = "3.1.0a2"
__author__ = "KpiFinity"

__all__ = [
    "ComplianceRule",
    "ExtractionQuality",
    "ExtractionResult",
    "Extractor",
    "emit_v3_kg",
]
