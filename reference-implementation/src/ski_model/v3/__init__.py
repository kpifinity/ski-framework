"""SKI Framework v3 runtime — public types and evaluator.

PR 10a landed the verdict envelope contract per spec v3.0 §4. PR 10b
ships the KG-grounded LLM evaluator and a deterministic ``FakeLLM``
backend. PR 10c lands the Symbolic Verifier wrapper that turns the
``VerifierResult`` placeholder into real agreement / divergence data.
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

__all__ = [
    "FakeLLM",
    "FormalizableAssertion",
    "KGCitation",
    "KGCitationRole",
    "ModelProvenance",
    "PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE_ID",
    "RESPONSE_GRAMMAR",
    "V3Evaluator",
    "V3LLMBackend",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
]
