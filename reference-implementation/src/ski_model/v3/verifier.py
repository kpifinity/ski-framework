"""Symbolic Verifier — mechanically cross-checks the LLM's formalizable assertions.

The verifier closes the neuro-symbolic loop per spec v3.0 §4.5. For each
:class:`FormalizableAssertion` the LLM emits, the verifier re-evaluates the
predicate **without** invoking the LLM, then compares its mechanical result
to the LLM's ``satisfied`` flag.

Outcomes (:class:`VerifierStatus`):

* ``AGREED`` — every assertion the verifier could check matches the LLM.
* ``LLM_CONTRADICTION`` — the LLM said ``satisfied`` (or ``not satisfied``)
  but the verifier disagrees. The mechanical truth wins.
* ``NEURO_SYMBOLIC_DIVERGENCE`` — the verifier's per-assertion view agrees
  with each ``satisfied`` flag in isolation, but the LLM's overall verdict
  doesn't match what those assertions imply (since v3.2.0 only: FLAG with
  every assertion satisfied; a CLEAR resting on a breach is a contradiction).
* ``UNVERIFIABLE`` — at least one assertion uses a predicate the verifier
  cannot mechanically evaluate (e.g. predicates that require qualified
  human judgment). The envelope is forwarded as-is for human attestation.

Precedence (framework v3.2.0, finding C1): ``LLM_CONTRADICTION`` wins over
``UNVERIFIABLE``, which wins over ``NEURO_SYMBOLIC_DIVERGENCE``. One
unverifiable assertion can no longer mask a mechanically established
breach. Sync and async paths share one aggregator (:class:`_Tally`).

Independent enumeration (spec §5.3 step 4): when given the scoped KG slice
and the measurement, the verifier also evaluates **every** obligation whose
metric is present in the measurement and whose predicate it can evaluate,
whether or not the LLM asserted it. The reading comes from the measurement,
never from the LLM. Divergences added by v3.2.0 are prefixed with their kind
(``"<KIND>: [<obligation id>] ..."``; plain strings, so the envelope schema
is unchanged):

* ``OMITTED_OBLIGATION`` — a mapped obligation the LLM did not assert and
  the verifier evaluates as breached: a contradiction.
* ``OMITTED_OBLIGATION_UNVERIFIABLE`` — not asserted and not evaluable
  (e.g. a stateful obligation with no telemetry buffer).
* ``UNFLAGGED_BREACH`` — the LLM verdict is CLEAR or NULL_UNMAPPED but the
  verifier evaluates a mapped obligation (or one of the LLM's own
  assertions) as breached, or the LLM's own assertion says unsatisfied:
  a contradiction.
* ``SCHEMA_VIOLATION`` — an assertion predicate outside the closed
  obligation-type enumeration (spec §3.3). Never lets a breach hide behind
  UNVERIFIABLE; the evaluator routes it to DISCRETIONARY at every tier.
* ``UNIT_MISMATCH`` — the measurement carries a unit (``{"value": x,
  "unit": u}``) other than the one the obligation declares. No conversion
  is attempted; the evaluator routes it to DISCRETIONARY at every tier.

An obligation not asserted by the LLM but evaluated as satisfied counts as
checked and is reported in :attr:`VerificationReport.notes`. The obligations
the verifier itself evaluates as breached are reported in
:attr:`VerificationReport.breached_obligations`; the evaluator never lets a
verdict that rests on one ship as CLEAR.

Bool, NaN and ±Infinity are never numeric readings: every handler treats
them as UNVERIFIABLE rather than letting ``True <= 100`` or
``-inf <= 100`` decide compliance.

Stateless predicates:

* ``must_not_exceed`` — ``observed <= value``
* ``must_be_at_least`` — ``observed >= value``
* ``must_be_within`` — ``value[0] <= observed <= value[1]``
* ``must_equal`` — ``observed == value``
* ``must_not_equal`` — ``observed != value``

Stateful predicates (window queries backed by the telemetry buffer):

* ``must_average_within`` — the windowed average falls within a range
* ``must_not_exceed_in_window`` — no windowed sample exceeds a cap

Stateful predicates are evaluated via the async ``acheck_assertion`` /
``averify`` methods against a :class:`BufferLike` telemetry buffer.
"""

from __future__ import annotations

import logging
import math
import statistics
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

from .envelope import (
    FormalizableAssertion,
    V3Verdict,
    VerifierResult,
    VerifierStatus,
)

logger = logging.getLogger(__name__)


# ---- Divergence kinds (v3.2.0, finding C1) -----------------------------------

OMITTED_OBLIGATION = "OMITTED_OBLIGATION"
OMITTED_OBLIGATION_UNVERIFIABLE = "OMITTED_OBLIGATION_UNVERIFIABLE"
UNFLAGGED_BREACH = "UNFLAGGED_BREACH"
SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
UNIT_MISMATCH = "UNIT_MISMATCH"

_SPEC_OBLIGATION_TYPES = frozenset(
    {
        "must",
        "must_not",
        "must_not_exceed",
        "must_be_at_least",
        "must_be_below",
        "must_be_above",
        "must_be_within",
        "must_be_one_of",
        "must_not_be_one_of",
        "must_be_recorded_within",
        "should",
        "discretionary",
    }
)
"""The closed ``obligation_type`` enumeration of spec §3.3."""


# ---- Buffer protocol (telemetry history source) -------------------------------


class BufferLike(Protocol):
    """Minimal interface the verifier needs to evaluate stateful predicates.

    The production telemetry buffer (``telemetry_buffer.TelemetryBuffer``)
    satisfies this protocol; tests use a fake. Implementations are async
    because real buffers issue database queries.

    ``window_query`` covers the window ``[as_of - window_seconds, as_of]``
    for ``metric_path`` on ``subject`` and returns either:

    * an aggregate with ``avg_value`` and ``max_value`` attributes (the
      production ``telemetry_buffer.WindowQueryResult``), each ``None``
      when the window holds no numeric sample for the metric; or
    * a list of samples — ``(timestamp, value)`` pairs, dicts with a
      ``value`` key, or bare numerics. Empty if no samples in the window.

    Any other result, or an exception from the query, makes the stateful
    predicate UNVERIFIABLE.
    """

    async def window_query(
        self,
        *,
        subject: str,
        as_of: datetime,
        window_seconds: int,
        metric_path: Optional[str] = None,
    ) -> Any: ...


# ---- Predicate handlers -------------------------------------------------------


@dataclass(frozen=True)
class _CheckOutcome:
    """Result of mechanically evaluating a single :class:`FormalizableAssertion`.

    ``mechanically_satisfied`` is the verifier's own computation; ``None`` when
    the predicate is one the verifier cannot evaluate (UNVERIFIABLE). The
    ``reason`` string records why the verifier reached this outcome — it goes
    into :attr:`VerifierResult.divergences` when there is a disagreement.
    """

    mechanically_satisfied: Optional[bool]
    reason: str


_STATELESS_PREDICATES = frozenset(
    {
        "must_not_exceed",
        "must_be_at_least",
        "must_be_below",
        "must_be_above",
        "must_be_within",
        "must_be_one_of",
        "must_not_be_one_of",
        "must_equal",
        "must_not_equal",
    }
)


def _is_real(v: Any) -> bool:
    """True for a finite, non-bool number: an int of any size, or a finite float.

    Comparisons on these are exact in Python (``10**400 <= 100.0`` is
    ``False``), so the handlers compare the raw values and never convert an
    int to float (which raises ``OverflowError`` beyond ~1.8e308).
    """
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and math.isfinite(v)


def _non_numeric(predicate: str, observed: Any, value: Any) -> Optional[_CheckOutcome]:
    """UNVERIFIABLE unless both operands are finite, non-bool numbers.

    ``True <= 100`` and ``-inf <= 100`` are both ``True`` in Python; neither
    is a reading that can establish compliance.
    """
    if not (_is_real(observed) and _is_real(value)):
        return _CheckOutcome(
            None,
            f"{predicate} requires finite, non-boolean numeric operands; "
            f"got observed={observed!r} value={value!r}.",
        )
    return None


def _ambiguous_equality(a: Any, b: Any) -> bool:
    """True when ``a == b`` would be decided by bool/number punning or a non-finite float."""
    if any(isinstance(x, float) and not math.isfinite(x) for x in (a, b)):
        return True
    numbers = (int, float)
    return isinstance(a, numbers) and isinstance(b, numbers) and isinstance(a, bool) != isinstance(b, bool)


def _check_must_not_exceed(observed: Any, value: Any) -> _CheckOutcome:
    bad = _non_numeric("must_not_exceed", observed, value)
    if bad is not None:
        return bad
    ok = observed <= value
    return _CheckOutcome(ok, f"observed={observed} <= value={value}: {ok}")


def _check_must_be_at_least(observed: Any, value: Any) -> _CheckOutcome:
    bad = _non_numeric("must_be_at_least", observed, value)
    if bad is not None:
        return bad
    ok = observed >= value
    return _CheckOutcome(ok, f"observed={observed} >= value={value}: {ok}")


def _check_must_be_within(observed: Any, value: Any) -> _CheckOutcome:
    if not _is_real(observed):
        return _CheckOutcome(
            None,
            f"must_be_within requires a finite, non-boolean numeric observed; got {observed!r}.",
        )
    if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_real(b) for b in value)):
        return _CheckOutcome(
            None,
            f"must_be_within requires value=[lo, hi] of two finite numbers; got {value!r}.",
        )
    lo, hi = value[0], value[1]
    ok = lo <= observed <= hi
    return _CheckOutcome(ok, f"{lo} <= observed={observed} <= {hi}: {ok}")


def _check_must_equal(observed: Any, value: Any) -> _CheckOutcome:
    if _ambiguous_equality(observed, value):
        return _CheckOutcome(None, f"must_equal cannot compare observed={observed!r} with value={value!r}.")
    ok = observed == value
    return _CheckOutcome(ok, f"observed={observed!r} == value={value!r}: {ok}")


def _check_must_not_equal(observed: Any, value: Any) -> _CheckOutcome:
    if _ambiguous_equality(observed, value):
        return _CheckOutcome(
            None, f"must_not_equal cannot compare observed={observed!r} with value={value!r}."
        )
    ok = observed != value
    return _CheckOutcome(ok, f"observed={observed!r} != value={value!r}: {ok}")


def _check_must_be_below(observed: Any, value: Any) -> _CheckOutcome:
    bad = _non_numeric("must_be_below", observed, value)
    if bad is not None:
        return bad
    ok = observed < value  # strictly below, per spec §3.3
    return _CheckOutcome(ok, f"observed={observed} < value={value}: {ok}")


def _check_must_be_above(observed: Any, value: Any) -> _CheckOutcome:
    bad = _non_numeric("must_be_above", observed, value)
    if bad is not None:
        return bad
    ok = observed > value  # strictly above, per spec §3.3
    return _CheckOutcome(ok, f"observed={observed} > value={value}: {ok}")


def _check_must_be_one_of(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(value, (list, tuple)) or not value:
        return _CheckOutcome(
            None,
            f"must_be_one_of requires value to be a non-empty list; got {value!r}.",
        )
    if any(_ambiguous_equality(observed, member) for member in value):
        return _CheckOutcome(
            None, f"must_be_one_of cannot compare observed={observed!r} with {list(value)!r}."
        )
    ok = observed in value
    return _CheckOutcome(ok, f"observed={observed!r} in {list(value)!r}: {ok}")


def _check_must_not_be_one_of(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(value, (list, tuple)) or not value:
        return _CheckOutcome(
            None,
            f"must_not_be_one_of requires value to be a non-empty list; got {value!r}.",
        )
    if any(_ambiguous_equality(observed, member) for member in value):
        return _CheckOutcome(
            None, f"must_not_be_one_of cannot compare observed={observed!r} with {list(value)!r}."
        )
    ok = observed not in value
    return _CheckOutcome(ok, f"observed={observed!r} not in {list(value)!r}: {ok}")


_PREDICATE_HANDLERS = {
    "must_not_exceed": _check_must_not_exceed,
    "must_be_at_least": _check_must_be_at_least,
    "must_be_below": _check_must_be_below,
    "must_be_above": _check_must_be_above,
    "must_be_within": _check_must_be_within,
    "must_be_one_of": _check_must_be_one_of,
    "must_not_be_one_of": _check_must_not_be_one_of,
    "must_equal": _check_must_equal,
    "must_not_equal": _check_must_not_equal,
}


_STATEFUL_PREDICATES = frozenset({"must_average_within", "must_not_exceed_in_window"})


def _finite_number(v: Any) -> Optional[float]:
    """``float(v)`` for a finite int/float; ``None`` for anything else.

    bool is an int subclass and is rejected explicitly; NaN/inf are not
    readings (and NaN makes ``max()`` order-dependent).
    """
    if not _is_real(v):
        return None
    try:
        f = float(v)
    except OverflowError:  # an int beyond the double range
        return None
    return f if math.isfinite(f) else None


def _extract_values(window_data: Any) -> List[float]:
    """Coerce a list-shaped window_query result into a list of floats.

    Accepts an iterable of:
      * (timestamp, value) tuples
      * dicts with a ``value`` key
      * bare numerics

    Non-numeric, non-finite or malformed entries are dropped. Returning a
    clean list lets the predicate handlers stay focused on the statistical
    question, not the parsing. Raises ``TypeError`` if ``window_data`` is
    not iterable.
    """
    values: List[float] = []
    for entry in window_data:
        if isinstance(entry, tuple) and len(entry) == 2:
            _ts, v = entry
        elif isinstance(entry, dict) and "value" in entry:
            v = entry["value"]
        else:
            v = entry
        f = _finite_number(v)
        if f is None:
            logger.debug("Dropping non-numeric buffer value: %r", v)
            continue
        values.append(f)
    return values


@dataclass(frozen=True)
class _WindowSummary:
    """The window statistics the stateful predicates need, whatever the buffer shape.

    ``average`` / ``peak`` are ``None`` when there is no numeric sample for
    the metric in the window, or the buffer does not report that statistic.
    ``samples`` is ``None`` when the buffer only reports aggregates.
    """

    average: Optional[float]
    peak: Optional[float]
    samples: Optional[int]
    peak_reported: bool = True


def _summarize_window(window_data: Any) -> Optional[_WindowSummary]:
    """Reduce a buffer's window_query result to a :class:`_WindowSummary`.

    Two shapes are accepted (see :class:`BufferLike`):

    * the production aggregate (``telemetry_buffer.WindowQueryResult``):
      ``avg_value`` is the average; ``max_value`` the peak. A result
      without ``max_value`` (older buffers) cannot answer peak queries.
    * a list of samples, reduced here with ``fmean`` / ``max``.

    Returns ``None`` for any other shape; the caller maps that to
    UNVERIFIABLE.
    """
    if hasattr(window_data, "avg_value"):
        return _WindowSummary(
            average=_finite_number(getattr(window_data, "avg_value", None)),
            peak=_finite_number(getattr(window_data, "max_value", None)),
            samples=None,
            peak_reported=hasattr(window_data, "max_value"),
        )
    try:
        values = _extract_values(window_data)
    except TypeError:
        return None
    return _WindowSummary(
        average=statistics.fmean(values) if values else None,
        peak=max(values) if values else None,
        samples=len(values),
    )


async def _query_window(
    predicate: str,
    assertion: FormalizableAssertion,
    *,
    subject: str,
    as_of: datetime,
    window_seconds: int,
    buffer: BufferLike,
) -> Union[_WindowSummary, _CheckOutcome]:
    """Run the window query; any failure becomes an UNVERIFIABLE outcome.

    A stateful check must never crash the evaluation (the buffer is a
    database) and never guess: a failed query or an unrecognised result
    is undecidable, not CLEAR.
    """
    try:
        data = await buffer.window_query(
            subject=subject,
            as_of=as_of,
            window_seconds=window_seconds,
            metric_path=assertion.metric,
        )
    except Exception as exc:
        logger.warning("%s: buffer window_query failed for %r: %r", predicate, assertion.metric, exc)
        return _CheckOutcome(
            None,
            f"{predicate}: telemetry buffer window query failed ({type(exc).__name__}: {exc}).",
        )
    summary = _summarize_window(data)
    if summary is None:
        return _CheckOutcome(
            None,
            f"{predicate}: unrecognised telemetry buffer result of type {type(data).__name__}.",
        )
    return summary


def _sample_note(summary: _WindowSummary) -> str:
    return f" (n={summary.samples})" if summary.samples is not None else ""


async def _check_must_average_within(
    assertion: FormalizableAssertion,
    *,
    subject: Optional[str],
    as_of: Optional[datetime],
    buffer: Optional[BufferLike],
) -> _CheckOutcome:
    if buffer is None or subject is None or as_of is None:
        return _CheckOutcome(
            None,
            "must_average_within requires a buffer, subject, and as_of timestamp.",
        )
    if assertion.window_seconds is None or assertion.window_seconds <= 0:
        return _CheckOutcome(
            None,
            f"must_average_within requires a positive window_seconds; got {assertion.window_seconds!r}.",
        )
    if not (
        isinstance(assertion.value, list)
        and len(assertion.value) == 2
        and all(_is_real(b) for b in assertion.value)
    ):
        return _CheckOutcome(
            None,
            f"must_average_within requires value=[lo, hi]; got {assertion.value!r}.",
        )

    summary = await _query_window(
        "must_average_within",
        assertion,
        subject=subject,
        as_of=as_of,
        window_seconds=assertion.window_seconds,
        buffer=buffer,
    )
    if isinstance(summary, _CheckOutcome):
        return summary
    if summary.average is None:
        return _CheckOutcome(
            None,
            f"No samples for metric {assertion.metric!r} in the last "
            f"{assertion.window_seconds}s; cannot compute average.",
        )

    lo, hi = assertion.value[0], assertion.value[1]  # exact: no float() overflow
    average = summary.average
    ok = lo <= average <= hi
    return _CheckOutcome(
        ok,
        f"average({assertion.metric}, {assertion.window_seconds}s)={average:.6g} "
        f"in [{lo}, {hi}]: {ok}{_sample_note(summary)}",
    )


async def _check_must_not_exceed_in_window(
    assertion: FormalizableAssertion,
    *,
    subject: Optional[str],
    as_of: Optional[datetime],
    buffer: Optional[BufferLike],
) -> _CheckOutcome:
    if buffer is None or subject is None or as_of is None:
        return _CheckOutcome(
            None,
            "must_not_exceed_in_window requires a buffer, subject, and as_of timestamp.",
        )
    if assertion.window_seconds is None or assertion.window_seconds <= 0:
        return _CheckOutcome(
            None,
            f"must_not_exceed_in_window requires a positive window_seconds; got {assertion.window_seconds!r}.",
        )
    if not _is_real(assertion.value):
        return _CheckOutcome(
            None,
            f"must_not_exceed_in_window requires a finite numeric value; got {assertion.value!r}.",
        )

    summary = await _query_window(
        "must_not_exceed_in_window",
        assertion,
        subject=subject,
        as_of=as_of,
        window_seconds=assertion.window_seconds,
        buffer=buffer,
    )
    if isinstance(summary, _CheckOutcome):
        return summary
    if not summary.peak_reported:
        return _CheckOutcome(
            None,
            "must_not_exceed_in_window: telemetry buffer does not report a window "
            "peak (no max_value); cannot check peak.",
        )
    if summary.peak is None:
        return _CheckOutcome(
            None,
            f"No samples for metric {assertion.metric!r} in the last "
            f"{assertion.window_seconds}s; cannot check peak.",
        )

    threshold = cast(Union[int, float], assertion.value)  # exact: no float() overflow
    peak = summary.peak
    ok = peak <= threshold
    return _CheckOutcome(
        ok,
        f"peak({assertion.metric}, {assertion.window_seconds}s)={peak:.6g} "
        f"<= {threshold}: {ok}{_sample_note(summary)}",
    )


_STATEFUL_HANDLERS = {
    "must_average_within": _check_must_average_within,
    "must_not_exceed_in_window": _check_must_not_exceed_in_window,
}

_FORMALIZABLE_PREDICATES = frozenset(_PREDICATE_HANDLERS) | frozenset(_STATEFUL_HANDLERS)
"""Predicates the verifier can evaluate mechanically."""

KNOWN_PREDICATES = _SPEC_OBLIGATION_TYPES | _FORMALIZABLE_PREDICATES
"""Spec §3.3's closed enumeration plus this implementation's evaluable predicates.

An assertion predicate outside this set is a ``SCHEMA_VIOLATION``.
"""


# ---- SymbolicVerifier ---------------------------------------------------------


def _obligation_grounding_violation(
    assertion: FormalizableAssertion, obligations: Mapping[str, Mapping[str, Any]]
) -> Optional[str]:
    """Check an assertion's claim against the cited KG obligation.

    Measurement grounding (above) pins ``observed`` to reality; this pins
    ``metric`` and ``value`` to the *obligation the assertion cites*. Found
    by eval run 5's analysis: nothing stopped a model from asserting a
    fabricated cap (value=999 against a KG value of 100) or attaching the
    right obligation id to the wrong metric — internally consistent
    arithmetic would then verify a claim the KG never made.
    """
    ob = obligations.get(assertion.obligation_id)
    if ob is None:
        return (
            f"[{assertion.obligation_id}] fabricated obligation reference: id is not "
            f"present in the scoped KG snapshot."
        )
    ob_metric = ob.get("metric")
    if ob_metric is not None and assertion.metric != ob_metric:
        return (
            f"[{assertion.obligation_id}] obligation mismatch: assertion metric "
            f"{assertion.metric!r} but the obligation governs {ob_metric!r}."
        )
    ob_predicate = ob.get("predicate")
    if ob_predicate is not None and assertion.predicate != ob_predicate:
        # v3.2.0: a model must not evaluate the cited obligation under a
        # different (e.g. more favourable) predicate.
        return (
            f"[{assertion.obligation_id}] obligation mismatch: assertion predicate "
            f"{assertion.predicate!r} but the obligation is {ob_predicate!r}."
        )
    ob_value = ob.get("value")
    if ob_value is not None and assertion.value is not None:
        a_val = assertion.value
        # int/float equality is exact in Python (100 == 100.0), so no float()
        # conversion (which overflows for very large ints); a list/tuple pair
        # compares element-wise the same way.
        if isinstance(ob_value, (list, tuple)) and isinstance(a_val, (list, tuple)):
            mismatch = list(ob_value) != list(a_val)
        else:
            mismatch = ob_value != a_val
        if mismatch:
            return (
                f"[{assertion.obligation_id}] fabricated obligation value: assertion "
                f"claims {a_val!r} but the KG records {ob_value!r}."
            )
    return None


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _grounding_violation(assertion: FormalizableAssertion, measurement: Mapping[str, Any]) -> Optional[str]:
    """Check an assertion's observation against the actual measurement.

    The LLM asserts ``observed`` for ``metric``; the framework holds the
    ground truth — the measurement record itself. An assertion whose
    metric is not in the measurement, or whose observed value differs
    from what the measurement records, is a **fabricated observation**:
    internally consistent arithmetic must not pass verification when the
    observation it rests on was never made. (Found by eval run 4, where
    the model fuzzy-matched a deliberately unmapped measurement key onto
    a KG metric and invented the reading — producing a false FLAG that
    the arithmetic-only verifier agreed with.)

    Stateful predicates (``window_seconds`` set) aggregate over history,
    so their ``observed`` is not expected to equal the current reading;
    they are grounded against the telemetry buffer instead.
    """
    if assertion.window_seconds is not None or assertion.observed is None:
        return None
    if assertion.metric not in measurement:
        return (
            f"[{assertion.obligation_id}] fabricated observation: metric "
            f"{assertion.metric!r} is not a key of the measurement record "
            f"(keys: {sorted(measurement)!r})."
        )
    # A unit-bearing reading ({"value": x, "unit": u}) is grounded on its
    # value; the unit itself is checked against the obligation separately
    # (UNIT_MISMATCH).
    actual, _unit = _split_unit(measurement[assertion.metric])
    observed = assertion.observed
    if isinstance(actual, bool) or isinstance(observed, bool):
        # bool is an int subclass and pydantic coerces an asserted ``true``
        # to ``1.0``: a boolean reading must never ground a number.
        if not (isinstance(actual, bool) and isinstance(observed, bool) and actual == observed):
            return (
                f"[{assertion.obligation_id}] fabricated observation: LLM asserted "
                f"observed={observed!r} for {assertion.metric!r}, but the measurement "
                f"records the boolean {actual!r} (a boolean is not a numeric reading)."
            )
        return None
    if isinstance(actual, (int, float)) and isinstance(observed, (int, float)):
        # NaN != NaN: a faithfully copied non-finite reading is grounded (the
        # predicate handlers then fail closed on it), not "fabricated".
        # int/float equality is exact without float() (no OverflowError).
        both_nan = _is_nan(actual) and _is_nan(observed)
        mismatch = not both_nan and actual != observed
    else:
        mismatch = actual != observed
    if mismatch:
        return (
            f"[{assertion.obligation_id}] fabricated observation: LLM asserted "
            f"observed={observed!r} for {assertion.metric!r}, but the measurement "
            f"records {actual!r}."
        )
    return None


# ---- Independent enumeration (spec §5.3 step 4) --------------------------------


def _resolve_reading(measurement: Mapping[str, Any], metric: str) -> Tuple[bool, Any]:
    """``(found, raw)`` for ``metric``: a top-level key, else a dotted path into nested objects.

    The dotted-path fallback only ever *adds* obligations to the
    independent enumeration (fail closed); grounding of the LLM's own
    assertions still requires a top-level key (dotted-path grounding is
    Phase 1 work).
    """
    if metric in measurement:
        return True, measurement[metric]
    if "." not in metric:
        return False, None
    current: Any = measurement
    for part in metric.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _split_unit(raw: Any) -> Tuple[Any, Any]:
    """``(value, unit)`` of a reading; ``{"value": x, "unit": u}`` is the unit-bearing shape.

    Same shape the v2 Symbolic Evaluator accepts (``_value_and_unit``).
    """
    if isinstance(raw, Mapping) and "value" in raw:
        return raw.get("value"), raw.get("unit")
    return raw, None


def _enumerable_obligations(
    obligations: Optional[Mapping[str, Mapping[str, Any]]],
    measurement: Optional[Mapping[str, Any]],
) -> Iterator[Tuple[str, Mapping[str, Any], Any]]:
    """Yield ``(obligation_id, obligation, raw_reading)`` for every obligation the
    verifier evaluates itself: its metric is present in the measurement and its
    predicate is mechanically evaluable."""
    if not obligations or measurement is None:
        return
    for ob_id, ob in obligations.items():
        metric = ob.get("metric")
        if ob.get("predicate") not in _FORMALIZABLE_PREDICATES or not isinstance(metric, str):
            continue
        found, raw = _resolve_reading(measurement, metric)
        if found:
            yield str(ob_id), ob, raw


def index_obligations(
    obligations: Iterable[Any], measurement: Optional[Mapping[str, Any]] = None
) -> Tuple[Dict[str, Mapping[str, Any]], List[str]]:
    """Index a scoped KG slice's obligations by id, reporting what the index would hide.

    Returns ``(index, violations)``. The verifier grounds and enumerates by
    obligation id, so an obligation without a string id, or one whose id a
    later obligation repeats (the last occurrence wins, as before), would
    silently drop out of the independent enumeration. When such an obligation is one the verifier would evaluate
    (its predicate is formalizable and its metric is in ``measurement``),
    a ``SCHEMA_VIOLATION`` is returned for it; the evaluator routes that to
    DISCRETIONARY at every tier (:meth:`VerificationReport.with_fail_closed`).
    """
    entries = [ob for ob in obligations if isinstance(ob, Mapping)]
    # The last occurrence of an id wins, as in the dict the evaluator used
    # to build (grounding behaviour for a repeated id is unchanged).
    last = {ob["id"]: pos for pos, ob in enumerate(entries) if isinstance(ob.get("id"), str)}
    index: Dict[str, Mapping[str, Any]] = {}
    violations: List[str] = []
    for position, ob in enumerate(entries):
        ob_id = ob.get("id")
        if isinstance(ob_id, str) and last[ob_id] == position:
            index[ob_id] = ob
            continue
        if measurement is None:
            continue
        if next(_enumerable_obligations({"_": ob}, measurement), None) is None:
            continue
        what = "has no string id" if not isinstance(ob_id, str) else "repeats a later obligation's id"
        violations.append(
            f"{SCHEMA_VIOLATION}: [{ob_id if isinstance(ob_id, str) else f'#{position}'}] scoped KG "
            f"obligation #{position} ({ob.get('metric')!r} {ob.get('predicate')}) {what}; the verifier "
            "cannot evaluate it independently (fail closed)."
        )
    return index, violations


_MAX_DOUBLE = sys.float_info.max

_NUMERIC_OPERAND_PREDICATES = frozenset(
    {
        "must_not_exceed",
        "must_be_at_least",
        "must_be_below",
        "must_be_above",
        "must_be_within",
        "must_average_within",
        "must_not_exceed_in_window",
    }
)


def _non_finite_paths(value: Any, path: str) -> Iterator[str]:
    """Yield the path of every number nested anywhere in ``value`` that is not a
    finite IEEE-754 double: NaN, ±Infinity, or an integer beyond the double
    range (I-JSON, RFC 7493 §2.2; ``json.loads`` accepts all of them)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            yield path
    elif isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > _MAX_DOUBLE:
            yield path
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _non_finite_paths(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _non_finite_paths(item, f"{path}[{index}]")


def _expects_number(ob: Mapping[str, Any]) -> bool:
    """True when ``ob`` compares its metric against a number."""
    if ob.get("predicate") in _NUMERIC_OPERAND_PREDICATES:
        return True
    operand = ob.get("value")
    members = operand if isinstance(operand, (list, tuple)) else [operand]
    return any(isinstance(m, (int, float)) and not isinstance(m, bool) for m in members)


def measurement_input_errors(
    measurement: Mapping[str, Any], obligations: Iterable[Mapping[str, Any]] = ()
) -> List[str]:
    """Describe every reading the API must reject (HTTP 422) before evaluation.

    * a non-finite number (NaN, ±Infinity -- ``json.loads`` accepts all
      three) or an integer beyond the double range anywhere in the
      measurement;
    * a boolean where one of ``obligations`` expects a number for that
      metric (``True <= 100`` is ``True`` in Python).

    Returns an empty list for a well-formed measurement.
    """
    errors = [
        f"{path}: non-finite or out-of-range number is not a reading"
        for key, value in measurement.items()
        for path in _non_finite_paths(value, f"measurement.{key}")
    ]
    seen: Set[str] = set()
    for ob in obligations:
        metric = ob.get("metric")
        if not isinstance(metric, str) or metric in seen or not _expects_number(ob):
            continue
        found, raw = _resolve_reading(measurement, metric)
        reading, _unit = _split_unit(raw)
        if found and isinstance(reading, bool):
            seen.add(metric)
            errors.append(
                f"measurement.{metric}: boolean {reading!r} where obligation "
                f"{ob.get('id')!r} ({ob.get('predicate')}) expects a number"
            )
    return errors


def _unit_mismatch(ob_id: str, ob: Mapping[str, Any], raw: Any) -> Optional[str]:
    """A ``UNIT_MISMATCH`` divergence when the reading's unit differs from the obligation's."""
    _value, unit = _split_unit(raw)
    declared = ob.get("unit")
    if unit is None or declared is None or unit == declared:
        return None
    return (
        f"{UNIT_MISMATCH}: [{ob_id}] measurement reports {ob.get('metric')!r} in {unit!r} but the "
        f"obligation is stated in {declared!r}; no unit conversion is attempted (fail closed)."
    )


def _obligation_probe(ob_id: str, ob: Mapping[str, Any], raw: Any) -> FormalizableAssertion:
    """The verifier's own assertion for ``ob``: KG predicate/value, measured reading.

    ``model_construct`` skips pydantic coercion so a bool or non-finite
    reading reaches the handlers as-is (and fails closed there).
    """
    reading, _unit = _split_unit(raw)
    window = ob.get("window_seconds")
    return FormalizableAssertion.model_construct(
        predicate=ob["predicate"],
        metric=ob["metric"],
        value=ob.get("value"),
        observed=reading,
        satisfied=True,
        obligation_id=ob_id,
        window_seconds=window if isinstance(window, int) and not isinstance(window, bool) else None,
    )


@dataclass(frozen=True)
class VerificationReport:
    """A :class:`VerifierResult` plus what the evaluator needs to fail closed.

    ``breached_obligations``: the scoped obligations the verifier itself
    evaluated as breached (from the measurement and the KG, never from the
    LLM). ``fail_closed``: the ``SCHEMA_VIOLATION`` / ``UNIT_MISMATCH``
    divergences, which route to DISCRETIONARY at every tier. ``notes``:
    obligations the LLM did not assert but the verifier checked and found
    satisfied.
    """

    result: VerifierResult
    breached_obligations: Tuple[str, ...] = ()
    fail_closed: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    def with_fail_closed(self, violations: Sequence[str]) -> VerificationReport:
        """This report plus fail-closed ``violations`` found outside the verifier.

        Each is appended to the divergences and to :attr:`fail_closed`; an
        ``AGREED`` / ``NEURO_SYMBOLIC_DIVERGENCE`` status becomes
        ``UNVERIFIABLE`` (a contradiction keeps precedence).
        """
        if not violations:
            return self
        status = self.result.status
        if status != VerifierStatus.LLM_CONTRADICTION:
            status = VerifierStatus.UNVERIFIABLE
        result = VerifierResult(
            status=status,
            checked_assertions=self.result.checked_assertions,
            divergences=[*self.result.divergences, *violations],
        )
        return replace(self, result=result, fail_closed=(*self.fail_closed, *violations))


_UNFLAGGED_VERDICTS = frozenset({V3Verdict.CLEAR, V3Verdict.NULL_UNMAPPED})
"""LLM verdicts that a breached mapped obligation contradicts outright."""


@dataclass
class _Tally:
    """Classifies per-assertion and per-obligation outcomes for one verify call.

    Shared by :meth:`SymbolicVerifier.verify_report` and
    :meth:`SymbolicVerifier.averify_report` so the sync and async paths
    cannot drift apart again.
    """

    llm_verdict: V3Verdict
    divergences: List[str] = field(default_factory=list)
    checked: int = 0
    unverifiable: int = 0
    contradictions: int = 0
    breached: List[str] = field(default_factory=list)
    fail_closed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    _breach_reported: Set[str] = field(default_factory=set)

    def _contradiction(self, message: str) -> None:
        self.contradictions += 1
        self.divergences.append(message)

    def _unflagged(self, ob_id: str, detail: str) -> None:
        self._breach_reported.add(ob_id)
        self._contradiction(
            f"{UNFLAGGED_BREACH}: [{ob_id}] LLM verdict {self.llm_verdict.value} but {detail}"
        )

    def precheck(
        self,
        assertion: FormalizableAssertion,
        measurement: Optional[Mapping[str, Any]],
        obligations: Optional[Mapping[str, Mapping[str, Any]]],
    ) -> bool:
        """Schema and grounding checks; True when they settled the assertion."""
        if assertion.predicate not in KNOWN_PREDICATES:
            msg = (
                f"{SCHEMA_VIOLATION}: [{assertion.obligation_id}] predicate {assertion.predicate!r} "
                "is outside the closed obligation-type enumeration (spec §3.3)."
            )
            self.unverifiable += 1
            self.divergences.append(msg)
            self.fail_closed.append(msg)
            return True
        violation = None
        if measurement is not None:
            violation = _grounding_violation(assertion, measurement)
        if violation is None and obligations is not None:
            violation = _obligation_grounding_violation(assertion, obligations)
        if violation is None:
            return False
        self.checked += 1
        self._contradiction(violation)
        return True

    def assertion(self, assertion: FormalizableAssertion, outcome: _CheckOutcome) -> None:
        """Record the mechanical outcome of one LLM assertion that passed :meth:`precheck`."""
        ob_id = assertion.obligation_id
        unflagged = self.llm_verdict in _UNFLAGGED_VERDICTS
        if outcome.mechanically_satisfied is None:
            self.unverifiable += 1
            self.divergences.append(f"[{ob_id}] {outcome.reason}")
            if unflagged and not assertion.satisfied:
                # The verdict contradicts the LLM's own (unverifiable) claim.
                self._unflagged(ob_id, "its own assertion reports the obligation unsatisfied.")
            return
        self.checked += 1
        if outcome.mechanically_satisfied != assertion.satisfied:
            if not outcome.mechanically_satisfied:
                self._breach_reported.add(ob_id)
            self._contradiction(
                f"[{ob_id}] LLM said satisfied={assertion.satisfied}, "
                f"verifier says {outcome.mechanically_satisfied}. {outcome.reason}"
            )
        elif not outcome.mechanically_satisfied and unflagged:
            # Agreed per assertion (e.g. after satisfied normalisation) but the
            # verdict rests on an asserted breach. Was NEURO_SYMBOLIC_DIVERGENCE
            # before v3.2.0, which tier-3 accepted => CLEAR.
            self._unflagged(ob_id, f"the verifier evaluates this assertion as breached. {outcome.reason}")

    def unit_mismatch(self, message: str) -> None:
        self.unverifiable += 1
        self.divergences.append(message)
        self.fail_closed.append(message)

    def obligation(self, ob_id: str, outcome: _CheckOutcome, *, asserted: bool) -> None:
        """Record the verifier's own evaluation of one mapped obligation."""
        breached = outcome.mechanically_satisfied is False
        if breached:
            self.breached.append(ob_id)
        if asserted:
            # The LLM's own assertion(s) were checked above; what remains is a
            # verdict that ignores a breach the verifier itself establishes
            # (e.g. the LLM evaluated it under a substituted predicate).
            if breached and self.llm_verdict in _UNFLAGGED_VERDICTS and ob_id not in self._breach_reported:
                self._unflagged(
                    ob_id, f"the verifier's own evaluation of the obligation says breached. {outcome.reason}"
                )
            return
        if outcome.mechanically_satisfied is None:
            self.unverifiable += 1
            self.divergences.append(
                f"{OMITTED_OBLIGATION_UNVERIFIABLE}: [{ob_id}] omitted by LLM; verifier could not "
                f"evaluate it. {outcome.reason}"
            )
            return
        self.checked += 1
        if breached:
            self._contradiction(
                f"{OMITTED_OBLIGATION}: [{ob_id}] omitted by LLM; verifier says breached. {outcome.reason}"
            )
        else:
            self.notes.append(
                f"independent_check: [{ob_id}] not asserted by LLM; verifier evaluated it "
                f"independently: satisfied. {outcome.reason}"
            )

    def report(self, assertions: Sequence[FormalizableAssertion]) -> VerificationReport:
        """Aggregate with precedence LLM_CONTRADICTION > UNVERIFIABLE > NSD > AGREED."""
        if self.contradictions:
            status = VerifierStatus.LLM_CONTRADICTION
            divergences = self.divergences
        elif self.unverifiable or not assertions:
            # No formalizable assertions to check is UNVERIFIABLE; whether that
            # is a problem is the risk-tier policy's call.
            status = VerifierStatus.UNVERIFIABLE
            divergences = ([] if assertions else ["No formalizable assertions to verify."]) + self.divergences
        else:
            # Every assertion agrees and no CLEAR / NULL_UNMAPPED rests on a
            # breach (that would be UNFLAGGED_BREACH above). What is left to
            # sanity-check is a FLAG none of whose assertions is unsatisfied.
            all_satisfied = all(a.satisfied for a in assertions)
            if self.llm_verdict == V3Verdict.FLAG and all_satisfied:
                status = VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE
                divergences = [
                    f"Per-assertion checks agree, but LLM verdict {self.llm_verdict.value!r} "
                    f"is not consistent with the satisfied flags "
                    f"(all_satisfied={all_satisfied}, any_unsatisfied={not all_satisfied})."
                ]
            else:
                status = VerifierStatus.AGREED
                divergences = []
        return VerificationReport(
            result=VerifierResult(status=status, checked_assertions=self.checked, divergences=divergences),
            breached_obligations=tuple(self.breached),
            fail_closed=tuple(self.fail_closed),
            notes=tuple(self.notes),
        )


@dataclass
class SymbolicVerifier:
    """Mechanically cross-checks :class:`FormalizableAssertion` instances.

    Instances are stateless and can be reused across requests. The
    stateless predicates (``check_assertion``/``verify``) do no I/O.
    Stateful predicates (``must_average_within``,
    ``must_not_exceed_in_window``) query the telemetry buffer via the
    async ``acheck_assertion``/``averify`` methods; they require
    ``subject``, ``as_of``, and ``buffer`` to be supplied, and yield
    ``UNVERIFIABLE`` when any of those is missing or the predicate is
    otherwise unknown.
    """

    def check_assertion(self, assertion: FormalizableAssertion) -> _CheckOutcome:
        """Mechanically evaluate one stateless assertion.

        Returns ``mechanically_satisfied=None`` when the predicate cannot be
        evaluated; the caller maps that to ``UNVERIFIABLE``. Stateful
        predicates always return ``None`` here — use :meth:`acheck_assertion`
        (with a buffer) to actually evaluate them.
        """
        handler = _PREDICATE_HANDLERS.get(assertion.predicate)
        if handler is not None:
            return handler(assertion.observed, assertion.value)
        if assertion.predicate in _STATEFUL_PREDICATES:
            return _CheckOutcome(
                None,
                f"Predicate {assertion.predicate!r} is stateful; use averify(buffer=...).",
            )
        return _CheckOutcome(
            None,
            f"Predicate {assertion.predicate!r} is not mechanically verifiable (no v3 handler for it).",
        )

    async def acheck_assertion(
        self,
        assertion: FormalizableAssertion,
        *,
        subject: Optional[str],
        as_of: Optional[datetime],
        buffer: Optional[BufferLike],
    ) -> _CheckOutcome:
        """Async per-assertion check that handles both stateless and stateful predicates."""
        handler = _PREDICATE_HANDLERS.get(assertion.predicate)
        if handler is not None:
            return handler(assertion.observed, assertion.value)
        stateful = _STATEFUL_HANDLERS.get(assertion.predicate)
        if stateful is None:
            return _CheckOutcome(
                None,
                f"Predicate {assertion.predicate!r} is not mechanically verifiable (no v3 handler for it).",
            )
        return await stateful(assertion, subject=subject, as_of=as_of, buffer=buffer)

    def normalize_satisfied(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        measurement: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> tuple[list[FormalizableAssertion], list[str]]:
        """Correct ``satisfied`` flags that the verifier can compute mechanically.

        This is the neuro-symbolic handoff for assertion truth values. For any
        stateless predicate (``must_not_exceed``, ``must_be_at_least``,
        ``must_be_within``, ``must_equal``, ``must_not_equal``) the verifier
        re-evaluates the predicate from ``observed`` and ``value`` and, when its
        answer differs from the LLM's ``satisfied`` flag, replaces the flag with
        the mechanically correct value. The correction is noted for the envelope's
        ``notes`` field so auditors can see what was fixed.

        Grounding failures (metric absent from measurement, value mismatch vs
        obligation) are intentionally left untouched — the grounding error itself
        is the signal, and ``averify`` will record it as ``LLM_CONTRADICTION``.

        Normalisation can never turn a breach into a CLEAR: a CLEAR (or
        NULL_UNMAPPED) verdict resting on an assertion normalised to
        ``satisfied=False`` is an ``UNFLAGGED_BREACH`` contradiction.

        Call this *before* :meth:`averify` and pass the returned assertion list
        to ``averify``. The resulting :class:`VerifierResult` will reflect the
        mechanically correct values; the raw LLM claims live in the transcript.

        Returns:
            A ``(corrected_assertions, notes)`` pair where ``notes`` is a list
            of human-readable strings describing each correction made.
        """
        corrected: list[FormalizableAssertion] = []
        notes: list[str] = []

        for assertion in assertions:
            # Skip normalization when grounding has already failed — the
            # grounding error is the real signal; averify will catch it.
            if measurement is not None:
                violation = _grounding_violation(assertion, measurement)
                if violation is not None:
                    corrected.append(assertion)
                    continue
            if obligations is not None:
                ob_violation = _obligation_grounding_violation(assertion, obligations)
                if ob_violation is not None:
                    corrected.append(assertion)
                    continue

            outcome = self.check_assertion(assertion)
            if (
                outcome.mechanically_satisfied is not None
                and outcome.mechanically_satisfied != assertion.satisfied
            ):
                notes.append(
                    f"[{assertion.obligation_id}] satisfied normalised "
                    f"{assertion.satisfied!r} -> {outcome.mechanically_satisfied!r}: "
                    f"{outcome.reason}"
                )
                corrected.append(assertion.model_copy(update={"satisfied": outcome.mechanically_satisfied}))
            else:
                corrected.append(assertion)

        return corrected, notes

    def verify(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
        measurement: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> VerifierResult:
        """Aggregate per-assertion checks into a :class:`VerifierResult`.

        Decision rules (precedence from the top, framework v3.2.0):

          * Any contradiction → LLM_CONTRADICTION: a per-assertion
            disagreement (mechanical != LLM's ``satisfied``), a grounding
            violation, an ``OMITTED_OBLIGATION`` (a mapped obligation the
            LLM did not assert and the verifier evaluates as breached), or
            an ``UNFLAGGED_BREACH`` (a CLEAR / NULL_UNMAPPED verdict resting
            on a breach). Unverifiable assertions can no longer mask it.
          * Any UNVERIFIABLE assertion or omitted obligation, a
            ``SCHEMA_VIOLATION`` or a ``UNIT_MISMATCH`` → UNVERIFIABLE.
          * All per-assertion outcomes agree, but the LLM verdict is FLAG
            while every assertion is satisfied → NEURO_SYMBOLIC_DIVERGENCE.
          * Otherwise → AGREED.

        ``measurement`` and ``obligations`` (the scoped KG slice, keyed by
        id) enable grounding and independent enumeration; use
        :meth:`verify_report` to also get the breached obligations and the
        fail-closed divergences.
        """
        return self.verify_report(
            assertions, llm_verdict=llm_verdict, measurement=measurement, obligations=obligations
        ).result

    def verify_report(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
        measurement: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> VerificationReport:
        """:meth:`verify`, returning the full :class:`VerificationReport`."""
        tally = _Tally(llm_verdict=V3Verdict(llm_verdict))
        asserted: Set[str] = set()
        for assertion in assertions:
            asserted.add(assertion.obligation_id)
            if not tally.precheck(assertion, measurement, obligations):
                tally.assertion(assertion, self.check_assertion(assertion))
        for ob_id, ob, raw in _enumerable_obligations(obligations, measurement):
            mismatch = _unit_mismatch(ob_id, ob, raw)
            if mismatch is not None:
                tally.unit_mismatch(mismatch)
                continue
            probe = _obligation_probe(ob_id, ob, raw)
            tally.obligation(ob_id, self.check_assertion(probe), asserted=ob_id in asserted)
        return tally.report(assertions)

    async def averify(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
        subject: Optional[str] = None,
        as_of: Optional[datetime] = None,
        buffer: Optional[BufferLike] = None,
        measurement: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> VerifierResult:
        """Async sibling of :meth:`verify` that handles stateful predicates.

        Stateless predicates produce the same result as :meth:`verify`.
        Stateful predicates (e.g. ``must_average_within``,
        ``must_not_exceed_in_window``) require ``subject``, ``as_of``,
        and ``buffer``; when any of those is missing the predicate
        yields ``UNVERIFIABLE``.
        """
        report = await self.averify_report(
            assertions,
            llm_verdict=llm_verdict,
            subject=subject,
            as_of=as_of,
            buffer=buffer,
            measurement=measurement,
            obligations=obligations,
        )
        return report.result

    async def averify_report(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
        subject: Optional[str] = None,
        as_of: Optional[datetime] = None,
        buffer: Optional[BufferLike] = None,
        measurement: Optional[Mapping[str, Any]] = None,
        obligations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> VerificationReport:
        """:meth:`averify`, returning the full :class:`VerificationReport`."""
        tally = _Tally(llm_verdict=V3Verdict(llm_verdict))
        asserted: Set[str] = set()
        for assertion in assertions:
            asserted.add(assertion.obligation_id)
            if not tally.precheck(assertion, measurement, obligations):
                outcome = await self.acheck_assertion(assertion, subject=subject, as_of=as_of, buffer=buffer)
                tally.assertion(assertion, outcome)
        for ob_id, ob, raw in _enumerable_obligations(obligations, measurement):
            mismatch = _unit_mismatch(ob_id, ob, raw)
            if mismatch is not None:
                tally.unit_mismatch(mismatch)
                continue
            probe = _obligation_probe(ob_id, ob, raw)
            outcome = await self.acheck_assertion(probe, subject=subject, as_of=as_of, buffer=buffer)
            tally.obligation(ob_id, outcome, asserted=ob_id in asserted)
        return tally.report(assertions)


__all__ = [
    "KNOWN_PREDICATES",
    "OMITTED_OBLIGATION",
    "OMITTED_OBLIGATION_UNVERIFIABLE",
    "SCHEMA_VIOLATION",
    "UNFLAGGED_BREACH",
    "UNIT_MISMATCH",
    "BufferLike",
    "SymbolicVerifier",
    "VerificationReport",
    "index_obligations",
    "measurement_input_errors",
]
