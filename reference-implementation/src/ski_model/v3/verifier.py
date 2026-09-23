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
  doesn't match what those assertions imply (e.g. all satisfied but the
  LLM still emitted FLAG, or vice versa).
* ``UNVERIFIABLE`` — at least one assertion uses a predicate the verifier
  cannot mechanically evaluate (e.g. predicates that require qualified
  human judgment). The envelope is forwarded as-is for human attestation.

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
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Mapping, Optional, Protocol, Sequence, Tuple, Union

from .envelope import (
    FormalizableAssertion,
    V3Verdict,
    VerifierResult,
    VerifierStatus,
)

logger = logging.getLogger(__name__)


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


def _check_must_not_exceed(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_not_exceed requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed <= value
    return _CheckOutcome(ok, f"observed={observed} <= value={value}: {ok}")


def _check_must_be_at_least(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_at_least requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed >= value
    return _CheckOutcome(ok, f"observed={observed} >= value={value}: {ok}")


def _check_must_be_within(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_within requires a numeric observed; got {observed!r}.",
        )
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(b, (int, float)) for b in value)
    ):
        return _CheckOutcome(
            None,
            f"must_be_within requires value=[lo, hi] of two numbers; got {value!r}.",
        )
    lo, hi = value[0], value[1]
    ok = lo <= observed <= hi
    return _CheckOutcome(ok, f"{lo} <= observed={observed} <= {hi}: {ok}")


def _check_must_equal(observed: Any, value: Any) -> _CheckOutcome:
    ok = observed == value
    return _CheckOutcome(ok, f"observed={observed!r} == value={value!r}: {ok}")


def _check_must_not_equal(observed: Any, value: Any) -> _CheckOutcome:
    ok = observed != value
    return _CheckOutcome(ok, f"observed={observed!r} != value={value!r}: {ok}")


def _check_must_be_below(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_below requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed < value  # strictly below, per spec §3.3
    return _CheckOutcome(ok, f"observed={observed} < value={value}: {ok}")


def _check_must_be_above(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(observed, (int, float)) or not isinstance(value, (int, float)):
        return _CheckOutcome(
            None,
            f"must_be_above requires numeric operands; got observed={observed!r} value={value!r}.",
        )
    ok = observed > value  # strictly above, per spec §3.3
    return _CheckOutcome(ok, f"observed={observed} > value={value}: {ok}")


def _check_must_be_one_of(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(value, (list, tuple)) or not value:
        return _CheckOutcome(
            None,
            f"must_be_one_of requires value to be a non-empty list; got {value!r}.",
        )
    ok = observed in value
    return _CheckOutcome(ok, f"observed={observed!r} in {list(value)!r}: {ok}")


def _check_must_not_be_one_of(observed: Any, value: Any) -> _CheckOutcome:
    if not isinstance(value, (list, tuple)) or not value:
        return _CheckOutcome(
            None,
            f"must_not_be_one_of requires value to be a non-empty list; got {value!r}.",
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
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


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
            window_seconds=assertion.window_seconds,
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
        and all(isinstance(b, (int, float)) for b in assertion.value)
    ):
        return _CheckOutcome(
            None,
            f"must_average_within requires value=[lo, hi]; got {assertion.value!r}.",
        )

    summary = await _query_window(
        "must_average_within", assertion, subject=subject, as_of=as_of, buffer=buffer
    )
    if isinstance(summary, _CheckOutcome):
        return summary
    if summary.average is None:
        return _CheckOutcome(
            None,
            f"No samples for metric {assertion.metric!r} in the last "
            f"{assertion.window_seconds}s; cannot compute average.",
        )

    lo, hi = float(assertion.value[0]), float(assertion.value[1])
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
    if not isinstance(assertion.value, (int, float)) or isinstance(assertion.value, bool):
        return _CheckOutcome(
            None,
            f"must_not_exceed_in_window requires numeric value; got {assertion.value!r}.",
        )

    summary = await _query_window(
        "must_not_exceed_in_window", assertion, subject=subject, as_of=as_of, buffer=buffer
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

    threshold = float(assertion.value)
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
    ob_value = ob.get("value")
    if ob_value is not None and assertion.value is not None:
        a_val = assertion.value
        if isinstance(ob_value, (int, float)) and isinstance(a_val, (int, float)):
            mismatch = float(ob_value) != float(a_val)
        elif isinstance(ob_value, (list, tuple)) and isinstance(a_val, (list, tuple)):
            mismatch = [float(x) if isinstance(x, (int, float)) else x for x in ob_value] != [
                float(x) if isinstance(x, (int, float)) else x for x in a_val
            ]
        else:
            mismatch = ob_value != a_val
        if mismatch:
            return (
                f"[{assertion.obligation_id}] fabricated obligation value: assertion "
                f"claims {a_val!r} but the KG records {ob_value!r}."
            )
    return None


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
    actual = measurement[assertion.metric]
    observed = assertion.observed
    if isinstance(actual, (int, float)) and isinstance(observed, (int, float)):
        mismatch = float(actual) != float(observed)
    else:
        mismatch = actual != observed
    if mismatch:
        return (
            f"[{assertion.obligation_id}] fabricated observation: LLM asserted "
            f"observed={observed!r} for {assertion.metric!r}, but the measurement "
            f"records {actual!r}."
        )
    return None


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

        Decision rules:

          * Any UNVERIFIABLE assertion → status is UNVERIFIABLE.
          * Any per-assertion disagreement (mechanical != LLM's ``satisfied``)
            → LLM_CONTRADICTION.
          * All per-assertion outcomes agree, but the LLM verdict is
            inconsistent with what the satisfied flags imply
            (e.g. all satisfied yet verdict=FLAG, or any unsatisfied yet
            verdict=CLEAR) → NEURO_SYMBOLIC_DIVERGENCE.
          * Otherwise → AGREED.
        """
        if not assertions:
            # No formalizable assertions to check; verifier is silent.
            # Whether that is a problem is the risk-tier policy's call.
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=0,
                divergences=["No formalizable assertions to verify."],
            )

        divergences: List[str] = []
        unverifiable_count = 0
        contradictions: List[Tuple[FormalizableAssertion, _CheckOutcome]] = []
        checked = 0

        for assertion in assertions:
            if measurement is not None:
                violation = _grounding_violation(assertion, measurement)
                if violation is not None:
                    checked += 1
                    contradictions.append((assertion, _CheckOutcome(False, violation)))
                    divergences.append(violation)
                    continue
            if obligations is not None:
                ob_violation = _obligation_grounding_violation(assertion, obligations)
                if ob_violation is not None:
                    checked += 1
                    contradictions.append((assertion, _CheckOutcome(False, ob_violation)))
                    divergences.append(ob_violation)
                    continue
            outcome = self.check_assertion(assertion)
            if outcome.mechanically_satisfied is None:
                unverifiable_count += 1
                divergences.append(f"[{assertion.obligation_id}] {outcome.reason}")
                continue
            checked += 1
            if outcome.mechanically_satisfied != assertion.satisfied:
                contradictions.append((assertion, outcome))
                divergences.append(
                    f"[{assertion.obligation_id}] LLM said satisfied={assertion.satisfied}, "
                    f"verifier says {outcome.mechanically_satisfied}. {outcome.reason}"
                )

        if unverifiable_count > 0:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=checked,
                divergences=divergences,
            )

        if contradictions:
            return VerifierResult(
                status=VerifierStatus.LLM_CONTRADICTION,
                checked_assertions=checked,
                divergences=divergences,
            )

        # Per-assertion agreement is total. Now sanity-check the LLM's
        # overall verdict against what the satisfied flags imply.
        all_satisfied = all(a.satisfied for a in assertions)
        any_unsatisfied = any(not a.satisfied for a in assertions)

        expected_verdict_consistent_with_clear = all_satisfied
        expected_verdict_consistent_with_flag = any_unsatisfied

        verdict_inconsistent = (
            llm_verdict == V3Verdict.CLEAR and not expected_verdict_consistent_with_clear
        ) or (llm_verdict == V3Verdict.FLAG and not expected_verdict_consistent_with_flag)

        if verdict_inconsistent:
            return VerifierResult(
                status=VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE,
                checked_assertions=checked,
                divergences=[
                    f"Per-assertion checks agree, but LLM verdict {llm_verdict.value!r} "
                    f"is not consistent with the satisfied flags "
                    f"(all_satisfied={all_satisfied}, any_unsatisfied={any_unsatisfied})."
                ],
            )

        return VerifierResult(
            status=VerifierStatus.AGREED,
            checked_assertions=checked,
            divergences=[],
        )

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
        if not assertions:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=0,
                divergences=["No formalizable assertions to verify."],
            )

        divergences: List[str] = []
        unverifiable_count = 0
        contradictions: List[Tuple[FormalizableAssertion, _CheckOutcome]] = []
        checked = 0

        for assertion in assertions:
            if measurement is not None:
                violation = _grounding_violation(assertion, measurement)
                if violation is not None:
                    checked += 1
                    contradictions.append((assertion, _CheckOutcome(False, violation)))
                    divergences.append(violation)
                    continue
            if obligations is not None:
                ob_violation = _obligation_grounding_violation(assertion, obligations)
                if ob_violation is not None:
                    checked += 1
                    contradictions.append((assertion, _CheckOutcome(False, ob_violation)))
                    divergences.append(ob_violation)
                    continue
            outcome = await self.acheck_assertion(assertion, subject=subject, as_of=as_of, buffer=buffer)
            if outcome.mechanically_satisfied is None:
                unverifiable_count += 1
                divergences.append(f"[{assertion.obligation_id}] {outcome.reason}")
                continue
            checked += 1
            if outcome.mechanically_satisfied != assertion.satisfied:
                contradictions.append((assertion, outcome))
                divergences.append(
                    f"[{assertion.obligation_id}] LLM said satisfied={assertion.satisfied}, "
                    f"verifier says {outcome.mechanically_satisfied}. {outcome.reason}"
                )

        if unverifiable_count > 0:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIABLE,
                checked_assertions=checked,
                divergences=divergences,
            )

        if contradictions:
            return VerifierResult(
                status=VerifierStatus.LLM_CONTRADICTION,
                checked_assertions=checked,
                divergences=divergences,
            )

        all_satisfied = all(a.satisfied for a in assertions)
        any_unsatisfied = any(not a.satisfied for a in assertions)

        verdict_inconsistent = (llm_verdict == V3Verdict.CLEAR and not all_satisfied) or (
            llm_verdict == V3Verdict.FLAG and not any_unsatisfied
        )

        if verdict_inconsistent:
            return VerifierResult(
                status=VerifierStatus.NEURO_SYMBOLIC_DIVERGENCE,
                checked_assertions=checked,
                divergences=[
                    f"Per-assertion checks agree, but LLM verdict {llm_verdict.value!r} "
                    f"is not consistent with the satisfied flags "
                    f"(all_satisfied={all_satisfied}, any_unsatisfied={any_unsatisfied})."
                ],
            )

        return VerifierResult(
            status=VerifierStatus.AGREED,
            checked_assertions=checked,
            divergences=[],
        )


__all__ = ["BufferLike", "SymbolicVerifier"]
