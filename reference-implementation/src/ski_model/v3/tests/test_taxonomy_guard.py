"""No unverified CLEAR, and assertions grounded in the cited obligation.

Regression tests for eval run 5 (2026-06-12):

* ``unmapped-helium`` / ``unmapped-benzene-sunset-ok``: the model
  reasoned "nothing maps" and emitted CLEAR anyway — zero citations,
  zero assertions — and the envelope shipped as CLEAR. A coverage gap
  masked as compliance.
* Analysis of the same run showed nothing pinned an assertion's
  ``metric``/``value`` to the obligation it cites: a fabricated cap
  with internally consistent arithmetic would verify.

And for the silent-sensor gap: ``{"so2_ppm": null}`` evaluated CLEAR
with verifier status UNVERIFIABLE, which tier-2 accepted with a note —
a silent CLEAR on a silent sensor. It must be NULL_STALE.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List

import pytest

from ski_model.v3.envelope import FormalizableAssertion, V3Verdict
from ski_model.v3.evaluator import FakeLLM, V3Evaluator
from ski_model.v3.verifier import SymbolicVerifier

SNAPSHOT: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}
    ],
    "definitions": [],
}


class _ScriptedLLM:
    name = "scripted-llm"
    model_weight_hash = "sha256:" + "a" * 64
    prompt_template_id = "test"
    prompt_template_hash = "sha256:" + "b" * 64
    structured_grammar_hash = "sha256:" + "c" * 64

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw

    async def evaluate(self, **_kw: Any) -> Dict[str, Any]:
        return self._raw


async def _evaluate(raw: Dict[str, Any], measurement: Dict[str, Any]) -> Any:
    ev = V3Evaluator(llm=_ScriptedLLM(raw), kg_version_hash="sha256:" + "0" * 64)
    return await ev.aevaluate(measurement=measurement, kg_snapshot=SNAPSHOT)


def _verdict(envelope: Any) -> str:
    return getattr(envelope.verdict, "value", str(envelope.verdict))


@pytest.mark.asyncio
async def test_run5_unmapped_clear_remaps_to_null_unmapped() -> None:
    """The exact run-5 shape: CLEAR, no citations, no assertions."""
    envelope = await _evaluate(
        {
            "verdict": "CLEAR",
            "reasoning": "The measurement does not contain any metrics mapped to obligations.",
            "kg_citations": [],
            "formalizable_assertions": [],
        },
        measurement={"helium_ppm": 5},
    )
    assert _verdict(envelope) == "NULL_UNMAPPED", "a coverage gap must never read as compliance"
    assert any("taxonomy_guard" in n for n in envelope.notes)


@pytest.mark.asyncio
async def test_clear_with_citations_but_no_assertions_goes_to_human() -> None:
    envelope = await _evaluate(
        {
            "verdict": "CLEAR",
            "reasoning": "Looks fine.",
            "kg_citations": [{"node_id": "energy.so2.cap", "version": "v1", "role": "obligation"}],
            "formalizable_assertions": [],
        },
        measurement={"so2_ppm": 50},
    )
    assert _verdict(envelope) == "DISCRETIONARY"
    assert any("taxonomy_guard" in n for n in envelope.notes)


@pytest.mark.asyncio
async def test_verified_clear_is_untouched() -> None:
    envelope = await _evaluate(
        {
            "verdict": "CLEAR",
            "reasoning": "50 <= 100.",
            "kg_citations": [{"node_id": "energy.so2.cap", "version": "v1", "role": "obligation"}],
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 100,
                    "observed": 50,
                    "satisfied": True,
                    "obligation_id": "energy.so2.cap",
                }
            ],
        },
        measurement={"so2_ppm": 50},
    )
    assert _verdict(envelope) == "CLEAR"
    assert envelope.notes == []


@pytest.mark.asyncio
async def test_fabricated_cap_is_a_contradiction() -> None:
    """Model claims the cap is 999; the KG says 100."""
    envelope = await _evaluate(
        {
            "verdict": "CLEAR",
            "reasoning": "142 <= 999.",
            "kg_citations": [{"node_id": "energy.so2.cap", "version": "v1", "role": "obligation"}],
            "formalizable_assertions": [
                {
                    "predicate": "must_not_exceed",
                    "metric": "so2_ppm",
                    "value": 999,
                    "observed": 142,
                    "satisfied": True,
                    "obligation_id": "energy.so2.cap",
                }
            ],
        },
        measurement={"so2_ppm": 142},
    )
    assert _verdict(envelope) == "DISCRETIONARY", "a fabricated cap must never verify"
    assert any("fabricated obligation value" in d for d in envelope.verifier_result.divergences)


# ---- Missing telemetry: a silent sensor is never CLEAR ---------------------

STALE_SNAPSHOT: Dict[str, Any] = {
    "version": "v1",
    "obligations": [
        {"id": "energy.so2.cap", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100},
        {"id": "energy.ph.range", "metric": "ph", "predicate": "must_be_within", "value": [6.0, 8.5]},
    ],
    "definitions": [],
}


def _so2_clear(observed: Any, satisfied: bool = True) -> Dict[str, Any]:
    return {
        "verdict": "CLEAR",
        "reasoning": "Within limit.",
        "kg_citations": [{"node_id": "energy.so2.cap", "version": "v1", "role": "obligation"}],
        "formalizable_assertions": [
            {
                "predicate": "must_not_exceed",
                "metric": "so2_ppm",
                "value": 100,
                "observed": observed,
                "satisfied": satisfied,
                "obligation_id": "energy.so2.cap",
            }
        ],
    }


async def _evaluate_stale(raw: Dict[str, Any], measurement: Dict[str, Any], **kw: Any) -> Any:
    ev = V3Evaluator(llm=_ScriptedLLM(raw), kg_version_hash="sha256:" + "0" * 64)
    return await ev.aevaluate(measurement=measurement, kg_snapshot=STALE_SNAPSHOT, **kw)


def _stale_note(envelope: Any) -> bool:
    return any("taxonomy_guard" in n and "NULL_STALE" in n for n in envelope.notes)


@pytest.mark.asyncio
async def test_clear_on_null_reading_remaps_to_null_stale() -> None:
    """The reported shape: {"so2_ppm": null} came back CLEAR / UNVERIFIABLE."""
    envelope = await _evaluate_stale(_so2_clear(None), {"so2_ppm": None})
    assert _verdict(envelope) == "NULL_STALE", "a silent sensor must never read as compliance"
    assert _stale_note(envelope)
    assert str(envelope.verifier_result.status) == "UNVERIFIABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["tier-1", "standard", "tier-3"])
async def test_null_reading_never_clears_at_any_tier(tier: str) -> None:
    envelope = await _evaluate_stale(_so2_clear(None), {"so2_ppm": None}, risk_tier=tier)
    assert _verdict(envelope) != "CLEAR"


@pytest.mark.asyncio
@pytest.mark.parametrize("reading", ["n/a", "", True])
async def test_non_numeric_reading_for_numeric_predicate_is_stale(reading: Any) -> None:
    envelope = await _evaluate_stale(_so2_clear(reading), {"so2_ppm": reading})
    assert _verdict(envelope) == "NULL_STALE"
    assert _stale_note(envelope)


@pytest.mark.asyncio
async def test_nan_reading_never_clears() -> None:
    """NaN is remapped too; observation grounding then sees nan != nan as a
    mismatch, so tier-2 routes it to a human rather than NULL_STALE. Either
    way it is never CLEAR."""
    nan = float("nan")
    envelope = await _evaluate_stale(_so2_clear(nan), {"so2_ppm": nan})
    assert _verdict(envelope) != "CLEAR"
    assert _stale_note(envelope)


@pytest.mark.asyncio
async def test_fabricated_reading_for_silent_sensor_never_clears() -> None:
    """The model invents 85 for a null reading. The guard checks the
    measurement itself, so the CLEAR is remapped; grounding then records
    the fabrication and tier-2 routes it to a human."""
    envelope = await _evaluate_stale(_so2_clear(85), {"so2_ppm": None})
    assert _verdict(envelope) == "DISCRETIONARY"
    assert _stale_note(envelope)
    assert str(envelope.verifier_result.status) == "LLM_CONTRADICTION"


@pytest.mark.asyncio
async def test_clear_that_skips_a_silent_mapped_metric_is_stale() -> None:
    """A verified assertion on so2 does not clear a record whose pH sensor is silent."""
    envelope = await _evaluate_stale(_so2_clear(50), {"so2_ppm": 50, "ph": None})
    assert _verdict(envelope) == "NULL_STALE"
    assert any("energy.ph.range" in n for n in envelope.notes)


@pytest.mark.asyncio
async def test_clear_with_no_assertions_on_silent_mapped_metric_is_stale_not_unmapped() -> None:
    envelope = await _evaluate_stale(
        {"verdict": "CLEAR", "reasoning": "No data.", "kg_citations": [], "formalizable_assertions": []},
        {"so2_ppm": None},
    )
    assert _verdict(envelope) == "NULL_STALE"


@pytest.mark.asyncio
async def test_null_on_unmapped_metric_is_still_unmapped() -> None:
    envelope = await _evaluate_stale(
        {"verdict": "CLEAR", "reasoning": "Nothing maps.", "kg_citations": [], "formalizable_assertions": []},
        {"helium_ppm": None},
    )
    assert _verdict(envelope) == "NULL_UNMAPPED"


@pytest.mark.asyncio
async def test_healthy_reading_clear_is_untouched_by_stale_guard() -> None:
    envelope = await _evaluate_stale(_so2_clear(50), {"so2_ppm": 50})
    assert _verdict(envelope) == "CLEAR"
    assert envelope.notes == []


@pytest.mark.asyncio
async def test_fakellm_emits_null_stale_for_silent_sensor() -> None:
    """CI's deterministic backend exercises the stale path end-to-end."""
    ev = V3Evaluator(llm=FakeLLM(), kg_version_hash="sha256:" + "0" * 64)
    measurements: List[Dict[str, Any]] = [{"so2_ppm": None}, {"ph": None}, {"so2_ppm": 50, "ph": None}]
    for measurement in measurements:
        envelope = await ev.aevaluate(measurement=measurement, kg_snapshot=STALE_SNAPSHOT)
        assert _verdict(envelope) == "NULL_STALE", measurement
        assert not _stale_note(envelope), "FakeLLM gets it right; the guard should not fire"


def _assertion(**overrides: object) -> FormalizableAssertion:
    base: dict[str, object] = {
        "predicate": "must_not_exceed",
        "metric": "so2_ppm",
        "value": 100,
        "observed": 50,
        "satisfied": True,
        "obligation_id": "energy.so2.cap",
    }
    base.update(overrides)
    return FormalizableAssertion.model_validate(base)


class TestObligationGroundingUnit:
    OBS: ClassVar[Dict[str, Dict[str, Any]]] = {
        "energy.so2.cap": {"id": "energy.so2.cap", "metric": "so2_ppm", "value": 100}
    }

    def _verify(self, assertion: FormalizableAssertion) -> Any:
        return SymbolicVerifier().verify(
            [assertion],
            llm_verdict=V3Verdict.CLEAR,
            measurement={"so2_ppm": 50},
            obligations=self.OBS,
        )

    def test_grounded_assertion_agreed(self) -> None:
        assert str(self._verify(_assertion()).status) == "AGREED"

    def test_wrong_metric_for_obligation(self) -> None:
        r = self._verify(_assertion(metric="so2", observed=None))
        assert str(r.status) == "LLM_CONTRADICTION"
        assert "obligation mismatch" in r.divergences[0]

    def test_unknown_obligation_id(self) -> None:
        r = self._verify(_assertion(obligation_id="energy.invented"))
        assert str(r.status) == "LLM_CONTRADICTION"
        assert "fabricated obligation reference" in r.divergences[0]

    def test_non_numeric_non_list_obligation_value_mismatch(self) -> None:
        """String-valued obligations (e.g. a required status/category) hit
        the plain equality branch, not the numeric or range coercion."""
        obs = {"energy.status.cap": {"id": "energy.status.cap", "metric": "status", "value": "compliant"}}
        a = _assertion(
            predicate="must_equal",
            metric="status",
            value="exempt",  # fabricated — the obligation actually says "compliant"
            observed="exempt",
            obligation_id="energy.status.cap",
        )
        r = SymbolicVerifier().verify(
            [a], llm_verdict=V3Verdict.CLEAR, measurement={"status": "exempt"}, obligations=obs
        )
        assert str(r.status) == "LLM_CONTRADICTION"
        assert "fabricated obligation value" in r.divergences[0]

    def test_range_value_tolerates_int_float(self) -> None:
        obs = {"ph.range": {"id": "ph.range", "metric": "ph", "value": [6, 8.5]}}
        a = _assertion(
            predicate="must_be_within",
            metric="ph",
            value=[6.0, 8.5],
            observed=7.0,
            obligation_id="ph.range",
        )
        r = SymbolicVerifier().verify(
            [a], llm_verdict=V3Verdict.CLEAR, measurement={"ph": 7.0}, obligations=obs
        )
        assert str(r.status) == "AGREED"
