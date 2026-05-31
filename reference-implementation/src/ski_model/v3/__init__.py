"""SKI Framework v3 runtime — public types, evaluator, and verifier.

PR 10a landed the verdict envelope contract per spec v3.0 §4. PR 10b
shipped the KG-grounded LLM evaluator and the deterministic ``FakeLLM``
backend. PR 10c closes the neuro-symbolic loop: :class:`SymbolicVerifier`
mechanically cross-checks each :class:`FormalizableAssertion`, and the
risk-tier policy (spec §5.4) post-processes the envelope.
"""

from .backends import (
    PROMPT_TEMPLATE_HASH,
    STRUCTURED_GRAMMAR_HASH,
    OllamaV3Backend,
    build_backend,
)
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
    EvaluationResult,
    FakeLLM,
    V3Evaluator,
    V3LLMBackend,
)
from .policies import RiskTier, apply_risk_policy
from .signing import TranscriptSigner, verify_signature
from .transcript import LLMTranscript
from .verifier import BufferLike, SymbolicVerifier

__all__ = [
    "PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE_HASH",
    "PROMPT_TEMPLATE_ID",
    "RESPONSE_GRAMMAR",
    "STRUCTURED_GRAMMAR_HASH",
    "BufferLike",
    "EvaluationResult",
    "FakeLLM",
    "FormalizableAssertion",
    "KGCitation",
    "KGCitationRole",
    "LLMTranscript",
    "ModelProvenance",
    "OllamaV3Backend",
    "RiskTier",
    "SymbolicVerifier",
    "TranscriptSigner",
    "V3Evaluator",
    "V3LLMBackend",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
    "apply_risk_policy",
    "build_backend",
    "verify_signature",
]
