"""ski-sdk — typed Python client for the SKI Framework SKI Model.

> Early alpha: wraps an alpha HTTP API; pin your versions.
"""

from __future__ import annotations

from .client import AsyncSKIClient, SKIClient
from .errors import (
    SKIAuthError,
    SKIError,
    SKIResponseError,
    SKIServiceUnavailable,
    SKITransportError,
    SKIValidationError,
)
from .models import (
    HealthStatus,
    LLMTranscript,
    MeasurementRecord,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierStatus,
)
from .verify import AttestationReport, VerificationReport, verify_sovereignty_attestation, verify_transcript

__version__ = "3.2.0"

__all__ = [
    "AsyncSKIClient",
    "AttestationReport",
    "HealthStatus",
    "LLMTranscript",
    "MeasurementRecord",
    "SKIAuthError",
    "SKIClient",
    "SKIError",
    "SKIResponseError",
    "SKIServiceUnavailable",
    "SKITransportError",
    "SKIValidationError",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerificationReport",
    "VerifierStatus",
    "__version__",
    "verify_sovereignty_attestation",
    "verify_transcript",
]
