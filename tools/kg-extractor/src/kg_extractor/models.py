"""
Data models for KG Extractor
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ConfidenceLevel(str, Enum):
    """Confidence level of extracted rule"""
    EXPLICIT = "EXPLICIT"
    IMPLIED = "IMPLIED"
    DISCRETIONARY = "DISCRETIONARY"
    CONFLICTING = "CONFLICTING"


class ComplianceRule(BaseModel):
    """Extracted compliance rule"""
    id: str = Field(..., description="Unique rule identifier")
    subject: str = Field(..., description="Subject of the rule (what is being regulated)")
    relation: str = Field(..., description="Compliance obligation (relation between subject and object)")
    object: str = Field(..., description="Constraint or limit (the regulatory requirement)")
    source_document: str = Field(..., description="Name of source regulatory document")
    source_clause: str = Field(..., description="Specific clause/section reference")
    confidence: ConfidenceLevel = Field(..., description="Confidence level of extraction")
    reasoning: str = Field(..., description="Explanation of how rule was extracted")
    effective_date: Optional[str] = Field(None, description="Date rule becomes effective")
    expiration_date: Optional[str] = Field(None, description="Date rule expires")
    related_rules: List[str] = Field(default_factory=list, description="IDs of related rules")

    class Config:
        use_enum_values = True


class ExtractionMetadata(BaseModel):
    """Metadata about extraction job"""
    document_name: str
    document_type: str
    sector: str
    extraction_timestamp: str
    total_rules_extracted: int
    rules_by_confidence: Dict[str, int]
    extraction_duration_seconds: float
    model_used: str = "claude-opus-4-6"


class ExtractionResult(BaseModel):
    """Complete extraction result"""
    rules: List[ComplianceRule] = Field(..., description="Extracted compliance rules")
    metadata: ExtractionMetadata = Field(..., description="Extraction metadata")
    warnings: List[str] = Field(default_factory=list, description="Warnings during extraction")

    def get_rules_by_confidence(self, confidence: ConfidenceLevel) -> List[ComplianceRule]:
        """Get rules filtered by confidence level"""
        return [r for r in self.rules if r.confidence == confidence]

    def get_explicit_rules(self) -> List[ComplianceRule]:
        """Get only explicitly stated rules"""
        return self.get_rules_by_confidence(ConfidenceLevel.EXPLICIT)

    def get_discretionary_rules(self) -> List[ComplianceRule]:
        """Get rules needing human review"""
        return self.get_rules_by_confidence(ConfidenceLevel.DISCRETIONARY)

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return {
            "rules": [r.dict() for r in self.rules],
            "metadata": self.metadata.dict(),
            "warnings": self.warnings,
        }
