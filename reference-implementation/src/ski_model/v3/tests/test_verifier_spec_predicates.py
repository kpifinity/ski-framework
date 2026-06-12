"""Spec §3.3 predicate handlers added for validator-verifier parity."""

from __future__ import annotations

from ski_model.v3.envelope import FormalizableAssertion, V3Verdict
from ski_model.v3.verifier import SymbolicVerifier


def _result(predicate: str, value: object, observed: object, satisfied: bool, verdict: V3Verdict):
    a = FormalizableAssertion.model_validate(
        {
            "predicate": predicate,
            "metric": "m",
            "value": value,
            "observed": observed,
            "satisfied": satisfied,
            "obligation_id": "ob.x",
        }
    )
    return SymbolicVerifier().verify([a], llm_verdict=verdict)


def test_must_be_below_is_strict() -> None:
    assert str(_result("must_be_below", 100, 99, True, V3Verdict.CLEAR).status) == "AGREED"
    # boundary: 100 < 100 is False — claiming satisfied is a contradiction
    assert str(_result("must_be_below", 100, 100, True, V3Verdict.CLEAR).status) == "LLM_CONTRADICTION"


def test_must_be_above_is_strict() -> None:
    assert str(_result("must_be_above", 10, 11, True, V3Verdict.CLEAR).status) == "AGREED"
    assert str(_result("must_be_above", 10, 10, True, V3Verdict.CLEAR).status) == "LLM_CONTRADICTION"


def test_must_be_one_of_membership() -> None:
    assert str(_result("must_be_one_of", ["a", "b"], "a", True, V3Verdict.CLEAR).status) == "AGREED"
    assert str(_result("must_be_one_of", ["a", "b"], "c", False, V3Verdict.FLAG).status) == "AGREED"
    assert (
        str(_result("must_be_one_of", ["a", "b"], "c", True, V3Verdict.CLEAR).status) == "LLM_CONTRADICTION"
    )


def test_must_not_be_one_of_membership() -> None:
    assert str(_result("must_not_be_one_of", ["x"], "y", True, V3Verdict.CLEAR).status) == "AGREED"
    assert str(_result("must_not_be_one_of", ["x"], "x", True, V3Verdict.CLEAR).status) == "LLM_CONTRADICTION"


def test_empty_set_is_unverifiable_not_guessed() -> None:
    assert str(_result("must_be_one_of", [], "a", True, V3Verdict.CLEAR).status) == "UNVERIFIABLE"
