"""Tests for the v3 Symbolic Verifier.

These tests construct :class:`FormalizableAssertion` instances directly
(no LLM) so we can drive every status code in :class:`VerifierStatus`:
AGREED, LLM_CONTRADICTION, NEURO_SYMBOLIC_DIVERGENCE, UNVERIFIABLE.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from ski_model.v3 import (
    FormalizableAssertion,
    SymbolicVerifier,
    V3Verdict,
    VerifierStatus,
)


def _assertion(
    *,
    predicate: str,
    metric: str = "x",
    value: Any = 100,
    observed: Any = 50,
    satisfied: bool = True,
    obligation_id: str = "ob.test",
) -> FormalizableAssertion:
    return FormalizableAssertion(
        predicate=predicate,
        metric=metric,
        value=value,
        observed=observed,
        satisfied=satisfied,
        obligation_id=obligation_id,
    )


# ---- AGREED -------------------------------------------------------------------


class TestAgreed:
    def test_single_assertion_within_limit_yields_agreed(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=50, satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.AGREED.value
        assert result.checked_assertions == 1
        assert result.divergences == []

    def test_must_be_within_range_yields_agreed(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [
                _assertion(
                    predicate="must_be_within",
                    value=[6.0, 8.5],
                    observed=7.2,
                    satisfied=True,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.AGREED.value

    def test_flag_verdict_with_unsatisfied_assertion_yields_agreed(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=200, satisfied=False)],
            llm_verdict=V3Verdict.FLAG,
        )
        assert result.status == VerifierStatus.AGREED.value
        assert result.checked_assertions == 1

    def test_multiple_assertions_all_agree(self) -> None:
        v = SymbolicVerifier()
        assertions: List[FormalizableAssertion] = [
            _assertion(
                predicate="must_not_exceed",
                metric="a",
                value=100,
                observed=50,
                satisfied=True,
                obligation_id="ob.a",
            ),
            _assertion(
                predicate="must_be_at_least",
                metric="b",
                value=5,
                observed=10,
                satisfied=True,
                obligation_id="ob.b",
            ),
        ]
        result = v.verify(assertions, llm_verdict=V3Verdict.CLEAR)
        assert result.status == VerifierStatus.AGREED.value
        assert result.checked_assertions == 2


# ---- LLM_CONTRADICTION --------------------------------------------------------


class TestLLMContradiction:
    def test_llm_says_satisfied_but_observed_exceeds_limit(self) -> None:
        v = SymbolicVerifier()
        # LLM claims satisfied=True, but 150 > 100 -> verifier disagrees.
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=150, satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value
        assert result.checked_assertions == 1
        assert any("satisfied=True" in d for d in result.divergences)

    def test_llm_says_unsatisfied_but_observed_is_within_limit(self) -> None:
        v = SymbolicVerifier()
        # LLM says satisfied=False, but 50 <= 100 -> actually satisfied.
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=50, satisfied=False)],
            llm_verdict=V3Verdict.FLAG,
        )
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value

    def test_one_contradiction_among_many_assertions(self) -> None:
        v = SymbolicVerifier()
        assertions = [
            _assertion(
                predicate="must_not_exceed",
                metric="a",
                value=100,
                observed=50,
                satisfied=True,
                obligation_id="ob.a",
            ),
            _assertion(
                predicate="must_not_exceed",
                metric="b",
                value=10,
                observed=20,
                satisfied=True,  # WRONG — verifier will disagree
                obligation_id="ob.b",
            ),
        ]
        result = v.verify(assertions, llm_verdict=V3Verdict.CLEAR)
        assert result.status == VerifierStatus.LLM_CONTRADICTION.value
        assert any("ob.b" in d for d in result.divergences)


# ---- NEURO_SYMBOLIC_DIVERGENCE ------------------------------------------------


class TestNeuroSymbolicDivergence:
    def test_all_satisfied_but_llm_emitted_flag(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=50, satisfied=True)],
            llm_verdict=V3Verdict.FLAG,
        )
        assert result.status == VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE.value
        assert any("not consistent" in d for d in result.divergences)

    def test_any_unsatisfied_but_llm_emitted_clear(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [_assertion(predicate="must_not_exceed", value=100, observed=200, satisfied=False)],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE.value


# ---- UNVERIFIABLE -------------------------------------------------------------


class TestUnverifiable:
    def test_unknown_predicate_is_unverifiable(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [
                _assertion(
                    predicate="requires_human_judgment",
                    value=None,
                    observed=None,
                    satisfied=True,
                )
            ],
            llm_verdict=V3Verdict.DISCRETIONARY,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value
        assert any("not mechanically verifiable" in d for d in result.divergences)

    def test_empty_assertions_is_unverifiable(self) -> None:
        v = SymbolicVerifier()
        result = v.verify([], llm_verdict=V3Verdict.CLEAR)
        assert result.status == VerifierStatus.UNVERIFIABLE.value
        assert result.checked_assertions == 0

    def test_non_numeric_operands_yields_unverifiable(self) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [
                _assertion(
                    predicate="must_not_exceed",
                    value="one hundred",
                    observed=50,
                    satisfied=True,
                )
            ],
            llm_verdict=V3Verdict.CLEAR,
        )
        assert result.status == VerifierStatus.UNVERIFIABLE.value


# ---- Predicate coverage -------------------------------------------------------


class TestPredicates:
    @pytest.mark.parametrize(
        ("predicate", "value", "observed", "expected"),
        [
            ("must_not_exceed", 100, 100, True),
            ("must_not_exceed", 100, 101, False),
            ("must_be_at_least", 5, 10, True),
            ("must_be_at_least", 5, 4, False),
            ("must_be_within", [6.0, 8.5], 7.2, True),
            ("must_be_within", [6.0, 8.5], 9.0, False),
            ("must_equal", "ok", "ok", True),
            ("must_equal", "ok", "nope", False),
            ("must_not_equal", "ok", "nope", True),
            ("must_not_equal", "ok", "ok", False),
        ],
    )
    def test_mechanical_check_matches_expectation(
        self, predicate: str, value: Any, observed: Any, expected: bool
    ) -> None:
        v = SymbolicVerifier()
        result = v.verify(
            [_assertion(predicate=predicate, value=value, observed=observed, satisfied=expected)],
            llm_verdict=V3Verdict.CLEAR if expected else V3Verdict.FLAG,
        )
        assert result.status == VerifierStatus.AGREED.value
