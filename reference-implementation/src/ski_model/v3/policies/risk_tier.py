"""Risk-tier policy — post-processing of a V3VerdictEnvelope per spec v3.0 §5.4.

The *effective* risk tier is derived from the signed Knowledge Graph, not
declared by the caller: ``MeasurementRecord`` carries no ``risk_tier``
field, and the server computes ``risk_tier`` for :func:`apply_risk_policy`
via ``RiskTierGovernor.tier_for_snapshot(kg_snapshot)`` (strictest tier
across the scoped snapshot's obligations). A caller cannot send
``risk_tier=tier-3`` to evade the policy of a KG rule that is actually
tier-1 -- see ``tag_registry.registry.RiskTierGovernor`` for the strict-
governor design this depends on. The evaluator runs the LLM and the
:class:`SymbolicVerifier`, then this module decides whether the envelope
can be returned as-is or must be downgraded / annotated.

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

Audit finding A4 (fail-safe default tiering): a measurement that declares
no tier, or an unrecognised one, has unknown criticality — treating that
as tier-2/tier-3 would silently apply a *more permissive* policy to the
one case where the framework knows the least. :func:`_normalise_tier`
therefore resolves an absent or unrecognised tier to ``tier-1`` (the most
conservative) rather than raising or falling back to a lower tier. The
coercion is always recorded in the envelope's ``notes`` so it is
auditable, even when the verifier result is ``AGREED`` (the one case that
would otherwise return the envelope untouched).
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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


def _normalise_tier(tier: Optional[str]) -> Tuple[RiskTier, Optional[str]]:
    """Resolve a caller-declared risk tier, failing safe on the unknown.

    Returns ``(resolved_tier, coercion_note)``. ``coercion_note`` is
    ``None`` when ``tier`` was a recognised, explicitly-declared value
    (behaviour unchanged); otherwise it explains why the fail-safe
    ``tier-1`` default was applied, for the caller to record in the
    envelope's audit trail.
    """
    if tier is None or not tier.strip():
        return RiskTier.TIER_1, (
            "risk_tier not declared; defaulting to tier-1 (fail-safe: unknown criticality "
            "is never assumed low-risk)."
        )
    key = tier.strip().lower()
    resolved = _ALIAS_MAP.get(key)
    if resolved is None:
        return RiskTier.TIER_1, (
            f"risk_tier {tier!r} not recognised (expected one of: {sorted(_ALIAS_MAP)}); "
            "defaulting to tier-1 (fail-safe: unknown criticality is never assumed low-risk)."
        )
    return resolved, None


def apply_risk_policy(envelope: V3VerdictEnvelope, risk_tier: Optional[str]) -> V3VerdictEnvelope:
    """Apply the spec §5.4 policy for ``risk_tier`` to ``envelope``.

    ``SKI_FORCE_DISCRETIONARY_ON_UNVERIFIABLE`` (default ``false``): when
    ``true``, any ``UNVERIFIABLE`` verifier status forces ``DISCRETIONARY``
    regardless of tier. Spec §5.4 already gives tier-1 this behaviour;
    this flag extends it to tier-2/tier-3 for operators who would rather
    over-flag qualitative obligations than rely solely on KG authoring
    (see kg-validator's ``UNDER_TIERED_QUALITATIVE_OBLIGATION`` check) to
    catch an under-tiered one.
    """
    tier, coercion_note = _normalise_tier(risk_tier)
    status = envelope.verifier_result.status
    notes: List[str] = list(envelope.notes)
    if coercion_note is not None:
        notes.append(coercion_note)

    if status == VerifierStatus.AGREED:
        if coercion_note is not None:
            return envelope.model_copy(update={"notes": notes})
        return envelope

    if (
        status == VerifierStatus.UNVERIFIABLE
        and os.getenv("SKI_FORCE_DISCRETIONARY_ON_UNVERIFIABLE", "false").strip().lower() == "true"
    ):
        notes.append(
            "SKI_FORCE_DISCRETIONARY_ON_UNVERIFIABLE=true: UNVERIFIABLE forces "
            "DISCRETIONARY regardless of risk tier."
        )
        return _downgrade_to_discretionary(envelope, notes=notes, human_attestation_required=True)

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
    # ``model_copy`` skips validation, so ``use_enum_values`` would not
    # convert an enum member here -- pass the plain value to keep the
    # envelope's ``verdict`` a ``str`` like every validated envelope.
    return envelope.model_copy(
        update={
            "verdict": V3Verdict.DISCRETIONARY.value,
            "notes": notes,
            "human_attestation": attestation,
        }
    )


__all__ = ["RiskTier", "apply_risk_policy"]
