"""Tests for :class:`tag_registry.RiskTierGovernor` (spec v3.0 §5.4).

The governor is the *strict* source of risk-tier truth in v3. The
caller cannot influence the verdict — these tests pin that contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from tag_registry import RiskTierGovernor

# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("tier-1", "tier-1"),
        ("tier1", "tier-1"),
        ("TIER-1", "tier-1"),
        ("  tier-1  ", "tier-1"),
        ("high", "tier-1"),
        ("high-risk", "tier-1"),
        ("tier-2", "tier-2"),
        ("tier2", "tier-2"),
        ("standard", "tier-2"),
        ("default", "tier-2"),
        ("tier-3", "tier-3"),
        ("tier3", "tier-3"),
        ("low", "tier-3"),
        ("low-risk", "tier-3"),
    ],
)
def test_canonicalise_recognised_inputs(raw: str, expected: str) -> None:
    assert RiskTierGovernor.canonicalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "nonsense", "tier-99", "high_risk", None, 42, 1.0, [], {}, object()],
)
def test_canonicalise_unknown_collapses_to_default(raw: Any) -> None:
    assert RiskTierGovernor.canonicalise(raw) == RiskTierGovernor.DEFAULT_TIER
    assert RiskTierGovernor.DEFAULT_TIER == "tier-2"


# ---------------------------------------------------------------------------
# Strictest-tier semantics
# ---------------------------------------------------------------------------


def test_strictest_tier_empty_input_returns_default() -> None:
    assert RiskTierGovernor.strictest_tier([]) == "tier-2"


def test_strictest_tier_picks_minimum_rank() -> None:
    rules = [
        {"id": "a", "risk_tier": "tier-3"},
        {"id": "b", "risk_tier": "tier-2"},
        {"id": "c", "risk_tier": "tier-1"},  # strictest
    ]
    assert RiskTierGovernor.strictest_tier(rules) == "tier-1"


def test_strictest_tier_ignores_unknown_values_as_default() -> None:
    # An unknown tier ("nonsense") collapses to tier-2 (DEFAULT_TIER), so
    # the strictest across the set is still tier-2 — not tier-3.
    rules = [
        {"id": "a", "risk_tier": "nonsense"},
        {"id": "b", "risk_tier": "tier-3"},
    ]
    assert RiskTierGovernor.strictest_tier(rules) == "tier-2"


def test_strictest_tier_missing_field_defaults_to_tier_2() -> None:
    rules = [{"id": "a"}, {"id": "b"}]
    assert RiskTierGovernor.strictest_tier(rules) == "tier-2"


def test_strictest_tier_all_tier_3() -> None:
    rules = [{"id": "a", "risk_tier": "tier-3"}, {"id": "b", "risk_tier": "low"}]
    assert RiskTierGovernor.strictest_tier(rules) == "tier-3"


# ---------------------------------------------------------------------------
# Snapshot convenience
# ---------------------------------------------------------------------------


def test_tier_for_snapshot_reads_obligations_list() -> None:
    snapshot: dict[str, Any] = {
        "version": "test-001",
        "obligations": [
            {"id": "x", "risk_tier": "tier-2"},
            {"id": "y", "risk_tier": "tier-1"},
        ],
        "scope": {},
    }
    assert RiskTierGovernor.tier_for_snapshot(snapshot) == "tier-1"


def test_tier_for_snapshot_empty_obligations_returns_default() -> None:
    snapshot: dict[str, Any] = {"version": "test-001", "obligations": [], "scope": {}}
    assert RiskTierGovernor.tier_for_snapshot(snapshot) == "tier-2"


def test_tier_for_snapshot_missing_obligations_key_returns_default() -> None:
    # A pathological / partial snapshot should not crash — it defaults.
    assert RiskTierGovernor.tier_for_snapshot({}) == "tier-2"


# ---------------------------------------------------------------------------
# Strict-governor contract
# ---------------------------------------------------------------------------


def test_caller_cannot_influence_tier_via_obligation_payload() -> None:
    """The governor reads ONLY the rule's own ``risk_tier`` field.

    A KG-authored rule pins the tier. Anything else (an extra attribute
    on the obligation that *looks* tier-like, e.g. ``"tier_hint"``) is
    ignored. This is the strict-governor invariant: tier is on the rule,
    not on the request.
    """
    rules = [
        {"id": "a", "risk_tier": "tier-2", "tier_hint": "tier-3"},
        {"id": "b", "risk_tier": "tier-2", "caller_override": "tier-3"},
    ]
    assert RiskTierGovernor.strictest_tier(rules) == "tier-2"
