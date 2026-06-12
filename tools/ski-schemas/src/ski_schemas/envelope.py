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
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

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
