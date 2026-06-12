"""Observation grounding — the verifier rejects fabricated observations.

Regression tests for the false FLAG eval run 4 found (2026-06-12): the
measurement contained a deliberately unmapped key (``so2``), the model
fuzzy-matched it onto the KG metric ``so2_ppm`` and asserted
``observed=142`` — a reading that was never made. The arithmetic was
internally consistent (142 > 100), so the arithmetic-only verifier
AGREED and a false FLAG shipped. Grounding closes the gap: ``observed``
must match what the measurement actually records.
"""

from __future__ import annotations

import pytest

from ski_model.v3.envelope import FormalizableAssertion, V3Verdict
from ski_model.v3.verifier import SymbolicVerifier


def _assertion(**overrides: object) -> FormalizableAssertion:
    base: dict[str, object] = {
        "predicate": "must_not_exceed",
        "metric": "so2_ppm",
        "value": 100,
        "observed": 142,
        "satisfied": False,
        "obligation_id": "energy.so2.cap",
    }
    base.update(overrides)
    return FormalizableAssertion.model_validate(base)


class TestGroundingViolations:
    def test_run4_false_flag_metric_not_in_measurement(self) -> None:
        """The exact run-4 case: measurement key 'so2', asserted metric 'so2_ppm'."""
        result = SymbolicVerifier().verify(
            [_assertion()],
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2": 142},
        )
        assert str(result.status) == "LLM_CONTRADICTION"
        assert "fabricated observation" in result.divergences[0]

    def test_observed_differs_from_measurement(self) -> None:
        result = SymbolicVerifier().verify(
            [_assertion(observed=99, satisfied=True)],
            llm_verdict=V3Verdict.CLEAR,
            measurement={"so2_ppm": 142},
        )
        assert str(result.status) == "LLM_CONTRADICTION"
        assert "fabricated observation" in result.divergences[0]

    def test_grounded_assertion_still_agreed(self) -> None:
        result = SymbolicVerifier().verify(
            [_assertion()],
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2_ppm": 142},
        )
        assert str(result.status) == "AGREED"

    def test_int_float_equivalence_is_not_a_violation(self) -> None:
        result = SymbolicVerifier().verify(
            [_assertion(observed=142.0)],
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2_ppm": 142},
        )
        assert str(result.status) == "AGREED"

    def test_no_measurement_keeps_arithmetic_only_behaviour(self) -> None:
        """Backwards compatible: callers that pass no measurement get the old contract."""
        result = SymbolicVerifier().verify([_assertion()], llm_verdict=V3Verdict.FLAG)
        assert str(result.status) == "AGREED"

    def test_none_observed_is_left_to_arithmetic_path(self) -> None:
        result = SymbolicVerifier().verify(
            [_assertion(observed=None)],
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2_ppm": 142},
        )
        # Not a grounding violation; the arithmetic check decides what
        # a missing observation means (UNVERIFIABLE).
        assert str(result.status) == "UNVERIFIABLE"


class TestGroundingAsync:
    @pytest.mark.asyncio
    async def test_averify_grounds_observations(self) -> None:
        result = await SymbolicVerifier().averify(
            [_assertion()],
            llm_verdict=V3Verdict.FLAG,
            measurement={"so2": 142},
        )
        assert str(result.status) == "LLM_CONTRADICTION"

    @pytest.mark.asyncio
    async def test_stateful_assertions_exempt_from_current_reading_grounding(self) -> None:
        a = _assertion(
            predicate="must_average_within",
            value=[0, 100],
            observed=87.5,
            satisfied=True,
            window_seconds=3600,
        )
        result = await SymbolicVerifier().averify(
            [a],
            llm_verdict=V3Verdict.CLEAR,
            measurement={"so2_ppm": 142},
        )
        # Aggregate observation != current reading is NOT a fabrication;
        # without a buffer the stateful check is UNVERIFIABLE.
        assert str(result.status) == "UNVERIFIABLE"


@pytest.mark.asyncio
async def test_end_to_end_fabricated_observation_routes_to_discretionary() -> None:
    """Through the evaluator: the run-4 false FLAG now degrades safely."""
    from ski_model.v3.evaluator import V3Evaluator

    class _FabricatingLLM:
        name = "fabricating-llm"
        model_weight_hash = "sha256:" + "a" * 64
        prompt_template_id = "test"
        prompt_template_hash = "sha256:" + "b" * 64
        structured_grammar_hash = "sha256:" + "c" * 64

        async def evaluate(self, **_kw: object) -> dict[str, object]:
            return {
                "verdict": "FLAG",
                "reasoning": "SO2 emissions exceed the allowed limit.",
                "kg_citations": [{"node_id": "energy.so2.cap", "version": "v1", "role": "obligation"}],
                "formalizable_assertions": [
                    {
                        "predicate": "must_not_exceed",
                        "metric": "so2_ppm",
                        "value": 100,
                        "observed": 142,
                        "satisfied": False,
                        "obligation_id": "energy.so2.cap",
                    }
                ],
            }

    snapshot = {
        "version": "v1",
        "obligations": [
            {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
        ],
        "definitions": [],
    }
    envelope = await V3Evaluator(llm=_FabricatingLLM(), kg_version_hash="sha256:" + "0" * 64).aevaluate(
        measurement={"so2": 142}, kg_snapshot=snapshot
    )
    verdict = getattr(envelope.verdict, "value", str(envelope.verdict))
    status = getattr(envelope.verifier_result.status, "value", str(envelope.verifier_result.status))
    assert verdict == "DISCRETIONARY", "false FLAG must not ship"
    assert status == "LLM_CONTRADICTION"
