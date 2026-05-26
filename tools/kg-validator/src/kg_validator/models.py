"""
Data models for KG Validator
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class ValidationStatus(str, Enum):
    """Status of rule validation"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"


class IssueType(str, Enum):
    """Type of validation issue"""
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    MISSING_FIELD = "MISSING_FIELD"
    VAGUE_RULE = "VAGUE_RULE"
    AMBIGUOUS = "AMBIGUOUS"
    INCONSISTENT_DATES = "INCONSISTENT_DATES"
    GRAMMAR = "GRAMMAR"


class ComplianceRule(BaseModel):
    """Compliance rule from extraction"""
    id: str
    subject: str
    relation: str
    object: str
    source_document: str
    source_clause: str
    confidence: str
    reasoning: str
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None


class ValidationIssue(BaseModel):
    """Issue found during validation"""
    rule_id: str
    issue_type: IssueType
    severity: str = Field(..., description="LOW|MEDIUM|HIGH|CRITICAL")
    message: str
    suggested_action: Optional[str] = None
    related_rule_ids: List[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class ConflictPair(BaseModel):
    """Pair of conflicting rules"""
    rule_id_1: str
    rule_id_2: str
    conflict_type: str = Field(..., description="CONTRADICTORY|DATE_OVERLAP|INCONSISTENT")
    explanation: str
    similarity_score: float = Field(..., ge=0, le=1)


class DuplicatePair(BaseModel):
    """Pair of duplicate or near-duplicate rules"""
    rule_id_1: str
    rule_id_2: str
    similarity_score: float = Field(..., ge=0, le=1)
    duplicate_type: str = Field(..., description="EXACT|SEMANTIC|NEAR_DUPLICATE")


class ApprovedRule(BaseModel):
    """Rule after expert approval"""
    id: str
    subject: str
    relation: str
    object: str
    source_document: str
    source_clause: str
    confidence: str
    reasoning: str
    validation_status: ValidationStatus
    validation_timestamp: str
    validator_notes: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class ValidationMetadata(BaseModel):
    """Metadata about validation session"""
    total_rules_reviewed: int
    total_approved: int
    total_rejected: int
    total_flagged: int
    total_issues_found: int
    validation_duration_seconds: float
    validators: List[str]
    validation_timestamp: str


class ValidationResult(BaseModel):
    """Complete validation result"""
    approved_rules: List[ApprovedRule]
    issues: List[ValidationIssue] = Field(default_factory=list)
    conflicts: List[ConflictPair] = Field(default_factory=list)
    duplicates: List[DuplicatePair] = Field(default_factory=list)
    metadata: ValidationMetadata

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return {
            "approved_rules": [r.dict() for r in self.approved_rules],
            "issues": [i.dict() for i in self.issues],
            "conflicts": [c.dict() for c in self.conflicts],
            "duplicates": [d.dict() for d in self.duplicates],
            "metadata": self.metadata.dict(),
        }
