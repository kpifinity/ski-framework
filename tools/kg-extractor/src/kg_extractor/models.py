"""Data models for kg-extractor.

This module declares the *extractor's* output shape — what the LLM
returns chunk-by-chunk from a regulatory document. The eventual v3 KG
that downstream tools (kg-validator, the runtime) consume is produced
by :mod:`.v3_emitter`, which wraps these flat rules into the typed
graph shape per spec v3.0 §3.

Naming distinction (PR 10e):

* The extractor's per-rule trust signal is ``extraction_quality``. It
  describes how confident the EXTRACTOR is in the source quote — an
  authoring-time judgement, not a runtime verdict.
* This is deliberately separate from the runtime, which is
  *categorical* per Axiom 2 and stores no confidence value at all.
* The runtime conformance test
  ``conformance/provenance/test_no_confidence.py`` enforces the
  separation: ``ConfidenceLevel`` must not appear in audit-ledger
  schemas, but the extractor is free to carry its own
  ``ExtractionQuality`` value.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionQuality(str, Enum):
    """Extractor's trust in the source quote it produced.

    Note: ``IMPLIED`` (present in pre-v2.1 versions) is GONE. See B2.1
    Anchor Constraint — extraction must not infer beyond the source
    text. Rules a Phase 1 extractor cannot defend with a verbatim
    source quote must be surfaced as ``DISCRETIONARY`` for human
    triage, not silently inferred.
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
    extraction_quality: ExtractionQuality
    reasoning: str
    effective_date: Optional[str] = None
    sunset_date: Optional[str] = None
    related_rules: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_implied(self) -> "ComplianceRule":
        # Defence in depth: even if a serialised payload sneaks in
        # `extraction_quality: "IMPLIED"`, the enum coercion will
        # already have raised. This validator exists so the
        # prohibition is also documented in code.
        if self.extraction_quality not in (
            ExtractionQuality.EXPLICIT,
            ExtractionQuality.DISCRETIONARY,
            ExtractionQuality.CONFLICTING,
        ):
            raise ValueError(f"Rule {self.id}: prohibited extraction_quality value")
        return self

    model_config = ConfigDict(use_enum_values=True)


class ExtractionMetadata(BaseModel):
    """Metadata about an extraction run — captured for reproducibility audits."""

    document_name: str
    document_type: str
    sector: str
    extraction_timestamp: str
    total_rules_extracted: int
    rules_by_quality: Dict[str, int]
    extraction_duration_seconds: float
    backend: str  # "anthropic" | "openai" | "ollama" | ...
    model_used: str
    model_file_sha256: Optional[str] = None
    temperature: float = 0.0
    seed: Optional[int] = None
    prompt_sha256: Optional[str] = None
    extractor_version: str = "3.0.0"


class ExtractionResult(BaseModel):
    rules: List[ComplianceRule] = Field(default_factory=list)
    metadata: ExtractionMetadata
    warnings: List[str] = Field(default_factory=list)

    def get_rules_by_quality(self, quality: ExtractionQuality) -> List[ComplianceRule]:
        return [r for r in self.rules if r.extraction_quality == quality]

    def get_explicit_rules(self) -> List[ComplianceRule]:
        return self.get_rules_by_quality(ExtractionQuality.EXPLICIT)

    def get_discretionary_rules(self) -> List[ComplianceRule]:
        return self.get_rules_by_quality(ExtractionQuality.DISCRETIONARY)

    def to_json(self) -> Dict[str, Any]:
        return {
            "rules": [r.model_dump() for r in self.rules],
            "metadata": self.metadata.model_dump(),
            "warnings": self.warnings,
        }
