"""Tests for the v3 risk-tier policy module (spec v3.0 §5.4).

The policy is mechanical: given an envelope and a tier, return the same
envelope or a downgraded one. No LLM. No I/O.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ski_model.v3 import (
    FormalizableAssertion,
    KGCitation,
    KGCitationRole,
    ModelProvenance,
    RiskTier,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
    apply_risk_policy,
)

_HASH = "sha256:" + "a" * 64


def _envelope(
    *,
    verdict: V3Verdict = V3Verdict.CLEAR,
    verifier_status: VerifierStatus = VerifierStatus.AGREED,
    human_attestation: Dict[str, Any] | None = None,
) -> V3VerdictEnvelope:
    return V3VerdictEnvelope(
        verdict=verdict,
        reasoning="for tests",
        kg_citations=[KGCitation(node_id="ob.x", version="v1", role=KGCitationRole.OBLIGATION)],
        formalizable_assertions=[
            FormalizableAssertion(
                predicate="must_not_exceed",
                metric="x",
                value=100,
                observed=50,
                satisfied=True,
                obligation_id="ob.x",
            )
        ],
        verifier_result=VerifierResult(status=verifier_status, checked_assertions=1, divergences=[]),
        model_provenance=ModelProvenance(
            model_weight_hash=_HASH,
            kg_version_hash=_HASH,
            prompt_template_id="ski.v3.evaluate.1",
            prompt_template_hash=_HASH,
            decoder_seed=0,
            structured_grammar_hash=_HASH,
        ),
        transcript_ref="ledger:t/seq:1",
        human_attestation=human_attestation,
    )


# ---- Tier-1: high-risk --------------------------------------------------------


class TestTier1:
    def test_agreed_passes_through(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.AGREED)
        out = apply_risk_policy(env, risk_tier="tier-1")
        assert out.verdict == V3Verdict.CLEAR.value
        assert out.human_attestation is None
        assert out.notes == []

    def test_contradiction_forces_discretionary_and_attestation_required(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.LLM_CONTRADICTION)
        out = apply_risk_policy(env, risk_tier="tier-1")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert out.human_attestation is not None
        assert out.human_attestation["required"] is True
        assert any("tier-1" in n for n in out.notes)

    def test_unverifiable_also_forces_discretionary(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.UNVERIFIABLE)
        out = apply_risk_policy(env, risk_tier="tier-1")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert out.human_attestation is not None

    def test_neuro_symbolic_divergence_also_forces_discretionary(self) -> None:
        """tier-1 requires AGREED; ANY other status downgrades — this pins
        the third non-AGREED status (LLM_CONTRADICTION and UNVERIFIABLE are
        covered above), closing the "ANY" in the spec §5.4 requirement."""
        env = _envelope(verifier_status=VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE)
        out = apply_risk_policy(env, risk_tier="tier-1")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert out.human_attestation is not None
        assert out.human_attestation["required"] is True
        assert any("tier-1" in n for n in out.notes)


# ---- Tier-2: standard ---------------------------------------------------------


class TestTier2:
    def test_agreed_passes_through(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.AGREED)
        out = apply_risk_policy(env, risk_tier="standard")
        assert out.verdict == V3Verdict.CLEAR.value

    def test_contradiction_without_attestation_forces_discretionary(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.LLM_CONTRADICTION)
        out = apply_risk_policy(env, risk_tier="standard")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert any("tier-2" in n for n in out.notes)

    def test_contradiction_with_attestation_keeps_verdict(self) -> None:
        env = _envelope(
            verifier_status=VerifierStatus.LLM_CONTRADICTION,
            human_attestation={"reviewer": "rk@ski.example", "fulfilled": True},
        )
        out = apply_risk_policy(env, risk_tier="standard")
        assert out.verdict == V3Verdict.CLEAR.value
        assert out.human_attestation == {"reviewer": "rk@ski.example", "fulfilled": True}

    def test_unverifiable_records_note_but_keeps_verdict(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.UNVERIFIABLE)
        out = apply_risk_policy(env, risk_tier="standard")
        assert out.verdict == V3Verdict.CLEAR.value
        assert any("UNVERIFIABLE" in n for n in out.notes)


# ---- Tier-3: low-risk ---------------------------------------------------------


class TestTier3:
    def test_agreed_passes_through(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.AGREED)
        out = apply_risk_policy(env, risk_tier="low")
        assert out.verdict == V3Verdict.CLEAR.value

    def test_contradiction_downgrades_to_discretionary(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.LLM_CONTRADICTION)
        out = apply_risk_policy(env, risk_tier="tier-3")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert any("tier-3" in n for n in out.notes)

    def test_unverifiable_accepted_with_note(self) -> None:
        env = _envelope(verifier_status=VerifierStatus.UNVERIFIABLE)
        out = apply_risk_policy(env, risk_tier="tier-3")
        assert out.verdict == V3Verdict.CLEAR.value
        assert any("UNVERIFIABLE" in n for n in out.notes)


# ---- Aliases + errors ---------------------------------------------------------


class TestTierResolution:
    @pytest.mark.parametrize("alias", ["high", "high-risk", "tier1", "TIER-1"])
    def test_tier1_aliases(self, alias: str) -> None:
        env = _envelope(verifier_status=VerifierStatus.LLM_CONTRADICTION)
        out = apply_risk_policy(env, risk_tier=alias)
        assert out.verdict == V3Verdict.DISCRETIONARY.value

    @pytest.mark.parametrize("alias", ["standard", "default", "tier2", "TIER-2"])
    def test_tier2_aliases(self, alias: str) -> None:
        env = _envelope(verifier_status=VerifierStatus.AGREED)
        out = apply_risk_policy(env, risk_tier=alias)
        assert out.verdict == V3Verdict.CLEAR.value

    def test_absent_tier_behaves_as_tier1(self) -> None:
        """Audit finding A4: no declared tier is unknown criticality, which
        must fail safe to the most conservative tier -- never a lower one,
        never a crash."""
        env = _envelope(verifier_status=VerifierStatus.UNVERIFIABLE)
        out = apply_risk_policy(env, risk_tier=None)
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert out.human_attestation is not None
        assert out.human_attestation["required"] is True
        assert any("risk_tier not declared" in n and "tier-1" in n for n in out.notes)

    def test_absent_tier_coercion_is_recorded_even_when_agreed(self) -> None:
        """The coercion must be auditable even in the one case
        (AGREED) that would otherwise return the envelope untouched."""
        env = _envelope(verifier_status=VerifierStatus.AGREED)
        out = apply_risk_policy(env, risk_tier=None)
        assert out.verdict == V3Verdict.CLEAR.value
        assert any("risk_tier not declared" in n for n in out.notes)

    def test_unrecognised_tier_behaves_as_tier1_with_a_note(self) -> None:
        """An unrecognised tier string must never raise or silently fall
        back to a lower tier -- it fails safe to tier-1, same as absent."""
        env = _envelope(verifier_status=VerifierStatus.LLM_CONTRADICTION)
        out = apply_risk_policy(env, risk_tier="ultra-mega-critical")
        assert out.verdict == V3Verdict.DISCRETIONARY.value
        assert out.human_attestation is not None
        assert out.human_attestation["required"] is True
        assert any("ultra-mega-critical" in n and "not recognised" in n and "tier-1" in n for n in out.notes)


# ---- RiskTier enum coverage ---------------------------------------------------


class TestRiskTierEnum:
    def test_three_tiers(self) -> None:
        assert {t.value for t in RiskTier} == {"tier-1", "tier-2", "tier-3"}
