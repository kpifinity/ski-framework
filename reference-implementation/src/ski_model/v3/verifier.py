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

Stateless predicates handled in PR 10c:

* ``must_not_exceed`` — ``observed <= value``
* ``must_be_at_least`` — ``observed >= value``
* ``must_be_within`` — ``value[0] <= observed <= value[1]``
* ``must_equal`` — ``observed == value``
* ``must_not_equal`` — ``observed != value``

Stateful predicates (window queries, time-bounded checks) require the
telemetry buffer and a database fixture; deferred to a follow-up PR.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Mapping, Optional, Protocol, Sequence, Tuple

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

    Returns:
        A list of ``(timestamp, value)`` pairs covering the window
        ``[as_of - window_seconds, as_of]`` for ``metric_path`` on
        ``subject``, sorted ascending by timestamp. Empty list if no
        samples in the window.
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
        "must_be_within",
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


_PREDICATE_HANDLERS = {
    "must_not_exceed": _check_must_not_exceed,
    "must_be_at_least": _check_must_be_at_least,
    "must_be_within": _check_must_be_within,
    "must_equal": _check_must_equal,
    "must_not_equal": _check_must_not_equal,
}


_STATEFUL_PREDICATES = frozenset({"must_average_within", "must_not_exceed_in_window"})


def _extract_values(window_data: Any) -> List[float]:
    """Coerce a buffer's window_query result into a list of floats.

    Accepts:
      * list of (timestamp, value) tuples
      * list of dicts with a ``value`` key
      * list of bare numerics

    Non-numeric or malformed entries are dropped (with a log warning).
    Returning a clean list lets the predicate handlers stay focused on
    the statistical question, not the parsing.
    """
    values: List[float] = []
    for entry in window_data or []:
        if isinstance(entry, tuple) and len(entry) == 2:
            _ts, v = entry
        elif isinstance(entry, dict) and "value" in entry:
            v = entry["value"]
        else:
            v = entry
        if isinstance(v, bool):
            # bool is an int subclass; reject explicitly.
            logger.debug("Dropping boolean buffer value: %r", v)
            continue
        if isinstance(v, (int, float)):
            values.append(float(v))
    return values


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

    data = await buffer.window_query(
        subject=subject,
        as_of=as_of,
        window_seconds=assertion.window_seconds,
        metric_path=assertion.metric,
    )
    values = _extract_values(data)
    if not values:
        return _CheckOutcome(
            None,
            f"No samples for metric {assertion.metric!r} in the last "
            f"{assertion.window_seconds}s; cannot compute average.",
        )

    lo, hi = float(assertion.value[0]), float(assertion.value[1])
    average = statistics.fmean(values)
    ok = lo <= average <= hi
    return _CheckOutcome(
        ok,
        f"average({assertion.metric}, {assertion.window_seconds}s)={average:.6g} "
        f"in [{lo}, {hi}]: {ok} (n={len(values)})",
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

    data = await buffer.window_query(
        subject=subject,
        as_of=as_of,
        window_seconds=assertion.window_seconds,
        metric_path=assertion.metric,
    )
    values = _extract_values(data)
    if not values:
        return _CheckOutcome(
            None,
            f"No samples for metric {assertion.metric!r} in the last "
            f"{assertion.window_seconds}s; cannot check peak.",
        )

    threshold = float(assertion.value)
    peak = max(values)
    ok = peak <= threshold
    return _CheckOutcome(
        ok,
        f"peak({assertion.metric}, {assertion.window_seconds}s)={peak:.6g} "
        f"<= {threshold}: {ok} (n={len(values)})",
    )


_STATEFUL_HANDLERS = {
    "must_average_within": _check_must_average_within,
    "must_not_exceed_in_window": _check_must_not_exceed_in_window,
}


# ---- SymbolicVerifier ---------------------------------------------------------


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

    Stateless: instances can be reused across requests. No I/O.

    Stateful predicates (window queries, time-bounded checks) require the
    telemetry buffer and will be added in a follow-up. Until then, an
    assertion that uses an unknown or stateful predicate yields
    ``UNVERIFIABLE`` for the whole envelope.
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

    def verify(
        self,
        assertions: Sequence[FormalizableAssertion],
        *,
        llm_verdict: V3Verdict,
        measurement: Optional[Mapping[str, Any]] = None,
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
