"""Risk-tier policies per SKI spec v3.0 §5.4.

The policy module decides, given a :class:`V3VerdictEnvelope` and a tenant-
declared risk tier, what (if any) post-processing the envelope needs before
it is returned to the caller. Examples:

* Tier-1 obligations require ``AGREED`` verifier status; if the verifier
  disagrees with the LLM, the policy forces the verdict to ``DISCRETIONARY``
  and flags ``human_attestation_required`` so the caller knows a human
  reviewer must sign off.
* Tier-2 obligations tolerate ``LLM_CONTRADICTION`` provided human
  attestation is recorded; absent attestation the verdict is downgraded.
* Tier-3 obligations are permissive — the LLM verdict stands unless the
  verifier produced an outright contradiction.
"""

from .risk_tier import RiskTier, apply_risk_policy

__all__ = ["RiskTier", "apply_risk_policy"]
