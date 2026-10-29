"""Property test for the fail-closed invariant (finding C1, framework v3.2.0).

**If any mapped, formalizable obligation is mechanically breached, the verdict
is never CLEAR -- at any risk tier.**

Hypothesis draws random scoped KG slices (stateless and stateful predicates,
declared / undeclared / unknown tiers, optional units), random measurements
(including integers beyond the double range and unit-bearing readings), random
telemetry-buffer windows, and adversarial LLM outputs built from them: omitted
obligations, junk (out-of-enum) predicates, in-enum qualitative predicates,
flipped ``satisfied`` flags, substituted predicates, fabricated observations or
caps, a ``window_seconds`` on a stateless predicate (which skips observation
grounding), ``observed: null``, wrong obligation ids and bogus citations.

The oracle below is independent of the verifier: it re-implements each
predicate on the raw reading in a few lines and decides "breached" itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from hypothesis import HealthCheck, event, given, note, settings
from hypothesis import strategies as st
from tag_registry import RiskTierGovernor

from ski_model.v3 import FakeLLM, SymbolicVerifier, V3Evaluator, V3Verdict, VerifierStatus
from ski_model.v3.verifier import index_obligations

H = "sha256:" + "d" * 64
AS_OF = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
METRICS = ("m0", "m1", "m2")
UNITS = ("ppm", "mg/m3")
STATELESS = (
    "must_not_exceed",
    "must_be_at_least",
    "must_be_below",
    "must_be_above",
    "must_be_within",
    "must_be_one_of",
    "must_not_be_one_of",
    "must_equal",
    "must_not_equal",
)
STATEFUL = ("must_not_exceed_in_window", "must_average_within")
TIERS: Tuple[Optional[str], ...] = ("tier-1", "tier-2", "tier-3", None, "critical")
CLEAR = V3Verdict.CLEAR.value

# ---- Independent oracle -------------------------------------------------------


def _truth(predicate: str, reading: Any, value: Any) -> bool:
    """The predicate's truth on a finite numeric reading (test-side re-implementation)."""
    if predicate == "must_not_exceed":
        return bool(reading <= value)
    if predicate == "must_be_at_least":
        return bool(reading >= value)
    if predicate == "must_be_below":
        return bool(reading < value)
    if predicate == "must_be_above":
        return bool(reading > value)
    if predicate in ("must_be_within", "must_average_within"):
        return bool(value[0] <= reading <= value[1])
    if predicate == "must_be_one_of":
        return reading in value
    if predicate == "must_not_be_one_of":
        return reading not in value
    if predicate == "must_equal":
        return bool(reading == value)
    if predicate == "must_not_equal":
        return bool(reading != value)
    if predicate == "must_not_exceed_in_window":
        return bool(reading <= value)
    raise AssertionError(predicate)


def _split(raw: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(raw, dict):
        return raw["value"], raw["unit"]
    return raw, None


@dataclass
class Scenario:
    snapshot: Dict[str, Any]
    measurement: Dict[str, Any]
    windows: Dict[str, Tuple[float, float]]  # metric -> (avg, peak)
    raw: Dict[str, Any]


def oracle(s: Scenario) -> Tuple[List[str], List[str]]:
    """``(breached, unit_mismatched)`` obligation ids among the mapped, formalizable ones."""
    breached: List[str] = []
    mismatched: List[str] = []
    for ob in s.snapshot["obligations"]:
        if ob["metric"] not in s.measurement:
            continue  # not mapped
        reading, unit = _split(s.measurement[ob["metric"]])
        if unit is not None and ob.get("unit") is not None and unit != ob["unit"]:
            mismatched.append(ob["id"])
            continue
        if ob["predicate"] == "must_not_exceed_in_window":
            reading = s.windows[ob["metric"]][1]
        elif ob["predicate"] == "must_average_within":
            reading = s.windows[ob["metric"]][0]
        if not _truth(ob["predicate"], reading, ob["value"]):
            breached.append(ob["id"])
    return breached, mismatched


# ---- Strategies ------------------------------------------------------------------

_small = st.integers(-5, 5)
_number = st.one_of(
    _small,
    st.integers(-(10**6), 10**6),
    st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
    st.sampled_from([10**400, -(10**400)]),
)


def _value_for(predicate: str) -> st.SearchStrategy[Any]:
    if predicate in ("must_be_within", "must_average_within"):
        return st.tuples(_number, _number).map(lambda p: sorted(p))
    if predicate in ("must_be_one_of", "must_not_be_one_of"):
        return st.lists(_small, min_size=1, max_size=3)
    if predicate in ("must_equal", "must_not_equal"):
        return _small
    return _number


@st.composite
def _obligation(draw: st.DrawFn, index: int) -> Dict[str, Any]:
    predicate = draw(st.sampled_from(STATELESS + STATEFUL))
    ob: Dict[str, Any] = {
        "id": f"ob{index}",
        "metric": draw(st.sampled_from(METRICS)),
        "predicate": predicate,
        "value": draw(_value_for(predicate)),
    }
    if predicate in STATEFUL:
        ob["window_seconds"] = draw(st.sampled_from([60, 3600]))
    tier = draw(st.sampled_from([None, "tier-1", "tier-2", "tier-3", "low", "medium", "high", "critical", 7]))
    if tier is not None:
        ob["risk_tier"] = tier
    unit = draw(st.sampled_from([None, None, "ppm"]))
    if unit is not None:
        ob["unit"] = unit
    return ob


def _cite(*ids: str) -> List[Dict[str, str]]:
    return [{"node_id": i, "version": "v1", "role": "obligation"} for i in ids]


MODES = (
    "honest",
    "honest",
    "omit",
    "omit",
    "junk",
    "qualitative",
    "substitute",
    "fabricate_observed",
    "fabricate_value",
    "window_trick",
    "null_observed",
    "wrong_id",
)


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    n = draw(st.integers(1, 4))
    obligations = [draw(_obligation(i)) for i in range(n)]
    measurement: Dict[str, Any] = {}
    for metric in METRICS:
        if draw(st.integers(0, 3)) == 0:
            continue  # metric absent: obligations on it are not mapped
        reading: Any = draw(st.one_of(_small, _number))
        if draw(st.integers(0, 4)) == 0:
            reading = {"value": reading, "unit": draw(st.sampled_from(UNITS))}
        measurement[metric] = reading
    windows = {m: (draw(_number), draw(_number)) for m in METRICS}

    assertions: List[Dict[str, Any]] = []
    for ob in obligations:
        mode = draw(st.sampled_from(MODES))
        if mode == "omit":
            continue
        raw = measurement.get(ob["metric"], draw(_number))
        observed, _unit = _split(raw)
        a: Dict[str, Any] = {
            "predicate": ob["predicate"],
            "metric": ob["metric"],
            "value": ob["value"],
            "observed": observed,
            "satisfied": draw(st.booleans()),
            "obligation_id": ob["id"],
        }
        if ob["predicate"] in STATEFUL:
            a["window_seconds"] = draw(st.sampled_from([ob["window_seconds"], 1, 86400]))
        if mode == "junk":
            a["predicate"] = draw(st.sampled_from(["must_be_reasonable", "is_fine", "MUST_NOT_EXCEED"]))
        elif mode == "qualitative":
            a["predicate"] = draw(st.sampled_from(["discretionary", "should", "must"]))
            a["value"] = None
        elif mode == "substitute":
            a["predicate"] = draw(st.sampled_from([p for p in STATELESS if p != ob["predicate"]]))
        elif mode == "fabricate_observed":
            a["observed"] = draw(_number)
        elif mode == "fabricate_value":
            a["value"] = draw(_value_for(ob["predicate"]))
        elif mode == "window_trick":
            a["window_seconds"] = 60
            a["observed"] = draw(_number)
        elif mode == "null_observed":
            a["observed"] = None
        elif mode == "wrong_id":
            a["obligation_id"] = draw(st.sampled_from([o["id"] for o in obligations] + ["ghost"]))
        event(f"mode={mode}")
        assertions.append(a)

    cited = draw(st.lists(st.sampled_from([o["id"] for o in obligations]), unique=True))
    if draw(st.integers(0, 9)) == 0:
        cited.append("bogus.node")
    raw_output = {
        "verdict": draw(
            st.sampled_from(["CLEAR"] * 4 + ["NULL_UNMAPPED", "FLAG", "DISCRETIONARY", "NULL_STALE"])
        ),
        "reasoning": "adversarial",
        "kg_citations": _cite(*cited),
        "formalizable_assertions": assertions,
    }
    snapshot = {"version": "v1", "obligations": obligations, "definitions": []}
    return Scenario(snapshot=snapshot, measurement=measurement, windows=windows, raw=raw_output)


# ---- Harness ---------------------------------------------------------------------


class _ScriptedLLM(FakeLLM):
    def __init__(self, raw: Dict[str, Any]) -> None:
        super().__init__()
        self._raw = raw

    async def evaluate(
        self, *, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        return dict(self._raw)


@dataclass
class _Agg:
    avg_value: float
    max_value: float


class _WindowBuffer:
    def __init__(self, windows: Dict[str, Tuple[float, float]]) -> None:
        self._windows = windows

    async def window_query(self, *, metric_path: Optional[str] = None, **_: Any) -> Any:
        avg, peak = self._windows[str(metric_path)] if metric_path in self._windows else (0.0, 0.0)
        return _Agg(avg_value=avg, max_value=peak)


async def _evaluate_all_tiers(s: Scenario) -> List[Tuple[Optional[str], Any]]:
    out: List[Tuple[Optional[str], Any]] = []
    governed = RiskTierGovernor.tier_for_snapshot(s.snapshot)
    for tier in (*TIERS, governed):
        evaluator = V3Evaluator(llm=_ScriptedLLM(s.raw), kg_version_hash=H)
        envelope = await evaluator.aevaluate(
            measurement=s.measurement,
            kg_snapshot=s.snapshot,
            risk_tier=tier,
            subject="stack-1",
            as_of=AS_OF,
            buffer=_WindowBuffer(s.windows),
        )
        out.append((tier, envelope))
    return out


# Derandomized so CI is reproducible: the same 1000 examples on every run
# (a few seconds). Explore further locally with --hypothesis-seed=<n> after
# removing derandomize.
_SETTINGS = settings(
    max_examples=1000,
    derandomize=True,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@_SETTINGS
@given(scenarios())
def test_no_mechanical_breach_ever_yields_clear(s: Scenario) -> None:
    breached, mismatched = oracle(s)
    event(f"breached={bool(breached)}")
    note(f"breached={breached} unit_mismatch={mismatched}")
    for tier, envelope in asyncio.run(_evaluate_all_tiers(s)):
        verdict = str(getattr(envelope.verdict, "value", envelope.verdict))
        if breached or mismatched:
            assert verdict != CLEAR, (tier, breached, mismatched, envelope.verifier_result, envelope.notes)


@_SETTINGS
@given(scenarios())
def test_sync_and_async_verifier_agree_and_flag_every_breach(s: Scenario) -> None:
    """The verifier alone (no evaluator, no buffer): both paths give the same
    report, and a CLEAR / NULL_UNMAPPED verdict over a stateless breach is
    always LLM_CONTRADICTION."""
    from ski_model.v3 import FormalizableAssertion

    stateless = {
        **s.snapshot,
        "obligations": [ob for ob in s.snapshot["obligations"] if ob["predicate"] in STATELESS],
    }
    breached, _mismatched = oracle(Scenario(stateless, s.measurement, s.windows, s.raw))
    try:
        assertions = [
            FormalizableAssertion(**a)
            for a in s.raw["formalizable_assertions"]
            if a["predicate"] not in STATEFUL  # the sync path cannot evaluate these by design
        ]
    except Exception:  # an output-contract violation never reaches the verifier
        return
    index, _violations = index_obligations(stateless["obligations"], s.measurement)
    verdict = V3Verdict(s.raw["verdict"])
    verifier = SymbolicVerifier()
    sync = verifier.verify_report(
        assertions, llm_verdict=verdict, measurement=s.measurement, obligations=index
    )
    asyn = asyncio.run(
        verifier.averify_report(assertions, llm_verdict=verdict, measurement=s.measurement, obligations=index)
    )
    assert sync == asyn
    assert sorted(set(sync.breached_obligations)) == sorted(set(breached))
    if breached and verdict in (V3Verdict.CLEAR, V3Verdict.NULL_UNMAPPED):
        assert sync.result.status == VerifierStatus.LLM_CONTRADICTION.value
