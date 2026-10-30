"""Fail-closed soundness of the v3 verifier path (finding C1, framework v3.2.0).

Regression tests for the fail-open paths found by the 2026-10-09 review and
re-verified by running code against v3.1.0:

* **OMISSION** -- the verifier only checked the assertions the LLM chose to
  emit. An LLM that asserted only a passing metric while another mapped
  obligation was breached got ``CLEAR``/``AGREED`` at every tier, tier-1
  included.
* **MASKING** -- ``UNVERIFIABLE`` was returned before contradictions were
  considered, so one junk-predicate assertion turned a mechanically
  established breach into ``UNVERIFIABLE``, which the tier-2/3 policy
  accepts => ``CLEAR``.
* **Tier-3 NEURO_SYMBOLIC_DIVERGENCE** -- after ``satisfied`` normalisation a
  CLEAR resting on an asserted breach was classified NSD, which tier-3
  accepts => ``CLEAR``.
* **Default tier** -- ``RiskTierGovernor.DEFAULT_TIER`` was ``tier-2``, so a KG
  that declared no tier (or an unknown one) never reached the tier-1
  fail-safe.
* **Edge values** -- ``-Infinity`` CLEARed ``must_not_exceed``; a bool reading
  was "normalised" to satisfied; an obligation's ``unit`` was ignored even
  when the measurement carried a different one.
* **HTTP** -- non-finite numbers and bools reached the evaluator; a malformed
  timestamp was silently replaced by "now"; a timezone-less one raised
  ``TypeError`` (HTTP 500).

The invariant every test here protects: **if any mapped, formalizable
obligation is mechanically breached, the verdict is never CLEAR -- at any
risk tier.** ``test_fail_closed_property.py`` checks the same invariant
with Hypothesis over random snapshots and adversarial LLM outputs.

New ``verifier_result.divergences`` kinds (``"<KIND>: [<obligation id>] ..."``):
``OMITTED_OBLIGATION``, ``OMITTED_OBLIGATION_UNVERIFIABLE``,
``UNFLAGGED_BREACH``, ``SCHEMA_VIOLATION`` and ``UNIT_MISMATCH``.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient
from tag_registry import RiskTierGovernor

from ski_model import server
from ski_model.kg_loader import KnowledgeGraph
from ski_model.v3 import (
    FakeLLM,
    FormalizableAssertion,
    SymbolicVerifier,
    V3Evaluator,
    V3Verdict,
    VerifierStatus,
)
from ski_model.v3 import evaluator as evaluator_module

from .test_endpoint import _install_test_state

H = "sha256:" + "d" * 64
TIERS = ("tier-1", "tier-2", "tier-3")
CLEAR = V3Verdict.CLEAR.value


def _ev(llm: Any) -> V3Evaluator:
    return V3Evaluator(llm=llm, kg_version_hash=H, decoder_seed=0)


def _run(
    llm: Any,
    measurement: Dict[str, Any],
    snapshot: Dict[str, Any],
    tier: Optional[str],
    **kwargs: Any,
) -> Any:
    return asyncio.run(
        _ev(llm).aevaluate(measurement=measurement, kg_snapshot=snapshot, risk_tier=tier, **kwargs)
    )


def _status(envelope: Any) -> str:
    return str(getattr(envelope.verifier_result.status, "value", envelope.verifier_result.status))


def _verdict(envelope: Any) -> str:
    return str(getattr(envelope.verdict, "value", envelope.verdict))


class _ScriptedLLM(FakeLLM):
    """A FakeLLM whose raw output is computed by ``script(measurement, snapshot)``."""

    def __init__(self, script: Any) -> None:
        super().__init__()
        self._script = script

    async def evaluate(
        self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        return dict(self._script(measurement, kg_snapshot))


def _cite(*ids: str) -> List[Dict[str, str]]:
    return [{"node_id": i, "version": "v1", "role": "obligation"} for i in ids]


# ---- The 2026-10-09 reproduction fixtures -------------------------------------

SO2_ONLY: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {
            "id": "so2.cap",
            "metric": "so2_ppm",
            "predicate": "must_not_exceed",
            "value": 100,
            "risk_tier": "tier-2",
        }
    ],
    "definitions": [],
}

SO2_AND_NOX: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {"id": "so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100},
        {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
    ],
    "definitions": [],
}


class JunkPredicateLLM(FakeLLM):
    """MASKING: asserts the breach truthfully-ish plus one junk-predicate assertion."""

    async def evaluate(
        self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        return {
            "verdict": "CLEAR",
            "reasoning": "compliant",
            "kg_citations": _cite("so2.cap"),
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "observed": measurement["so2_ppm"],
                    "satisfied": True,
                    "obligation_id": "so2.cap",
                },
                {
                    "predicate": "must_be_reasonable",
                    "metric": "so2_ppm",
                    "value": None,
                    "observed": measurement["so2_ppm"],
                    "satisfied": True,
                    "obligation_id": "so2.cap",
                },
            ],
        }


class OmitBreachLLM(FakeLLM):
    """OMISSION: asserts only the passing nox obligation; never mentions so2."""

    async def evaluate(
        self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        return {
            "verdict": "CLEAR",
            "reasoning": "nox fine",
            "kg_citations": _cite("nox.cap"),
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "nox_ppm",
                    "value": 50,
                    "observed": measurement["nox_ppm"],
                    "satisfied": True,
                    "obligation_id": "nox.cap",
                }
            ],
        }


class ClearWithAssertedBreachLLM(FakeLLM):
    """Asserts the real reading for the breached obligation but claims CLEAR."""

    async def evaluate(
        self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        ob = kg_snapshot["obligations"][0]
        return {
            "verdict": "CLEAR",
            "reasoning": "compliant",
            "kg_citations": _cite(ob["id"]),
            "formalizable_assertions": [
                {
                    "predicate": ob["predicate"],
                    "metric": ob["metric"],
                    "value": ob["value"],
                    "observed": measurement[ob["metric"]],
                    "satisfied": True,
                    "obligation_id": ob["id"],
                }
            ],
        }


# ---- OMISSION -----------------------------------------------------------------


class TestOmission:
    @pytest.mark.parametrize("tier", TIERS)
    def test_omitted_breach_is_never_clear(self, tier: str) -> None:
        env = _run(OmitBreachLLM(), {"so2_ppm": 150, "nox_ppm": 10}, SO2_AND_NOX, tier)
        assert _verdict(env) != CLEAR
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
        assert any(
            d.startswith("OMITTED_OBLIGATION:") and "[so2.cap] omitted by LLM; verifier says breached" in d
            for d in env.verifier_result.divergences
        ), env.verifier_result.divergences

    def test_omitted_satisfied_obligation_is_recorded_as_checked(self) -> None:
        env = _run(OmitBreachLLM(), {"so2_ppm": 50, "nox_ppm": 10}, SO2_AND_NOX, "tier-1")
        assert _verdict(env) == CLEAR
        assert _status(env) == VerifierStatus.AGREED.value
        # nox asserted + so2 independently evaluated.
        assert env.verifier_result.checked_assertions == 2
        assert any("[so2.cap]" in n and "independently" in n for n in env.notes), env.notes

    def test_omission_caught_when_llm_says_null_unmapped(self) -> None:
        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "NULL_UNMAPPED",
                "reasoning": "nothing maps",
                "kg_citations": [],
                "formalizable_assertions": [],
            }

        for tier in TIERS:
            env = _run(_ScriptedLLM(script), {"so2_ppm": 150}, SO2_ONLY, tier)
            assert _verdict(env) == V3Verdict.DISCRETIONARY.value, tier
            assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value

    def test_bogus_citation_cannot_hide_a_breach_as_unmapped(self) -> None:
        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "x",
                "kg_citations": _cite("nope"),
                "formalizable_assertions": [],
            }

        for tier in TIERS:
            env = _run(_ScriptedLLM(script), {"so2_ppm": 150}, SO2_ONLY, tier)
            assert _verdict(env) == V3Verdict.DISCRETIONARY.value, tier
            assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
            divergences = env.verifier_result.divergences
            assert "Invalid citation: nope" in divergences
            assert any("[so2.cap] omitted by LLM; verifier says breached" in d for d in divergences)
            assert env.human_attestation == {"required": True, "fulfilled": False}

    def test_bogus_citation_without_breach_is_unchanged(self) -> None:
        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "x",
                "kg_citations": _cite("nope"),
                "formalizable_assertions": [],
            }

        env = _run(_ScriptedLLM(script), {"so2_ppm": 50}, SO2_ONLY, "tier-2")
        assert _verdict(env) == V3Verdict.NULL_UNMAPPED.value
        assert _status(env) == VerifierStatus.UNVERIFIABLE.value
        assert env.verifier_result.divergences == ["Invalid citation: nope"]

    def test_omission_via_dotted_path_metric(self) -> None:
        snapshot = {
            "version": "v1",
            "obligations": [
                {"id": "stack.so2", "metric": "stack.so2_ppm", "predicate": "must_not_exceed", "value": 100},
                {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
            ],
        }
        for tier in TIERS:
            env = _run(OmitBreachLLM(), {"stack": {"so2_ppm": 150}, "nox_ppm": 10}, snapshot, tier)
            assert _verdict(env) != CLEAR, tier
            assert any("[stack.so2] omitted by LLM" in d for d in env.verifier_result.divergences)


# ---- MASKING / precedence -----------------------------------------------------


class TestMasking:
    @pytest.mark.parametrize("tier", TIERS)
    def test_junk_predicate_cannot_mask_a_breach(self, tier: str) -> None:
        env = _run(JunkPredicateLLM(), {"so2_ppm": 150}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        # Contradictions win over UNVERIFIABLE.
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
        divergences = env.verifier_result.divergences
        assert any(d.startswith("SCHEMA_VIOLATION:") and "must_be_reasonable" in d for d in divergences)
        assert any(d.startswith("UNFLAGGED_BREACH:") and "so2.cap" in d for d in divergences)

    @pytest.mark.parametrize("tier", TIERS)
    def test_junk_predicate_alone_routes_to_discretionary(self, tier: str) -> None:
        """No breach at all: the out-of-enum predicate is a schema violation,
        routed to DISCRETIONARY (spec §3.3), never CLEAR."""
        env = _run(JunkPredicateLLM(), {"so2_ppm": 50}, SO2_ONLY, tier)
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert any(d.startswith("SCHEMA_VIOLATION:") for d in env.verifier_result.divergences)
        assert env.human_attestation == {"required": True, "fulfilled": False}

    def test_in_enum_qualitative_predicate_is_not_a_schema_violation(self) -> None:
        """``discretionary`` is in the closed enumeration: honestly UNVERIFIABLE,
        not a schema violation (tier semantics unchanged)."""
        snapshot = {
            "version": "v1",
            "obligations": [
                *SO2_ONLY["obligations"],
                {"id": "so2.review", "metric": "so2_ppm", "predicate": "discretionary"},
            ],
        }

        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "ok",
                "kg_citations": _cite("so2.cap", "so2.review"),
                "formalizable_assertions": [
                    {
                        "predicate": "must_not_exceed",
                        "metric": "so2_ppm",
                        "value": 100,
                        "observed": m["so2_ppm"],
                        "satisfied": True,
                        "obligation_id": "so2.cap",
                    },
                    {
                        "predicate": "discretionary",
                        "metric": "so2_ppm",
                        "value": None,
                        "observed": m["so2_ppm"],
                        "satisfied": True,
                        "obligation_id": "so2.review",
                    },
                ],
            }

        env = _run(_ScriptedLLM(script), {"so2_ppm": 50}, snapshot, "tier-2")
        assert _status(env) == VerifierStatus.UNVERIFIABLE.value
        assert not any(d.startswith("SCHEMA_VIOLATION:") for d in env.verifier_result.divergences)
        assert _verdict(env) == CLEAR  # tier-2 accepts UNVERIFIABLE (spec §5.4 Medium)
        # ...but with the same in-enum predicate a breach still wins.
        env = _run(_ScriptedLLM(script), {"so2_ppm": 150}, snapshot, "tier-3")
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value

    def test_in_enum_predicate_on_the_wrong_obligation_is_a_kg_mismatch(self) -> None:
        """Attaching a qualitative predicate to a numeric obligation is an
        obligation mismatch (contradiction), not an escape to UNVERIFIABLE."""

        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "ok",
                "kg_citations": _cite("so2.cap"),
                "formalizable_assertions": [
                    {
                        "predicate": "discretionary",
                        "metric": "so2_ppm",
                        "value": None,
                        "observed": m["so2_ppm"],
                        "satisfied": True,
                        "obligation_id": "so2.cap",
                    },
                ],
            }

        for tier in TIERS:
            env = _run(_ScriptedLLM(script), {"so2_ppm": 50}, SO2_ONLY, tier)
            assert _verdict(env) == V3Verdict.DISCRETIONARY.value, tier
            assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
            assert any(
                "obligation mismatch" in d and "predicate" in d for d in env.verifier_result.divergences
            )

    @pytest.mark.parametrize("tier", TIERS)
    def test_clear_with_asserted_breach_is_never_clear(self, tier: str) -> None:
        """Was NEURO_SYMBOLIC_DIVERGENCE after normalisation, which tier-3 accepted."""
        env = _run(ClearWithAssertedBreachLLM(), {"so2_ppm": 150}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value

    def test_predicate_substitution_is_caught_by_kg_cross_check(self) -> None:
        """The LLM cites so2.cap but evaluates a different (valid) predicate."""

        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "ok",
                "kg_citations": _cite("so2.cap"),
                "formalizable_assertions": [
                    {
                        "predicate": "must_be_at_least",
                        "metric": "so2_ppm",
                        "value": 100,
                        "observed": m["so2_ppm"],
                        "satisfied": True,
                        "obligation_id": "so2.cap",
                    }
                ],
            }

        for tier in TIERS:
            env = _run(_ScriptedLLM(script), {"so2_ppm": 150}, SO2_ONLY, tier)
            assert _verdict(env) != CLEAR, tier
            assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
            divergences = env.verifier_result.divergences
            assert any("obligation mismatch" in d and "must_be_at_least" in d for d in divergences)
            assert any(d.startswith("UNFLAGGED_BREACH:") and "[so2.cap]" in d for d in divergences)


# ---- Sync / async verifier parity ---------------------------------------------


def _fa(**kw: Any) -> FormalizableAssertion:
    base: Dict[str, Any] = {
        "predicate": "must_not_exceed",
        "metric": "so2_ppm",
        "value": 100,
        "observed": 150,
        "satisfied": False,
        "obligation_id": "so2.cap",
    }
    base.update(kw)
    return FormalizableAssertion.model_validate(base)


def _both(
    assertions: List[FormalizableAssertion],
    *,
    llm_verdict: V3Verdict,
    measurement: Optional[Dict[str, Any]] = None,
    obligations: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[Any, Any]:
    v = SymbolicVerifier()
    sync = v.verify(assertions, llm_verdict=llm_verdict, measurement=measurement, obligations=obligations)
    asyn = asyncio.run(
        v.averify(assertions, llm_verdict=llm_verdict, measurement=measurement, obligations=obligations)
    )
    return sync, asyn


class TestVerifierParity:
    def test_contradiction_wins_over_unverifiable_without_kg(self) -> None:
        """Even without a KG slice: one real contradiction + one unverifiable
        assertion is LLM_CONTRADICTION in BOTH paths (was UNVERIFIABLE)."""
        assertions = [
            _fa(satisfied=True),  # 150 <= 100 is false: a direct contradiction
            _fa(predicate="discretionary", value=None, satisfied=True),
        ]
        for r in _both(assertions, llm_verdict=V3Verdict.CLEAR):
            assert str(r.status) == "LLM_CONTRADICTION"

    def test_omission_detected_in_both_paths(self) -> None:
        obligations = {ob["id"]: ob for ob in SO2_AND_NOX["obligations"]}
        assertions = [_fa(metric="nox_ppm", value=50, observed=10, satisfied=True, obligation_id="nox.cap")]
        for r in _both(
            assertions,
            llm_verdict=V3Verdict.CLEAR,
            measurement={"so2_ppm": 150, "nox_ppm": 10},
            obligations=obligations,
        ):
            assert str(r.status) == "LLM_CONTRADICTION"
            assert any("[so2.cap] omitted by LLM; verifier says breached" in d for d in r.divergences)

    def test_omission_detected_with_zero_assertions(self) -> None:
        obligations = {ob["id"]: ob for ob in SO2_ONLY["obligations"]}
        for r in _both(
            [], llm_verdict=V3Verdict.CLEAR, measurement={"so2_ppm": 150}, obligations=obligations
        ):
            assert str(r.status) == "LLM_CONTRADICTION"

    def test_flag_with_omitted_second_breach_is_contradiction(self) -> None:
        obligations = {ob["id"]: ob for ob in SO2_AND_NOX["obligations"]}
        assertions = [_fa(metric="nox_ppm", value=50, observed=60, satisfied=False, obligation_id="nox.cap")]
        for r in _both(
            assertions,
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2_ppm": 150, "nox_ppm": 60},
            obligations=obligations,
        ):
            assert str(r.status) == "LLM_CONTRADICTION"


# ---- Risk-tier governor default ----------------------------------------------


class TestGovernorFailSafeDefault:
    def test_snapshot_without_risk_tier_is_tier_1(self) -> None:
        snapshot = {"obligations": [{"id": "so2.cap", "metric": "so2_ppm"}]}
        assert RiskTierGovernor.tier_for_snapshot(snapshot) == "tier-1"

    @pytest.mark.parametrize("raw", ["critical", "tier-99", "", None, 7, ["tier-3"]])
    def test_unknown_tier_is_tier_1(self, raw: Any) -> None:
        snapshot = {"obligations": [{"id": "x", "risk_tier": raw}]}
        assert RiskTierGovernor.tier_for_snapshot(snapshot) == "tier-1"

    def test_unknown_tier_beside_tier_3_is_still_tier_1(self) -> None:
        """An author typo on one rule must not let the permissive tier win."""
        rules = [{"id": "a", "risk_tier": "tier-3"}, {"id": "b", "risk_tier": "teir-3"}]
        assert RiskTierGovernor.strictest_tier(rules) == "tier-1"

    def test_explicit_tiers_still_honoured(self) -> None:
        rules = [{"id": "a", "risk_tier": "tier-3"}, {"id": "b", "risk_tier": "low"}]
        assert RiskTierGovernor.strictest_tier(rules) == "tier-3"
        assert RiskTierGovernor.strictest_tier([{"id": "a", "risk_tier": "tier-2"}]) == "tier-2"

    def test_no_obligations_is_tier_1(self) -> None:
        assert RiskTierGovernor.strictest_tier([]) == "tier-1"
        assert RiskTierGovernor.tier_for_snapshot({}) == "tier-1"

    def test_spec_medium_is_tier_2(self) -> None:
        """Spec §5.4 vocabulary (low/medium/high): ``medium`` keeps the tier-2
        behaviour it had (by accident of the old default) before v3.2.0."""
        assert RiskTierGovernor.canonicalise("medium") == "tier-2"


# ---- Non-finite numbers and bools ---------------------------------------------


class TestNonFiniteAndBool:
    @pytest.mark.parametrize("reading", [-math.inf, math.inf, math.nan])
    @pytest.mark.parametrize("tier", TIERS)
    def test_fake_llm_non_finite_reading_never_clears(self, reading: float, tier: str) -> None:
        env = _run(FakeLLM(), {"so2_ppm": reading}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) != VerifierStatus.AGREED.value

    @pytest.mark.parametrize("tier", TIERS)
    def test_adversarial_clear_on_negative_infinity(self, tier: str) -> None:
        env = _run(ClearWithAssertedBreachLLM(), {"so2_ppm": -math.inf}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.UNVERIFIABLE.value

    @pytest.mark.parametrize("tier", TIERS)
    def test_bool_reading_is_never_satisfied(self, tier: str) -> None:
        """pydantic coerces an asserted ``observed: true`` to ``1.0``; a bool
        reading must not ground that number (True == 1 in Python)."""
        env = _run(FakeLLM(), {"so2_ppm": True}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
        assert any("boolean" in d for d in env.verifier_result.divergences)
        # The bool must not be "normalised" into a satisfied comparison (True <= 100).
        assert not any(a.satisfied for a in env.formalizable_assertions)

    @pytest.mark.parametrize("tier", TIERS)
    def test_bool_reading_on_must_equal_is_never_clear(self, tier: str) -> None:
        snapshot = {
            "version": "v1",
            "obligations": [{"id": "v.eq", "metric": "valve", "predicate": "must_equal", "value": 1}],
        }
        env = _run(FakeLLM(), {"valve": True}, snapshot, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) != VerifierStatus.AGREED.value

    @pytest.mark.parametrize(
        ("predicate", "value", "observed"),
        [
            ("must_not_exceed", 100, -math.inf),
            ("must_not_exceed", math.inf, 5),
            ("must_be_at_least", 5, math.inf),
            ("must_be_below", 100, -math.inf),
            ("must_be_above", 5, math.inf),
            ("must_be_within", [0, 10], math.nan),
            ("must_be_within", [-math.inf, math.inf], 5),
            ("must_not_exceed", 100, True),
            ("must_be_at_least", 0, False),
            ("must_not_equal", 0, math.nan),
            ("must_equal", 1, True),
            ("must_not_be_one_of", [1, 2], math.nan),
        ],
    )
    def test_handlers_reject_non_finite_and_bool(self, predicate: str, value: Any, observed: Any) -> None:
        a = FormalizableAssertion.model_construct(
            predicate=predicate,
            metric="m",
            value=value,
            observed=observed,
            satisfied=True,
            obligation_id="ob",
            window_seconds=None,
        )
        assert SymbolicVerifier().check_assertion(a).mechanically_satisfied is None


# ---- Units --------------------------------------------------------------------

UNIT_SNAPSHOT: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {"id": "so2.cap", "metric": "so2", "predicate": "must_not_exceed", "value": 100, "unit": "ppm"}
    ],
}


class TestUnits:
    """A measurement carries a unit with the v2 ``{"value": x, "unit": u}`` shape."""

    def test_bare_reading_keeps_behaviour(self) -> None:
        env = _run(FakeLLM(), {"so2": 90}, UNIT_SNAPSHOT, "tier-1")
        assert _verdict(env) == CLEAR
        assert _status(env) == VerifierStatus.AGREED.value

    @pytest.mark.parametrize("tier", TIERS)
    def test_unit_mismatch_fails_closed(self, tier: str) -> None:
        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "90 <= 100",
                "kg_citations": _cite("so2.cap"),
                "formalizable_assertions": [
                    {
                        "predicate": "must_not_exceed",
                        "metric": "so2",
                        "value": 100,
                        "observed": 90,
                        "satisfied": True,
                        "obligation_id": "so2.cap",
                    }
                ],
            }

        env = _run(_ScriptedLLM(script), {"so2": {"value": 90, "unit": "mg/m3"}}, UNIT_SNAPSHOT, tier)
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert _status(env) != VerifierStatus.AGREED.value
        assert any(d.startswith("UNIT_MISMATCH:") for d in env.verifier_result.divergences)
        assert env.human_attestation == {"required": True, "fulfilled": False}

    def test_unit_mismatch_on_omitted_obligation_fails_closed(self) -> None:
        env = _run(
            OmitBreachLLM(),
            {"so2": {"value": 90, "unit": "ppb"}, "nox_ppm": 10},
            {
                "version": "v1",
                "obligations": [
                    *UNIT_SNAPSHOT["obligations"],
                    {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
                ],
            },
            "tier-3",
        )
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert _status(env) == VerifierStatus.UNVERIFIABLE.value
        assert any(
            d.startswith("UNIT_MISMATCH:") and "[so2.cap]" in d for d in env.verifier_result.divergences
        )

    def test_matching_unit_is_evaluated_independently(self) -> None:
        """Same unit: the verifier evaluates the wrapped value, so an omitted
        breach is still caught."""
        snapshot = {
            "version": "v1",
            "obligations": [
                *UNIT_SNAPSHOT["obligations"],
                {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
            ],
        }
        for tier in TIERS:
            env = _run(OmitBreachLLM(), {"so2": {"value": 150, "unit": "ppm"}, "nox_ppm": 10}, snapshot, tier)
            assert _verdict(env) == V3Verdict.DISCRETIONARY.value, tier
            assert any(
                "[so2.cap] omitted by LLM; verifier says breached" in d
                for d in env.verifier_result.divergences
            )
            assert not any(d.startswith("UNIT_MISMATCH:") for d in env.verifier_result.divergences)


# ---- Stateful enumeration ------------------------------------------------------


@dataclass
class _Agg:
    avg_value: Optional[float]
    max_value: Optional[float]
    count: int = 1


class _AggBuffer:
    def __init__(self, avg: float, peak: float) -> None:
        self._r = _Agg(avg_value=avg, max_value=peak)

    async def window_query(self, **_: Any) -> Any:
        return self._r


STATEFUL_SNAPSHOT: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {
            "id": "so2.peak",
            "metric": "so2_ppm",
            "predicate": "must_not_exceed_in_window",
            "value": 100,
            "window_seconds": 3600,
        },
        {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
    ],
}


class TestStatefulEnumeration:
    _AS_OF = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    def test_omitted_stateful_breach_is_contradiction(self) -> None:
        for tier in TIERS:
            env = _run(
                OmitBreachLLM(),
                {"so2_ppm": 80, "nox_ppm": 10},
                STATEFUL_SNAPSHOT,
                tier,
                subject="stack-1",
                as_of=self._AS_OF,
                buffer=_AggBuffer(avg=80.0, peak=140.0),
            )
            assert _verdict(env) != CLEAR, tier
            assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value
            assert any(
                "[so2.peak] omitted by LLM; verifier says breached" in d
                for d in env.verifier_result.divergences
            )

    def test_omitted_stateful_satisfied_is_agreed(self) -> None:
        env = _run(
            OmitBreachLLM(),
            {"so2_ppm": 80, "nox_ppm": 10},
            STATEFUL_SNAPSHOT,
            "tier-1",
            subject="stack-1",
            as_of=self._AS_OF,
            buffer=_AggBuffer(avg=80.0, peak=90.0),
        )
        assert _verdict(env) == CLEAR
        assert _status(env) == VerifierStatus.AGREED.value
        assert env.verifier_result.checked_assertions == 2

    def test_omitted_stateful_without_buffer_is_unverifiable(self) -> None:
        env = _run(OmitBreachLLM(), {"so2_ppm": 80, "nox_ppm": 10}, STATEFUL_SNAPSHOT, "tier-1")
        assert _status(env) == VerifierStatus.UNVERIFIABLE.value
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value  # tier-1 requires AGREED
        assert any(d.startswith("OMITTED_OBLIGATION_UNVERIFIABLE:") for d in env.verifier_result.divergences)


# ---- Defence in depth: the breach floor is independent of the tier policy ------


def test_breach_floor_holds_even_if_the_tier_policy_accepts_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a future policy (e.g. spec §5.4 "Low: honour the LLM verdict") passed
    every envelope through untouched, a mechanically established breach must
    still never ship as CLEAR."""
    monkeypatch.setattr(evaluator_module, "apply_risk_policy", lambda envelope, risk_tier: envelope)
    for llm, measurement, snapshot in [
        (ClearWithAssertedBreachLLM(), {"so2_ppm": 150}, SO2_ONLY),
        (OmitBreachLLM(), {"so2_ppm": 150, "nox_ppm": 10}, SO2_AND_NOX),
        (JunkPredicateLLM(), {"so2_ppm": 150}, SO2_ONLY),
    ]:
        env = _run(llm, measurement, snapshot, "tier-3")
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert any(n.startswith("breach_floor:") for n in env.notes), env.notes


# ---- HTTP layer -----------------------------------------------------------------


def _payload(measurement: Dict[str, Any], timestamp: str = "2026-01-15T12:00:00Z") -> str:
    import json

    return json.dumps(
        {"measurement_id": "m-1", "timestamp": timestamp, "subject": "emissions", "measurement": measurement},
        allow_nan=True,
    )


@pytest.fixture
def client() -> Iterator[Tuple[TestClient, Any]]:
    ledger = _install_test_state()
    yield TestClient(server.app, raise_server_exceptions=False), ledger


def _post(c: TestClient, body: str) -> Any:
    return c.post("/api/evaluate", content=body, headers={"content-type": "application/json"})


class TestHttpRejectsMalformedInput:
    @pytest.mark.parametrize(
        "measurement",
        [
            {"so2_ppm": -math.inf},
            {"so2_ppm": math.inf},
            {"so2_ppm": math.nan},
            {"other": {"nested": [1, math.inf]}},  # anywhere in the record
        ],
    )
    def test_non_finite_numbers_are_422(self, client: Any, measurement: Dict[str, Any]) -> None:
        c, ledger = client
        resp = _post(c, _payload(measurement))
        assert resp.status_code == 422, resp.text
        assert ledger.appended == []

    def test_bool_where_a_number_is_expected_is_422(self, client: Any) -> None:
        c, ledger = client
        resp = _post(c, _payload({"so2_ppm": True}))
        assert resp.status_code == 422, resp.text
        assert "so2_ppm" in resp.text
        assert ledger.appended == []

    def test_bool_on_a_metric_with_no_numeric_obligation_is_accepted(self, client: Any) -> None:
        c, _ledger = client
        resp = _post(c, _payload({"so2_ppm": 50, "door_open": True}))
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "timestamp",
        [
            "garbage",
            "",
            "2026-13-45T99:00:00Z",
            "2026-01-15T12:00:00",  # timezone-less
            "2026-01-15",  # date only => timezone-less
        ],
    )
    def test_bad_timestamps_are_422(self, client: Any, timestamp: str) -> None:
        c, ledger = client
        resp = _post(c, _payload({"so2_ppm": 50}, timestamp=timestamp))
        assert resp.status_code == 422, resp.text
        assert ledger.appended == []

    @pytest.mark.parametrize(
        "timestamp", ["2026-01-15T12:00:00Z", "2026-01-15T12:00:00+00:00", "2026-01-15T07:00:00-05:00"]
    )
    def test_timezone_aware_timestamps_are_accepted(self, client: Any, timestamp: str) -> None:
        c, _ledger = client
        resp = _post(c, _payload({"so2_ppm": 50}, timestamp=timestamp))
        assert resp.status_code == 200, resp.text

    def test_timestamp_is_never_replaced_by_now(self, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """The parsed timestamp (not wall-clock) is what scoping sees."""
        c, _ledger = client
        seen: List[datetime] = []
        kg: KnowledgeGraph = server.state.knowledge_graph  # type: ignore[assignment]
        original = kg.scope_to

        def spy(*, jurisdiction: Optional[str], as_of: datetime) -> Dict[str, Any]:
            seen.append(as_of)
            return original(jurisdiction=jurisdiction, as_of=as_of)

        monkeypatch.setattr(kg, "scope_to", spy)
        resp = _post(c, _payload({"so2_ppm": 50}, timestamp="2026-01-15T07:00:00-05:00"))
        assert resp.status_code == 200, resp.text
        assert seen == [datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)]
        assert abs(seen[0] - datetime.now(timezone.utc)) > timedelta(days=1)


# ---- Integers beyond the double range --------------------------------------------


class TestHugeIntegers:
    """``json.loads`` turns ``1e400``-sized integer literals into Python ints;
    ``float()`` on them raises ``OverflowError`` (an HTTP 500 before v3.2.0)."""

    @pytest.mark.parametrize("tier", TIERS)
    def test_huge_reading_is_a_breach_not_a_crash(self, tier: str) -> None:
        env = _run(ClearWithAssertedBreachLLM(), {"so2_ppm": 10**400}, SO2_ONLY, tier)
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value

    def test_huge_negative_reading_is_compared_exactly(self) -> None:
        a = _fa(observed=-(10**400), satisfied=True)
        assert SymbolicVerifier().check_assertion(a).mechanically_satisfied is True

    @pytest.mark.parametrize("tier", TIERS)
    def test_huge_stateful_bound_is_still_decidable(self, tier: str) -> None:
        """Found by the property test: a KG bound beyond the double range made
        the stateful check UNVERIFIABLE (tier-2/3 accept => CLEAR) although
        an average of 0 below a lower bound of 1 is a decidable breach."""
        snapshot = {
            "version": "v1",
            "obligations": [
                {
                    "id": "so2.avg",
                    "metric": "so2_ppm",
                    "predicate": "must_average_within",
                    "value": [1, 10**400],
                    "window_seconds": 60,
                }
            ],
        }
        env = _run(
            ClearWithAssertedBreachLLM(),
            {"so2_ppm": 0},
            snapshot,
            tier,
            subject="stack-1",
            as_of=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            buffer=_AggBuffer(avg=0.0, peak=0.0),
        )
        assert _verdict(env) != CLEAR
        assert _status(env) == VerifierStatus.LLM_CONTRADICTION.value

    def test_huge_integer_is_422_at_the_api(self, client: Any) -> None:
        c, ledger = client
        body = (
            '{"measurement_id": "m-1", "timestamp": "2026-01-15T12:00:00Z", '
            '"subject": "emissions", "measurement": {"so2_ppm": 1' + "0" * 400 + "}}"
        )
        resp = _post(c, body)
        assert resp.status_code == 422, resp.text
        assert ledger.appended == []


# ---- Obligations the id index would hide -----------------------------------------


class TestShadowedObligations:
    """The verifier enumerates by obligation id; an obligation with no id, or a
    repeated id, must not silently drop out of the independent enumeration."""

    DUPLICATE: ClassVar[Dict[str, Any]] = {
        "version": "v1",
        "obligations": [
            {"id": "nox.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100},
            {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
        ],
    }
    ID_LESS: ClassVar[Dict[str, Any]] = {
        "version": "v1",
        "obligations": [
            {"metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100},
            {"id": "nox.cap", "metric": "nox_ppm", "predicate": "must_not_exceed", "value": 50},
        ],
    }

    @pytest.mark.parametrize("snapshot_name", ["DUPLICATE", "ID_LESS"])
    @pytest.mark.parametrize("tier", TIERS)
    def test_hidden_breach_fails_closed(self, snapshot_name: str, tier: str) -> None:
        snapshot = getattr(self, snapshot_name)
        env = _run(OmitBreachLLM(), {"so2_ppm": 150, "nox_ppm": 10}, snapshot, tier)
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert any(d.startswith("SCHEMA_VIOLATION:") for d in env.verifier_result.divergences)

    def test_hidden_obligation_without_a_reading_is_ignored(self) -> None:
        """Nothing to evaluate (metric absent): no violation, behaviour unchanged."""
        env = _run(OmitBreachLLM(), {"nox_ppm": 10}, self.ID_LESS, "tier-1")
        assert _verdict(env) == CLEAR
        assert _status(env) == VerifierStatus.AGREED.value

    def test_hidden_breach_fails_closed_on_the_citation_path(self) -> None:
        def script(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "verdict": "CLEAR",
                "reasoning": "x",
                "kg_citations": _cite("nope"),
                "formalizable_assertions": [],
            }

        env = _run(_ScriptedLLM(script), {"so2_ppm": 150, "nox_ppm": 10}, self.ID_LESS, "tier-3")
        assert _verdict(env) == V3Verdict.DISCRETIONARY.value
        assert any(d.startswith("SCHEMA_VIOLATION:") for d in env.verifier_result.divergences)
