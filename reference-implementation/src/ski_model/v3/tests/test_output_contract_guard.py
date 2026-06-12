"""Output-contract guard — a misbehaving model must never crash the evaluator.

Regression tests for the crash the first nightly real-model eval run
found (2026-06-12): qwen2.5:7b emitted ``"value": {"min": 6.0, "max": 8.5}``
and ``"observed": {"value": 7.2}`` — valid JSON, invalid envelope schema —
and ``aevaluate_with_transcript`` raised ``pydantic.ValidationError``
instead of degrading. In production that is a 500 on ``/api/evaluate``.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ski_model.v3.evaluator import (
    PROMPT_TEMPLATE,
    PROMPT_TEMPLATE_ID,
    RESPONSE_GRAMMAR,
    V3Evaluator,
)

SNAPSHOT: Dict[str, Any] = {
    "version": "test-1",
    "obligations": [
        {
            "id": "energy.ph.range",
            "metric": "ph",
            "predicate": "must_be_within",
            "value": [6.5, 8.5],
        }
    ],
    "definitions": [],
}


class _MisbehavingLLM:
    """Returns syntactically valid JSON that violates the envelope schema."""

    name = "misbehaving-llm"
    model_weight_hash = "sha256:" + "a" * 64
    prompt_template_id = PROMPT_TEMPLATE_ID
    prompt_template_hash = "sha256:" + "b" * 64
    structured_grammar_hash = "sha256:" + "c" * 64

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw

    async def evaluate(self, **_kwargs: Any) -> Dict[str, Any]:
        return self._raw


def _nightly_crash_payload() -> Dict[str, Any]:
    """The exact shape qwen2.5:7b produced in the 2026-06-12 nightly run."""
    return {
        "verdict": "CLEAR",
        "reasoning": "pH 7.2 is within the permitted range.",
        "kg_citations": [{"node_id": "energy.ph.range", "version": "test-1", "role": "obligation"}],
        "formalizable_assertions": [
            {
                "predicate": "must_be_within",
                "metric": "ph",
                "value": {"min": 6.0, "max": 8.5},
                "observed": {"value": 7.2},
                "satisfied": True,
                "obligation_id": "energy.ph.range",
            }
        ],
    }


@pytest.mark.asyncio
async def test_dict_shaped_assertion_degrades_to_discretionary() -> None:
    ev = V3Evaluator(llm=_MisbehavingLLM(_nightly_crash_payload()), kg_version_hash="sha256:" + "0" * 64)
    envelope = await ev.aevaluate(measurement={"ph": 7.2}, kg_snapshot=SNAPSHOT)
    assert str(envelope.verdict) == "DISCRETIONARY"
    assert envelope.formalizable_assertions == []
    assert str(envelope.verifier_result.status) == "UNVERIFIABLE"
    assert envelope.verifier_result.checked_assertions == 0
    assert "Output-contract violation" in envelope.reasoning


@pytest.mark.asyncio
async def test_missing_reasoning_degrades_not_crashes() -> None:
    raw = _nightly_crash_payload()
    del raw["reasoning"]
    raw["formalizable_assertions"] = []
    ev = V3Evaluator(llm=_MisbehavingLLM(raw), kg_version_hash="sha256:" + "0" * 64)
    envelope = await ev.aevaluate(measurement={"ph": 7.2}, kg_snapshot=SNAPSHOT)
    assert str(envelope.verdict) == "DISCRETIONARY"


@pytest.mark.asyncio
async def test_malformed_citation_shape_degrades_not_crashes() -> None:
    raw = _nightly_crash_payload()
    raw["formalizable_assertions"] = []
    raw["kg_citations"] = [{"node_id": "energy.ph.range", "version": {"v": 1}, "role": "obligation"}]
    ev = V3Evaluator(llm=_MisbehavingLLM(raw), kg_version_hash="sha256:" + "0" * 64)
    envelope = await ev.aevaluate(measurement={"ph": 7.2}, kg_snapshot=SNAPSHOT)
    assert str(envelope.verdict) == "DISCRETIONARY"


@pytest.mark.asyncio
async def test_well_formed_response_unaffected_by_guard() -> None:
    raw = _nightly_crash_payload()
    raw["formalizable_assertions"][0]["value"] = [6.5, 8.5]
    raw["formalizable_assertions"][0]["observed"] = 7.2
    ev = V3Evaluator(llm=_MisbehavingLLM(raw), kg_version_hash="sha256:" + "0" * 64)
    envelope = await ev.aevaluate(measurement={"ph": 7.2}, kg_snapshot=SNAPSHOT)
    assert str(envelope.verdict) == "CLEAR"
    assert str(envelope.verifier_result.status) == "AGREED"


def test_grammar_forbids_object_valued_assertion_fields() -> None:
    props = RESPONSE_GRAMMAR["properties"]["formalizable_assertions"]["items"]["properties"]
    assert "object" not in props["value"]["type"]
    assert "object" not in props["observed"]["type"]


def test_prompt_pins_scalar_assertion_shapes_and_id_bumped() -> None:
    assert PROMPT_TEMPLATE_ID == "ski.v3.evaluate.4"
    assert "BARE scalars" in PROMPT_TEMPLATE
    assert "[min, max]" in PROMPT_TEMPLATE
