"""SKI Framework v3 runtime — public types, evaluator, and verifier.

PR 10a landed the verdict envelope contract per spec v3.0 §4. PR 10b
shipped the KG-grounded LLM evaluator and the deterministic ``FakeLLM``
backend. PR 10c closes the neuro-symbolic loop: :class:`SymbolicVerifier`
mechanically cross-checks each :class:`FormalizableAssertion`, and the
risk-tier policy (spec §5.4) post-processes the envelope.
"""

from .envelope import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    ModelProvenance,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)
from .evaluator import (
    PROMPT_TEMPLATE,
    PROMPT_TEMPLATE_ID,
    RESPONSE_GRAMMAR,
    FakeLLM,
    V3Evaluator,
    V3LLMBackend,
)
from .policies import RiskTier, apply_risk_policy
from .verifier import SymbolicVerifier

__all__ = [
    "PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE_ID",
    "RESPONSE_GRAMMAR",
    "FakeLLM",
    "FormalizableAssertion",
    "KGCitation",
    "KGCitationRole",
    "ModelProvenance",
    "RiskTier",
    "SymbolicVerifier",
    "V3Evaluator",
    "V3LLMBackend",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
    "apply_risk_policy",
]
