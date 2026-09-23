"""Freshness gate (``requires_recent_within_seconds``) on the v3 path.

Spec §4.1: an obligation with a temporal freshness predicate that maps to
the measurement, but whose freshness window has no telemetry for the
subject, yields ``NULL_STALE``. v2's ``symbolic_evaluator`` enforced this
(conformance ``provenance/test_null_stale_routing.py``); these tests pin
the same gate on ``V3Evaluator.aevaluate_with_transcript``, including the
fail-safe when freshness cannot be established (never CLEAR).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from ski_model.v3.evaluator import FakeLLM, V3Evaluator

_AS_OF = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_KG_HASH = "sha256:" + "0" * 64


def _snapshot(**extra: Any) -> Dict[str, Any]:
    ob: Dict[str, Any] = {
        "id": "energy.so2.cap",
        "metric": "so2_ppm",
        "predicate": "must_not_exceed",
        "value": 100,
    }
    ob.update(extra)
    return {"version": "v1", "obligations": [ob], "definitions": []}


GATED = _snapshot(requires_recent_within_seconds=60)


class _ListBuffer:
    """Protocol-minimal buffer: only ``window_query``, list-of-samples shape."""

    def __init__(self, samples: List[datetime]) -> None:
        self._samples = samples
        self.calls: List[Dict[str, Any]] = []

    async def window_query(
        self, *, subject: str, as_of: datetime, window_seconds: int, metric_path: Optional[str] = None
    ) -> Any:
        self.calls.append({"subject": subject, "as_of": as_of, "window_seconds": window_seconds})
        start = as_of - timedelta(seconds=window_seconds)
        return [(ts, 1.0) for ts in self._samples if start < ts <= as_of]


@dataclass
class _WindowResult:
    count: int


class _CountBuffer:
    """Production-shaped ``window_query`` result (``WindowQueryResult.count``)."""

    def __init__(self, count: int) -> None:
        self._count = count

    async def window_query(self, **_: Any) -> Any:
        return _WindowResult(count=self._count)


class _FreshSampleBuffer:
    """Exposes ``has_fresh_sample`` like ``telemetry_buffer.TelemetryBuffer``."""

    def __init__(self, fresh: bool) -> None:
        self._fresh = fresh
        self.window_query_called = False

    async def window_query(self, **_: Any) -> Any:
        self.window_query_called = True
        return []

    async def has_fresh_sample(self, *, subject: str, as_of: datetime, within_seconds: int) -> bool:
        return self._fresh


class _BrokenBuffer:
    async def window_query(self, **_: Any) -> Any:
        raise RuntimeError("db down")


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


async def _evaluate(
    *,
    buffer: Any,
    snapshot: Dict[str, Any] = GATED,
    measurement: Optional[Dict[str, Any]] = None,
    subject: Optional[str] = "plant-1",
    as_of: Optional[datetime] = _AS_OF,
    llm: Any = None,
    risk_tier: str = "standard",
) -> Any:
    ev = V3Evaluator(llm=llm or FakeLLM(), kg_version_hash=_KG_HASH)
    return await ev.aevaluate(
        measurement=measurement if measurement is not None else {"so2_ppm": 85},
        kg_snapshot=snapshot,
        subject=subject,
        as_of=as_of,
        buffer=buffer,
        risk_tier=risk_tier,
    )


def _verdict(envelope: Any) -> str:
    return getattr(envelope.verdict, "value", str(envelope.verdict))


def _freshness_notes(envelope: Any) -> List[str]:
    return [n for n in envelope.notes if n.startswith("taxonomy_guard: freshness gate")]


# ---- NULL_STALE -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_sample_in_window_is_null_stale() -> None:
    """The LLM says CLEAR (85 <= 100) but the subject is silent: NULL_STALE."""
    buf = _ListBuffer([_AS_OF - timedelta(seconds=600)])
    envelope = await _evaluate(buffer=buf)
    assert _verdict(envelope) == "NULL_STALE"
    (note,) = _freshness_notes(envelope)
    assert "energy.so2.cap" in note and "CLEAR remapped to NULL_STALE" in note
    assert buf.calls == [{"subject": "plant-1", "as_of": _AS_OF, "window_seconds": 60}]


@pytest.mark.asyncio
async def test_null_stale_overrides_flag() -> None:
    """v2 parity: the gate precedes predicate evaluation, so a breach on stale data is NULL_STALE."""
    envelope = await _evaluate(buffer=_ListBuffer([]), measurement={"so2_ppm": 150})
    assert _verdict(envelope) == "NULL_STALE"


@pytest.mark.asyncio
async def test_null_stale_keeps_verifier_audit_and_skips_risk_policy() -> None:
    """The verifier still records the LLM's assertions; tier-1 does not relabel NULL_STALE."""
    envelope = await _evaluate(buffer=_ListBuffer([]), risk_tier="tier-1")
    assert _verdict(envelope) == "NULL_STALE"
    assert envelope.verifier_result.status == "AGREED"
    assert envelope.verifier_result.checked_assertions == 1
    assert envelope.human_attestation is None


@pytest.mark.asyncio
async def test_production_shaped_window_result_count_zero_is_null_stale() -> None:
    envelope = await _evaluate(buffer=_CountBuffer(0))
    assert _verdict(envelope) == "NULL_STALE"


@pytest.mark.asyncio
async def test_has_fresh_sample_preferred_when_buffer_exposes_it() -> None:
    buf = _FreshSampleBuffer(fresh=False)
    envelope = await _evaluate(buffer=buf)
    assert _verdict(envelope) == "NULL_STALE"
    assert buf.window_query_called is False


@pytest.mark.asyncio
async def test_null_stale_applies_even_when_llm_output_is_rejected() -> None:
    """Early-exit paths (here: hallucinated citation) are gated too."""
    llm = _ScriptedLLM(
        {
            "verdict": "CLEAR",
            "reasoning": "fine",
            "kg_citations": [{"node_id": "made.up", "version": "v1", "role": "obligation"}],
            "formalizable_assertions": [],
        }
    )
    envelope = await _evaluate(buffer=_ListBuffer([]), llm=llm)
    assert _verdict(envelope) == "NULL_STALE"
    assert envelope.verifier_result.status == "UNVERIFIABLE"
    assert any("Invalid citation: made.up" in d for d in envelope.verifier_result.divergences)


@pytest.mark.asyncio
async def test_stale_wins_over_undecidable_across_obligations() -> None:
    snapshot = {
        "version": "v1",
        "obligations": [
            {
                "id": "a.bad_window",
                "metric": "so2_ppm",
                "predicate": "must_not_exceed",
                "value": 100,
                "requires_recent_within_seconds": "soon",
            },
            {
                "id": "b.stale",
                "metric": "so2_ppm",
                "predicate": "must_not_exceed",
                "value": 100,
                "requires_recent_within_seconds": 60,
            },
        ],
        "definitions": [],
    }
    envelope = await _evaluate(buffer=_ListBuffer([]), snapshot=snapshot)
    assert _verdict(envelope) == "NULL_STALE"
    assert "b.stale" in _freshness_notes(envelope)[0]


# ---- Fresh / not gated ----------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_sample_passes_through() -> None:
    envelope = await _evaluate(buffer=_ListBuffer([_AS_OF - timedelta(seconds=5)]))
    assert _verdict(envelope) == "CLEAR"
    assert _freshness_notes(envelope) == []


@pytest.mark.asyncio
async def test_fresh_sample_preserves_flag() -> None:
    envelope = await _evaluate(buffer=_CountBuffer(3), measurement={"so2_ppm": 150})
    assert _verdict(envelope) == "FLAG"


@pytest.mark.asyncio
async def test_unmapped_gated_obligation_is_not_checked() -> None:
    """The gate only applies to obligations whose metric is in the measurement."""
    buf = _ListBuffer([])
    envelope = await _evaluate(buffer=buf, measurement={"helium_ppm": 5})
    assert _verdict(envelope) == "NULL_UNMAPPED"
    assert buf.calls == []
    assert _freshness_notes(envelope) == []


@pytest.mark.asyncio
async def test_ungated_obligation_does_not_need_a_buffer() -> None:
    envelope = await _evaluate(buffer=None, snapshot=_snapshot())
    assert _verdict(envelope) == "CLEAR"
    assert _freshness_notes(envelope) == []


# ---- Fail safe: freshness cannot be established ---------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, missing",
    [
        ({"buffer": None}, "buffer"),
        ({"buffer": _ListBuffer([_AS_OF]), "subject": None}, "subject"),
        ({"buffer": _ListBuffer([_AS_OF]), "as_of": None}, "as_of"),
    ],
)
async def test_missing_context_is_discretionary_never_clear(kwargs: Dict[str, Any], missing: str) -> None:
    envelope = await _evaluate(**kwargs)
    assert _verdict(envelope) == "DISCRETIONARY"
    assert envelope.human_attestation == {"required": True, "fulfilled": False}
    (note,) = _freshness_notes(envelope)
    assert f"no {missing} supplied" in note and "never CLEAR" in note


@pytest.mark.asyncio
async def test_buffer_error_is_discretionary() -> None:
    envelope = await _evaluate(buffer=_BrokenBuffer())
    assert _verdict(envelope) == "DISCRETIONARY"
    assert "db down" in _freshness_notes(envelope)[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [0, -5, True, "60", 1.5])
async def test_malformed_window_is_discretionary(window: Any) -> None:
    envelope = await _evaluate(
        buffer=_ListBuffer([_AS_OF]),
        snapshot=_snapshot(requires_recent_within_seconds=window),
    )
    assert _verdict(envelope) == "DISCRETIONARY"
    assert "invalid requires_recent_within_seconds" in _freshness_notes(envelope)[0]


@pytest.mark.asyncio
async def test_unrecognised_window_result_is_discretionary() -> None:
    class _Weird:
        async def window_query(self, **_: Any) -> Any:
            return object()

    envelope = await _evaluate(buffer=_Weird())
    assert _verdict(envelope) == "DISCRETIONARY"
