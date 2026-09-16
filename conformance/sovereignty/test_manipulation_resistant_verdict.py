"""SKI Framework v3.0 §5.3 + §4.1 + §5.4 — Manipulation-resistant verdicts.

Threat model T9, "LLM prompt injection via telemetry"
(docs/RFCs/0002-v3-neuro-symbolic-pivot.md, "Security implications"): a
compromised telemetry source (SCADA, sensors, ETL) attempts to subvert the
LLM into emitting a fabricated CLEAR for a genuine breach. Per the trust
model (docs/threat-model.md), the telemetry source is explicitly "not
trusted for: deciding which rule applies" — a successful injection would
mean the framework itself certifies a real breach as compliant. This is
the highest-consequence OT threat in the model.

Black-box: we assert the structural guard rails the RFC's promised
mitigation depends on are present in the reference implementation —
independent grounding of the LLM's claims against the measurement and the
cited obligation, mechanical recomputation of ``satisfied`` rather than
trusting the LLM's own claim, and a risk-tier policy that downgrades any
disagreement rather than passing it through. The *functional* proof — a
scripted FakeLLM simulating a successful injection, showing a real breach
is never CLEARed even when the LLM has been "convinced" — lives in the
runtime suite (``v3/tests/test_adversarial_telemetry.py``), the same
split used for ``test_signed_llm_transcript.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

V3 = ("reference-implementation", "src", "ski_model", "v3")


@pytest.mark.sovereignty
def test_verifier_grounds_assertions_against_the_measurement(repo_root: Path) -> None:
    """An LLM's claimed ``observed`` value must be checked against the
    actual measurement record — a fabricated reading must not verify just
    because the arithmetic built on it is internally consistent."""
    verifier = (repo_root.joinpath(*V3, "verifier.py")).read_text()
    assert "_grounding_violation" in verifier, (
        "no measurement-grounding guard: a fabricated 'observed' value would verify."
    )
    assert "fabricated observation" in verifier


@pytest.mark.sovereignty
def test_verifier_grounds_assertions_against_the_cited_obligation(repo_root: Path) -> None:
    """An LLM's claimed obligation metric/value must be checked against
    the KG node it cites — a fabricated cap must not verify."""
    verifier = (repo_root.joinpath(*V3, "verifier.py")).read_text()
    assert "_obligation_grounding_violation" in verifier, (
        "no obligation-grounding guard: a fabricated cap or metric would verify."
    )
    assert "fabricated obligation" in verifier


@pytest.mark.sovereignty
def test_verifier_recomputes_satisfied_rather_than_trusting_the_llm(repo_root: Path) -> None:
    """The mechanically-correct ``satisfied`` value must be computed and
    substituted for the LLM's own claim — a "convinced" LLM's boolean is
    not authoritative on its own."""
    verifier = (repo_root.joinpath(*V3, "verifier.py")).read_text()
    assert "def normalize_satisfied" in verifier, (
        "no satisfied-flag normalisation: the LLM's own (possibly manipulated) claim would stand uncorrected."
    )


@pytest.mark.sovereignty
def test_taxonomy_guard_forbids_an_unverifiable_clear(repo_root: Path) -> None:
    """CLEAR asserts *verified* satisfaction (spec §4.1) — a CLEAR with no
    checkable assertions must be remapped, never shipped as-is."""
    evaluator = (repo_root.joinpath(*V3, "evaluator.py")).read_text()
    assert "taxonomy_guard" in evaluator
    assert "NULL_UNMAPPED" in evaluator and "DISCRETIONARY" in evaluator


@pytest.mark.sovereignty
def test_risk_policy_downgrades_verdicts_the_verifier_disagrees_with(repo_root: Path) -> None:
    """Every risk tier must react to a disagreeing verifier by downgrading
    the verdict — LLM_CONTRADICTION and NEURO_SYMBOLIC_DIVERGENCE must
    never be silently passed through as the LLM's original verdict."""
    policy = (repo_root.joinpath(*V3, "policies", "risk_tier.py")).read_text()
    assert "VerifierStatus.LLM_CONTRADICTION" in policy
    assert "VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE" in policy
    assert "_downgrade_to_discretionary" in policy, (
        "no downgrade path: a disagreeing verifier must never be silently accepted."
    )
