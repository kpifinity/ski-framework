"""ski-schemas — the SKI Framework wire models, defined once (RFC 0003 PR 1).

The verdict envelope, the signed LLM transcript, and the measurement
record are normative (spec v3.0 §4, §6). This dependency-light package
is the single source of truth the server, the ski-sdk client, and the
conformance suite all import — one definition, no drift.
"""

from .canonical import (
    CanonicalizationError,
    canonicalize,
    canonicalize_json_text,
    digest,
    parse_json,
    serialize_number,
    sha256_canonical,
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
from .kg import KGObligation
from .measurement import MeasurementRecord
from .transcript import LLMTranscript, hash_pair, signing_message

__version__ = "3.2.0"

__all__ = [
    "CanonicalizationError",
    "FormalizableAssertion",
    "KGCitation",
    "KGCitationRole",
    "KGObligation",
    "LLMTranscript",
    "MeasurementRecord",
    "ModelProvenance",
    "V3Verdict",
    "V3VerdictEnvelope",
    "VerifierResult",
    "VerifierStatus",
    "canonicalize",
    "canonicalize_json_text",
    "digest",
    "hash_pair",
    "parse_json",
    "serialize_number",
    "sha256_canonical",
    "signing_message",
]
