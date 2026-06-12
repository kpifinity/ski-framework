"""Verdict-envelope models — re-exported from ``ski-schemas`` (RFC 0003 PR 1).

The models formerly defined here are now the shared package
``ski_schemas.envelope``; this module remains so every existing
``ski_model.v3.envelope`` import keeps working. New code may import
from either path — they are the same objects.
"""

from __future__ import annotations

from ski_schemas.envelope import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)

__all__ = [
    "FormalizableAssertion",
    "KGCitation",
    "KGCitationRole",
    "ModelProvenance",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
]
