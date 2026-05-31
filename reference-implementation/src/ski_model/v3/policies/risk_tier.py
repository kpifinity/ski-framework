"""Risk-tier policy — post-processing of a V3VerdictEnvelope per spec v3.0 §5.4.

A tenant declares the risk tier of the obligation when submitting a
measurement (``MeasurementRecord.risk_tier``). The evaluator runs the LLM
and the :class:`SymbolicVerifier`, then this module decides whether the
envelope can be returned as-is or must be downgraded / annotated.

The three tiers are deliberately mechanical — no LLM is consulted at
policy-application time. Verdict shifts are recorded in the envelope's
``notes`` list so the audit ledger captures *why* the verdict differs from
what the LLM emitted.

Risk-tier definitions (spec §5.4):

  * tier-1 (high-risk):     require ``AGREED``; anything else forces
    ``DISCRETIONARY`` and ``human_attestation_required=true``.
  * tier-2 (standard):       allow ``LLM_CONTRADICTION`` only if the caller
    supplied ``human_attestation``; otherwise force ``DISCRETIONARY``.
  * tier-3 (low-risk):       only ``LLM_CONTRADICTION`` (verifier mechanically
    disagrees) forces downgrade; ``UNVERIFIABLE`` / ``NEURO_SYMBOLIC_DIVERGENCE``
    are accepted with a note recorded.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from ..envelope import V3Verdict, V3VerdictEnvelope, VerifierStatus


class RiskTier(str, Enum):
    """Canonical risk-tier identifiers per spec §5.4."""

    TIER_1 = "tier-1"
    TIER_2 = "tier-2"
    TIER_3 = "tier-3"


_ALIAS_MAP = {
    "tier-1": RiskTier.TIER_1,
    "tier1": RiskTier.TIER_1,
    "high": RiskTier.TIER_1,
    "high-risk": RiskTier.TIER_1,
    "tier-2": RiskTier.TIER_2,
    "tier2": RiskTier.TIER_2,
    "standard": RiskTier.TIER_2,
    "default": RiskTier.TIER_2,
    "tier-3": RiskTier.TIER_3,
    "tier3": RiskTier.TIER_3,
    "low": RiskTier.TIER_3,
    "low-risk": RiskTier.TIER_3,
}


def _normalise_tier(tier: str) -> RiskTier:
    key = tier.strip().lower()
    if key in _ALIAS_MAP:
        return _ALIAS_MAP[key]
    raise ValueError(f"Unknown risk tier {tier!r}. Expected one of: {sorted(_ALIAS_MAP)}.")


def apply_risk_policy(envelope: V3VerdictEnvelope, risk_tier: str) -> V3VerdictEnvelope:
    """Apply the spec §5.4 policy for ``risk_tier`` to ``envelope``."""
    tier = _normalise_tier(risk_tier)
    status = envelope.verifier_result.status
    notes: List[str] = list(envelope.notes)

    if status == VerifierStatus.AGREED:
        return envelope

    has_attestation = envelope.human_attestation is not None

    if tier == RiskTier.TIER_1:
        notes.append(
            f"risk-tier=tier-1 requires AGREED verifier; got {status!r}. "
            "Verdict forced to DISCRETIONARY; human_attestation_required=true."
        )
        return _downgrade_to_discretionary(envelope, notes=notes, human_attestation_required=True)

    if tier == RiskTier.TIER_2:
        if status == VerifierStatus.LLM_CONTRADICTION and not has_attestation:
            notes.append(
                "risk-tier=tier-2: LLM_CONTRADICTION without human_attestation. "
                "Verdict forced to DISCRETIONARY."
            )
            return _downgrade_to_discretionary(envelope, notes=notes, human_attestation_required=True)
        if status == VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE and not has_attestation:
            notes.append(
                "risk-tier=tier-2: NEURO_SYMBOLIC_DIVERGENCE without human_attestation. "
                "Verdict forced to DISCRETIONARY."
            )
            return _downgrade_to_discretionary(envelope, notes=notes, human_attestation_required=True)
        if status == VerifierStatus.UNVERIFIABLE:
            notes.append("risk-tier=tier-2: UNVERIFIABLE status accepted with note recorded.")
            return envelope.model_copy(update={"notes": notes})
        return envelope

    # tier-3 — permissive
    if status == VerifierStatus.LLM_CONTRADICTION:
        notes.append("risk-tier=tier-3: LLM_CONTRADICTION downgrades verdict to DISCRETIONARY.")
        return _downgrade_to_discretionary(envelope, notes=notes, human_attestation_required=False)
    notes.append(f"risk-tier=tier-3: verifier status {status!r} accepted with note recorded.")
    return envelope.model_copy(update={"notes": notes})


def _downgrade_to_discretionary(
    envelope: V3VerdictEnvelope,
    *,
    notes: List[str],
    human_attestation_required: bool,
) -> V3VerdictEnvelope:
    attestation: Optional[Dict[str, Any]] = envelope.human_attestation
    if human_attestation_required and attestation is None:
        attestation = {"required": True, "fulfilled": False}
    return envelope.model_copy(
        update={
            "verdict": V3Verdict.DISCRETIONARY,
            "notes": notes,
            "human_attestation": attestation,
        }
    )


__all__ = ["RiskTier", "apply_risk_policy"]
