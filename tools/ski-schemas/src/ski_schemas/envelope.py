"""Pydantic models for the v3 verdict envelope per spec v3.0 §4.

* §4.1 — the five-verdict taxonomy (preserved from v2.1).
* §4.2 — required + optional envelope fields.
* §4.3 — KG citations with node_id / version / role.
* §4.4 — formalizable assertions the symbolic verifier can check.
* §4.5 — verifier result with status enum.
* §4.6 — model provenance (six required hash + id fields).

These models are the contract every v3 verdict honours. They MUST
round-trip through JSON without loss; the runtime's envelope tests
enforce this. This module is the single source of truth shared by the
server, the SDK, and the conformance suite (RFC 0003 PR 1).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

# ---- Verdict taxonomy (§4.1) ----


class V3Verdict(str, Enum):
    """The five-verdict taxonomy, preserved from v2.1."""

    CLEAR = "CLEAR"
    FLAG = "FLAG"
    NULL_UNMAPPED = "NULL_UNMAPPED"
    NULL_STALE = "NULL_STALE"
    DISCRETIONARY = "DISCRETIONARY"


# ---- Verifier status (§4.5) ----


class VerifierStatus(str, Enum):
    """Status returned by the Symbolic Verifier (spec §5.3)."""

    AGREED = "AGREED"
    LLM_CONTRADICTION = "LLM_CONTRADICTION"
    NEURO_SYMBOLIC_DIVERGENCE = "NEURO_SYMBOLIC_DIVERGENCE"
    UNVERIFIABLE = "UNVERIFIABLE"


# ---- KG citation (§4.3) ----


class KGCitationRole(str, Enum):
    """The role a cited KG node played in the verdict."""

    OBLIGATION = "obligation"
    DEFINITION_RESOLVED = "definition_resolved"
    EXEMPTION_CONSIDERED = "exemption_considered"
    PRECEDENT_REFERENCED = "precedent_referenced"
    JURISDICTION_MATCHED = "jurisdiction_matched"


class KGCitation(BaseModel):
    """A single KG node the LLM cited as informing the verdict."""

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    node_id: str
    version: str
    role: KGCitationRole


# ---- Formalizable assertion (§4.4) ----


class FormalizableAssertion(BaseModel):
    """A structured assertion the symbolic verifier can mechanically check."""

    model_config = ConfigDict(extra="forbid")

    predicate: str = Field(..., description="Predicate type, e.g. 'must_not_exceed'.")
    metric: str = Field(..., description="Dotted-path into the measurement object.")
    value: Union[float, int, str, List[Any], None] = None
    observed: Union[float, int, str, List[Any], None] = None
    satisfied: bool
    obligation_id: str = Field(..., description="The KG obligation this assertion checks.")
    window_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Time-window length in seconds for stateful predicates "
            "(e.g. 86400 for a 24h rolling average). None for stateless "
            "predicates."
        ),
    )


# ---- Verifier result (§4.5) ----


class VerifierResult(BaseModel):
    """The symbolic verifier's per-assertion result."""

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    status: VerifierStatus
    checked_assertions: int = Field(default=0, ge=0)
    divergences: List[str] = Field(default_factory=list)


# ---- Model provenance (§4.6) ----


class ModelProvenance(BaseModel):
    """Inference provenance metadata required for v3 replay.

    All hash values MUST be lowercase hex prefixed with ``sha256:`` per
    spec §4.6. The Pydantic layer enforces the prefix.
    """

    # model_weight_hash collides with Pydantic's reserved model_
    # namespace; opt out explicitly. The field name is normative per
    # spec §4.6 and cannot be renamed.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_weight_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    kg_version_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    prompt_template_id: str = Field(..., description="Stable id, e.g. 'ski.v3.evaluate.1'.")
    prompt_template_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")
    decoder_seed: int = Field(..., ge=0)
    structured_grammar_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]+$")

    # ---- Optional inference-provenance fields (framework v3.2.0) ----
    # Absent on envelopes from v3.1.x runtimes; both default to None so
    # those envelopes stay valid.
    model_hash_verified: Optional[bool] = Field(
        default=None,
        description=(
            "True only when an operator pin (SKI_MODEL_FILE_SHA256) matched a weights "
            "digest the runtime obtained independently of that pin. False means "
            "model_weight_hash is unverified: an unpinned backend digest, an "
            "operator-asserted value, or a name commitment that is NOT a weight hash."
        ),
    )
    inference_backend: Optional[str] = Field(
        default=None,
        description="Name of the backend that produced the verdict, e.g. 'ollama-v3', 'fake-llm'.",
    )

    # ---- Optional KG-trust fields (framework v3.2.0) ----
    # Absent on envelopes from v3.1.x runtimes; both default to None so
    # those envelopes stay valid.
    kg_signer_key_id: Optional[str] = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description=(
            "Key ID of the Ed25519 key the Knowledge Graph signature verified "
            "against: 'sha256:' + hex sha256 of the raw 32-byte public key. "
            "None when the KG was unsigned."
        ),
    )
    kg_trust: Optional[Literal["anchored", "unanchored", "unsigned"]] = Field(
        default=None,
        description=(
            "'anchored': the KG signature verified against an operator-pinned "
            "trust anchor (SKI_KG_TRUST_ANCHORS). 'unanchored': no anchors, "
            "SKI_KG_ALLOW_UNANCHORED=true, checked only against the KG's own "
            "embedded key (dev only). 'unsigned': KG_REQUIRE_SIGNATURE=false "
            "loaded a KG with no signature (dev only)."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_unset_optional_fields(self, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
        # The six spec §4.6 fields can never be None, so dropping None
        # values only drops optional fields that were never set. A
        # v3.1-shape envelope therefore re-serialises byte-identically and
        # stored envelope hashes stay stable. No return annotation on
        # purpose: pydantic then keeps the per-field serialisation schema.
        data = handler(self)
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


# ---- Verdict envelope (§4.2) ----


class V3VerdictEnvelope(BaseModel):
    """The complete v3 verdict envelope.

    Every required field is enforced at the Pydantic layer. The
    envelope MUST round-trip through JSON without loss; that property
    is what makes the audit ledger's hash chain meaningful.
    """

    # model_provenance collides with Pydantic's reserved model_
    # namespace; opt out explicitly. The field name is normative per
    # spec §4.2 and cannot be renamed.
    model_config = ConfigDict(use_enum_values=True, extra="forbid", protected_namespaces=())

    verdict: V3Verdict
    reasoning: str
    kg_citations: List[KGCitation] = Field(default_factory=list)
    formalizable_assertions: List[FormalizableAssertion] = Field(default_factory=list)
    verifier_result: VerifierResult
    model_provenance: ModelProvenance
    transcript_ref: str = Field(..., description="Pointer to the LLM transcript in the ledger.")

    # Optional fields per spec §4.2 + §5.4 + §5.6.
    human_attestation: Optional[Dict[str, Any]] = None
    notes: List[str] = Field(default_factory=list)
    verdict_path: Optional[str] = Field(default=None, description="Per §5.6: 'fast' or None.")
