"""Wire-contract models, mirrored from the SKI Model v3 envelope (spec §4-§6).

These intentionally duplicate the server's Pydantic models so the SDK has no
dependency on the reference implementation. A contract-drift test
(`tests/test_contract_drift.py`) asserts the field sets stay in lock-step with
the server's `V3VerdictEnvelope` / `MeasurementRecord` / `LLMTranscript`.

Response models use ``extra="ignore"`` so a forward-compatible server that adds
a field does not break older SDKs at runtime; the drift test is what flags the
divergence in CI.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

_RESPONSE = ConfigDict(use_enum_values=True, extra="ignore", protected_namespaces=())


class V3Verdict(str, Enum):
    CLEAR = "CLEAR"
    FLAG = "FLAG"
    DISCRETIONARY = "DISCRETIONARY"
    NULL_UNMAPPED = "NULL_UNMAPPED"
    NULL_STALE = "NULL_STALE"


class VerifierStatus(str, Enum):
    AGREED = "AGREED"
    LLM_CONTRADICTION = "LLM_CONTRADICTION"
    NEURO_SYMBOLIC_DIVERGENCE = "NEURO_SYMBOLIC_DIVERGENCE"
    UNVERIFIABLE = "UNVERIFIABLE"


class KGCitationRole(str, Enum):
    OBLIGATION = "obligation"
    DEFINITION = "definition"
    PRECEDENT = "precedent"


class KGCitation(BaseModel):
    model_config = _RESPONSE
    node_id: str
    version: str
    role: str


class FormalizableAssertion(BaseModel):
    model_config = _RESPONSE
    predicate: str
    metric: str
    value: Union[float, int, str, List[Any], None] = None
    observed: Union[float, int, str, List[Any], None] = None
    satisfied: bool
    obligation_id: str
    window_seconds: Optional[int] = None


class VerifierResult(BaseModel):
    model_config = _RESPONSE
    status: str
    checked_assertions: int = 0
    divergences: List[str] = Field(default_factory=list)


class ModelProvenance(BaseModel):
    model_config = _RESPONSE
    model_weight_hash: str
    kg_version_hash: str
    prompt_template_id: str
    prompt_template_hash: str
    decoder_seed: int
    structured_grammar_hash: str


class V3VerdictEnvelope(BaseModel):
    model_config = _RESPONSE
    verdict: str
    reasoning: str
    kg_citations: List[KGCitation] = Field(default_factory=list)
    formalizable_assertions: List[FormalizableAssertion] = Field(default_factory=list)
    verifier_result: VerifierResult
    model_provenance: ModelProvenance
    transcript_ref: str
    human_attestation: Optional[Dict[str, Any]] = None
    notes: List[str] = Field(default_factory=list)
    verdict_path: Optional[str] = None


class MeasurementRecord(BaseModel):
    """Request body for ``POST /api/evaluate``."""

    model_config = ConfigDict(extra="forbid")
    measurement_id: str
    timestamp: str
    subject: str
    measurement: Dict[str, Any] = Field(default_factory=dict)
    jurisdiction: Optional[str] = None


class LLMTranscript(BaseModel):
    """The signed transcript an auditor verifies (spec §6.2)."""

    model_config = ConfigDict(extra="ignore")
    transcript_id: str
    request_canonical: str
    request_hash: str
    response_canonical: Dict[str, Any]
    response_hash: str
    signature_hex: str
    signing_key_id: str
    backend_name: str
    backend_metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime


class HealthStatus(BaseModel):
    model_config = _RESPONSE
    status: str
    kg_loaded: bool
    kg_signature_verified: bool
    canary_status: str
    verdicts_produced: int
    timestamp: str
    runtime_version: str


__all__ = [
    "FormalizableAssertion",
    "HealthStatus",
    "KGCitation",
    "KGCitationRole",
    "LLMTranscript",
    "MeasurementRecord",
    "ModelProvenance",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
]
