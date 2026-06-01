"""SKI Framework v3.0 §4.5 + §5.3 — Symbolic Verifier conformance.

A v3-conformant runtime MUST run a Symbolic Verifier that mechanically
cross-checks the LLM's formalizable assertions. Every produced
V3VerdictEnvelope therefore carries a VerifierResult with one of the
four spec-normative statuses.

This static test reads the reference implementation's verifier module so
it can be exercised without a live deployment.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _verifier_source(repo_root: Path) -> str:
    return (repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "verifier.py").read_text()


@pytest.mark.provenance
def test_verifier_module_exists(repo_root: Path) -> None:
    """The v3 runtime must ship a SymbolicVerifier module."""
    path = repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "verifier.py"
    assert path.exists(), (
        "v3/verifier.py is missing. Spec §5.3 requires a Symbolic Verifier "
        "module in every conformant runtime."
    )


@pytest.mark.provenance
def test_verifier_class_is_named_symbolic_verifier(repo_root: Path) -> None:
    """The verifier class MUST be exposed under the spec-normative name."""
    src = _verifier_source(repo_root)
    assert "class SymbolicVerifier" in src, "SymbolicVerifier class not found in v3/verifier.py."


@pytest.mark.provenance
def test_verifier_emits_all_four_statuses(repo_root: Path) -> None:
    """The verifier reads/emits all four VerifierStatus values."""
    src = _verifier_source(repo_root)
    for status in ("AGREED", "LLM_CONTRADICTION", "NEURO_SYMBOLIC_DIVERGENCE", "UNVERIFIABLE"):
        assert f"VerifierStatus.{status}" in src, (
            f"verifier.py never references VerifierStatus.{status}; the four-status "
            "taxonomy per spec §4.5 must be exhaustively handled."
        )


@pytest.mark.provenance
def test_verifier_supports_minimum_stateless_predicates(repo_root: Path) -> None:
    """The verifier must handle at least the five minimum stateless predicates."""
    src = _verifier_source(repo_root)
    minimum_predicates = {
        "must_not_exceed",
        "must_be_at_least",
        "must_be_within",
        "must_equal",
        "must_not_equal",
    }
    for predicate in minimum_predicates:
        assert predicate in src, (
            f"SymbolicVerifier does not handle the predicate {predicate!r}; "
            "the five stateless predicates are the v3.0 minimum."
        )


@pytest.mark.provenance
def test_risk_tier_policy_module_exists(repo_root: Path) -> None:
    """A risk-tier policy module MUST exist per spec §5.4."""
    path = repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "policies" / "risk_tier.py"
    assert path.exists(), (
        "v3/policies/risk_tier.py is missing. Spec §5.4 requires a risk-tier "
        "policy module in every conformant runtime."
    )


@pytest.mark.provenance
def test_risk_tier_module_exposes_all_three_tiers(repo_root: Path) -> None:
    """RiskTier enum lists all three spec §5.4 tiers."""
    src = (
        repo_root / "reference-implementation" / "src" / "ski_model" / "v3" / "policies" / "risk_tier.py"
    ).read_text()
    for tier in ("tier-1", "tier-2", "tier-3"):
        assert f'"{tier}"' in src, f"RiskTier enum is missing {tier!r} per spec §5.4."
