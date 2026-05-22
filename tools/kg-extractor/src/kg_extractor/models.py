"""Data models for kg-extractor (v0.1.0-alpha).

v2.1 changes:
  * `IMPLIED` removed from the confidence enum — the Anchor Constraint
    (B2.1) prohibits inference beyond source text. Rules a Phase 1
    extractor cannot defend with a verbatim source quote must be
    surfaced as `DISCRETIONARY` for human triage, not silently inferred.
  * Extraction metadata now records the seed, temperature, prompt hash,
    model name, and model file SHA-256 to make compilation auditable.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ConfidenceLevel(str, Enum):
    """Permitted confidence levels for extracted rules.

    Note: `IMPLIED` (present in pre-v2.1 versions) is GONE. See B2.1.
    """

    EXPLICIT = "EXPLICIT"
    DISCRETIONARY = "DISCRETIONARY"
    CONFLICTING = "CONFLICTING"


class ComplianceRule(BaseModel):
    """Extracted compliance rule."""

    id: str
    subject: str
    relation: str
    object: str
    source_document: str
    source_clause: str
    source_document_version: Optional[str] = None
    confidence: ConfidenceLevel
    reasoning: str
    effective_date: Optional[str] = None
    sunset_date: Optional[str] = None
    related_rules: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_implied(self) -> "ComplianceRule":
        # Defence in depth: even if a serialised payload sneaks in
        # `confidence: "IMPLIED"`, the enum coercion will already have
        # raised. This validator exists so the prohibition is also
        # documented in code.
        if self.confidence not in (ConfidenceLevel.EXPLICIT, ConfidenceLevel.DISCRETIONARY, ConfidenceLevel.CONFLICTING):
            raise ValueError(f"Rule {self.id}: prohibited confidence value")
        return self

    class Config:
        use_enum_values = True


class ExtractionMetadata(BaseModel):
    """Metadata about an extraction run — captured for reproducibility audits."""

    document_name: str
    document_type: str
    sector: str
    extraction_timestamp: str
    total_rules_extracted: int
    rules_by_confidence: Dict[str, int]
    extraction_duration_seconds: float
    backend: str                          # "anthropic" | "openai" | "ollama" | ...
    model_used: str
    model_file_sha256: Optional[str] = None
    temperature: float = 0.0
    seed: Optional[int] = None
    prompt_sha256: Optional[str] = None
    extractor_version: str = "0.1.0a0"


class ExtractionResult(BaseModel):
    rules: List[ComplianceRule] = Field(default_factory=list)
    metadata: ExtractionMetadata
    warnings: List[str] = Field(default_factory=list)

    def get_rules_by_confidence(self, confidence: ConfidenceLevel) -> List[ComplianceRule]:
        return [r for r in self.rules if r.confidence == confidence]

    def get_explicit_rules(self) -> List[ComplianceRule]:
        return self.get_rules_by_confidence(ConfidenceLevel.EXPLICIT)

    def get_discretionary_rules(self) -> List[ComplianceRule]:
        return self.get_rules_by_confidence(ConfidenceLevel.DISCRETIONARY)

    def to_json(self) -> Dict[str, Any]:
        return {
            "rules": [r.model_dump() for r in self.rules],
            "metadata": self.metadata.model_dump(),
            "warnings": self.warnings,
        }
