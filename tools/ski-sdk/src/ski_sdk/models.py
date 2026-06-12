"""ski-sdk wire models.

The shared wire contract (envelope, transcript, measurement) is
imported from ``ski-schemas`` — the single source of truth the server
uses too (RFC 0003 PR 1). Only SDK-local convenience models are
defined here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from ski_schemas import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    LLMTranscript,
    MeasurementRecord,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)

# Lenient parsing for SDK-local response models: tolerate additive
# server fields. The shared wire models keep the server's semantics.
_RESPONSE = ConfigDict(use_enum_values=True, extra="ignore", protected_namespaces=())


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
