"""Symbolic Evaluator (v0.2).

Deterministic predicate evaluator for SKI Track 1 rules. See package
``__init__.py`` for the supported predicate grammar.

v0.2 adds stateful predicates that consult the telemetry buffer. The
evaluator is now async because the buffer is async; pre-v0.2 callers
that used the synchronous evaluate() should use ``evaluate_sync()`` for
backward compatibility (rejects stateful predicates with DISCRETIONARY).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Protocol

# Use the verdict taxonomy from the SKI Model v3 envelope. Falls back to a
# local definition if symbolic_evaluator is imported standalone (e.g. in
# unit tests that do not load the runtime package).
#
# ``V3Verdict`` is imported under its native name so mypy treats it as an
# explicit re-export (PEP 484, --no-implicit-reexport). The module-level
# ``Verdict = V3Verdict`` alias below is a true module attribute that
# ``__init__.py`` can re-export. The rewrite to v3 naming throughout the
# symbolic_evaluator package happens in PR 10c.
try:
    from ski_model.v3.envelope import V3Verdict as V3Verdict
except ImportError:  # pragma: no cover
    from enum import Enum

    class V3Verdict(str, Enum):  # type: ignore
        CLEAR = "CLEAR"
        FLAG = "FLAG"
        NULL_UNMAPPED = "NULL_UNMAPPED"
        NULL_STALE = "NULL_STALE"
        DISCRETIONARY = "DISCRETIONARY"


Verdict = V3Verdict


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------


@dataclass
class SymbolicDecision:
    verdict: Verdict
    reasoning: str


class BufferLike(Protocol):
    """Minimal subset of TelemetryBuffer the evaluator depends on.

    Defining it as a Protocol keeps the evaluator import-light (no hard
    dependency on the telemetry_buffer package or SQLAlchemy in unit
    tests).
    """

    async def window_query(
        self, *, subject: str, as_of: datetime, window_seconds: int, metric_path: Optional[str] = None
    ) -> Any: ...
    async def last_record_ts(self, *, subject: str, as_of: datetime) -> Optional[datetime]: ...
    async def has_fresh_sample(self, *, subject: str, as_of: datetime, within_seconds: int) -> bool: ...


# --------------------------------------------------------------------------
# Operator sets
# --------------------------------------------------------------------------

_NUMERIC_OPS = {"lte", "gte", "lt", "gt", "eq", "range", "between"}
_SET_OPS = {"in_set", "not_in_set"}
_WINDOW_OPS = {"window_count", "window_sum", "window_avg"}
_TEMPORAL_OPS = {"since_last", "debounce"}
_STATEFUL_OPS = _WINDOW_OPS | _TEMPORAL_OPS

# Mapping of comparison short-code to a comparator function.
_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "lte": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "eq": lambda a, b: a == b,
}
_COMPARATOR_SYMBOL = {"lte": "≤", "lt": "<", "gte": "≥", "gt": ">", "eq": "=="}


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


class SymbolicEvaluator:
    """Deterministic predicate evaluator for SKI Track 1 rules.

    v0.2: stateful predicates (``window_*``, ``since_last``, ``debounce``,
    and the ``requires_recent_within_seconds`` rule property) are
    supported when an async ``BufferLike`` is passed.
    """

    async def aevaluate(
        self,
        rule: dict[str, Any],
        telemetry: dict[str, Any],
        *,
        buffer: Optional[BufferLike] = None,
        as_of: Optional[datetime] = None,
    ) -> SymbolicDecision:
        """Async evaluation. Use this from the SKI Model server."""
        return await _evaluate_async(rule, telemetry, buffer, as_of)

    def evaluate(
        self,
        rule: dict[str, Any],
        telemetry: dict[str, Any],
    ) -> SymbolicDecision:
        """Synchronous evaluation for stateless predicates only.

        Backwards-compat shim for v0.1 callers and unit tests. Stateful
        predicates return DISCRETIONARY with a clear reason when no
        buffer is available.
        """
        predicate = rule.get("predicate")
        if isinstance(predicate, dict) and predicate.get("operator") in _STATEFUL_OPS:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Rule {rule.get('id')!r} uses stateful operator "
                    f"{predicate.get('operator')!r}; sync evaluation cannot consult the "
                    "telemetry buffer. Use evaluator.aevaluate(..., buffer=...) instead."
                ),
            )
        if (
            isinstance(rule.get("predicate"), dict)
            and rule["predicate"].get("requires_recent_within_seconds") is not None
        ):
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Rule {rule.get('id')!r} requires a fresh sample check but no buffer "
                    "is available in sync evaluation."
                ),
            )
        return _evaluate_stateless(rule, telemetry)


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


async def _evaluate_async(
    rule: dict[str, Any],
    telemetry: dict[str, Any],
    buffer: Optional[BufferLike],
    as_of: Optional[datetime],
) -> SymbolicDecision:
    predicate = rule.get("predicate")
    if not isinstance(predicate, dict):
        return _no_predicate(rule)

    op = predicate.get("operator")
    rule_id = rule.get("id", "<unknown>")
    subject = telemetry.get("subject", "")
    effective_as_of = as_of or _parse_iso(telemetry.get("timestamp"))

    # 1. Freshness gate (NULL_STALE) — applies regardless of operator.
    fresh_seconds = predicate.get("requires_recent_within_seconds")
    if fresh_seconds is not None:
        if buffer is None or effective_as_of is None:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Rule {rule_id}: requires_recent_within_seconds set but no buffer / "
                    "no telemetry timestamp available."
                ),
            )
        try:
            is_fresh = await buffer.has_fresh_sample(
                subject=subject, as_of=effective_as_of, within_seconds=int(fresh_seconds)
            )
        except Exception as exc:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=f"Rule {rule_id}: buffer freshness check failed: {exc!r}",
            )
        if not is_fresh:
            return SymbolicDecision(
                verdict=Verdict.NULL_STALE,
                reasoning=(
                    f"Rule {rule_id}: no telemetry for subject {subject!r} within the "
                    f"last {fresh_seconds}s of {effective_as_of.isoformat()}."
                ),
            )

    # 2. Stateful operators.
    if op in _STATEFUL_OPS:
        if buffer is None or effective_as_of is None:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Rule {rule_id}: operator {op!r} requires a buffer and a telemetry "
                    "timestamp; one is missing."
                ),
            )
        try:
            return await _evaluate_stateful(predicate, op, rule_id, subject, effective_as_of, buffer)
        except Exception as exc:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=f"Rule {rule_id}: stateful predicate evaluation failed: {exc!r}",
            )

    # 3. Stateless operators.
    return _evaluate_stateless(rule, telemetry)


def _evaluate_stateless(rule: dict[str, Any], telemetry: dict[str, Any]) -> SymbolicDecision:
    predicate = rule.get("predicate")
    if not isinstance(predicate, dict):
        return _no_predicate(rule)

    op = predicate.get("operator")
    metric_path = predicate.get("metric", "")
    unit_expected = predicate.get("unit")
    observed = _lookup(telemetry.get("measurement", {}), metric_path)
    rule_id = rule.get("id", "<unknown>")

    if observed is None:
        return SymbolicDecision(
            verdict=Verdict.NULL_UNMAPPED,
            reasoning=(f"Rule {rule_id!r}: metric {metric_path!r} not present in telemetry."),
        )

    observed_value, observed_unit = _value_and_unit(observed)
    if unit_expected and observed_unit and observed_unit != unit_expected:
        return SymbolicDecision(
            verdict=Verdict.DISCRETIONARY,
            reasoning=(
                f"Unit mismatch on rule {rule_id!r}: predicate expects {unit_expected!r}, "
                f"telemetry has {observed_unit!r}. No implicit conversion performed."
            ),
        )

    try:
        if op in _NUMERIC_OPS:
            return _eval_numeric(op, predicate, observed_value, rule_id, metric_path)
        if op in _SET_OPS:
            return _eval_set(op, predicate, observed_value, rule_id, metric_path)
        if op == "exists":
            return SymbolicDecision(
                verdict=Verdict.CLEAR,
                reasoning=f"Rule {rule_id}: 'exists' predicate satisfied for {metric_path!r}.",
            )
    except (TypeError, ValueError) as exc:
        return SymbolicDecision(
            verdict=Verdict.DISCRETIONARY,
            reasoning=(
                f"Rule {rule_id}: predicate evaluation raised {exc!r}. "
                "Routed to human reviewer rather than guessing."
            ),
        )

    return SymbolicDecision(
        verdict=Verdict.DISCRETIONARY,
        reasoning=f"Rule {rule_id}: unknown predicate operator {op!r}.",
    )


async def _evaluate_stateful(
    predicate: dict[str, Any],
    op: str,
    rule_id: str,
    subject: str,
    as_of: datetime,
    buffer: BufferLike,
) -> SymbolicDecision:
    if op in _WINDOW_OPS:
        seconds = int(predicate["seconds"])
        cmp = predicate.get("op", "lte")
        target = float(predicate["value"])
        metric_path = predicate.get("metric")
        result = await buffer.window_query(
            subject=subject,
            as_of=as_of,
            window_seconds=seconds,
            metric_path=metric_path,
        )

        if op == "window_count":
            return _compare(rule_id, cmp, float(result.count), target, label=f"count over {seconds}s")

        if op == "window_sum":
            if result.sum_value is None:
                return SymbolicDecision(
                    verdict=Verdict.NULL_UNMAPPED,
                    reasoning=(
                        f"Rule {rule_id}: window_sum found no numeric values at "
                        f"{metric_path!r} for {subject!r} in the last {seconds}s."
                    ),
                )
            return _compare(
                rule_id, cmp, result.sum_value, target, label=f"sum({metric_path}) over {seconds}s"
            )

        if op == "window_avg":
            if result.avg_value is None:
                return SymbolicDecision(
                    verdict=Verdict.NULL_UNMAPPED,
                    reasoning=(
                        f"Rule {rule_id}: window_avg found no numeric values at "
                        f"{metric_path!r} for {subject!r} in the last {seconds}s."
                    ),
                )
            return _compare(
                rule_id, cmp, result.avg_value, target, label=f"avg({metric_path}) over {seconds}s"
            )

    if op == "since_last":
        cmp = predicate.get("op", "gte")
        value_seconds = float(predicate["value_seconds"])
        last_ts = await buffer.last_record_ts(subject=subject, as_of=as_of)
        if last_ts is None:
            return SymbolicDecision(
                verdict=Verdict.NULL_UNMAPPED,
                reasoning=(
                    f"Rule {rule_id}: since_last needs a prior record for {subject!r}; none found in buffer."
                ),
            )
        elapsed = (as_of - last_ts).total_seconds()
        return _compare(rule_id, cmp, elapsed, value_seconds, label=f"since_last({subject})")

    if op == "debounce":
        seconds = int(predicate["seconds"])
        last_ts = await buffer.last_record_ts(subject=subject, as_of=as_of)
        if last_ts is None or (as_of - last_ts).total_seconds() > seconds:
            # No recent record => not debounced, allow downstream to evaluate.
            return SymbolicDecision(
                verdict=Verdict.CLEAR,
                reasoning=(
                    f"Rule {rule_id}: debounce({seconds}s) satisfied — no prior record for "
                    f"{subject!r} in the window."
                ),
            )
        return SymbolicDecision(
            verdict=Verdict.DISCRETIONARY,
            reasoning=(
                f"Rule {rule_id}: debounce({seconds}s) — duplicate event for {subject!r} "
                f"at {as_of.isoformat()} (prior at {last_ts.isoformat()}). "
                "Routed to human reviewer."
            ),
        )

    return SymbolicDecision(
        verdict=Verdict.DISCRETIONARY,
        reasoning=f"Rule {rule_id}: unknown stateful operator {op!r}.",
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _no_predicate(rule: dict[str, Any]) -> SymbolicDecision:
    return SymbolicDecision(
        verdict=Verdict.DISCRETIONARY,
        reasoning=(
            f"Rule {rule.get('id')!r} is declared track=symbolic but has no structured "
            "'predicate'. Refusing to guess; route to human reviewer."
        ),
    )


def _compare(rule_id: str, cmp: str, observed: float, target: float, *, label: str) -> SymbolicDecision:
    if cmp not in _COMPARATORS:
        return SymbolicDecision(
            verdict=Verdict.DISCRETIONARY,
            reasoning=f"Rule {rule_id}: unknown comparison {cmp!r} on {label}.",
        )
    ok = _COMPARATORS[cmp](observed, target)
    sym = _COMPARATOR_SYMBOL[cmp]
    detail = f"{label}: {observed} {sym if ok else _negate(sym)} {target}"
    if ok:
        return SymbolicDecision(verdict=Verdict.CLEAR, reasoning=f"Rule {rule_id} satisfied: {detail}")
    return SymbolicDecision(verdict=Verdict.FLAG, reasoning=f"Rule {rule_id} BREACHED: {detail}")


def _negate(sym: str) -> str:
    return {"≤": ">", "<": "≥", "≥": "<", ">": "≤", "==": "!="}.get(sym, "!=")


def _lookup(obj: Any, dotted: str) -> Any:
    if not dotted:
        return obj
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _value_and_unit(observed: Any) -> tuple[Any, Optional[str]]:
    if isinstance(observed, dict) and "value" in observed:
        return observed.get("value"), observed.get("unit")
    return observed, None


def _eval_numeric(
    op: str,
    predicate: dict[str, Any],
    observed: Any,
    rule_id: str,
    metric_path: str,
) -> SymbolicDecision:
    obs = float(observed)
    if op == "lte":
        limit = float(predicate["value"])
        ok = obs <= limit
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'≤' if ok else '>'} {limit}")
    if op == "gte":
        limit = float(predicate["value"])
        ok = obs >= limit
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'≥' if ok else '<'} {limit}")
    if op == "lt":
        limit = float(predicate["value"])
        ok = obs < limit
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'<' if ok else '≥'} {limit}")
    if op == "gt":
        limit = float(predicate["value"])
        ok = obs > limit
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'>' if ok else '≤'} {limit}")
    if op == "eq":
        target = float(predicate["value"])
        ok = obs == target
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'==' if ok else '!='} {target}")
    if op in ("range", "between"):
        lo = float(predicate["min"])
        hi = float(predicate["max"])
        ok = lo <= obs <= hi
        return _bool_to_decision(ok, rule_id, f"{metric_path}={obs} {'in' if ok else 'outside'} [{lo}, {hi}]")
    raise ValueError(f"Unknown numeric operator: {op}")


def _eval_set(
    op: str,
    predicate: dict[str, Any],
    observed: Any,
    rule_id: str,
    metric_path: str,
) -> SymbolicDecision:
    allowed = predicate.get("value") or []
    if not isinstance(allowed, list):
        raise TypeError("'in_set' / 'not_in_set' require a list 'value'.")
    in_set = observed in allowed
    if op == "in_set":
        return _bool_to_decision(
            in_set, rule_id, f"{metric_path}={observed} {'∈' if in_set else '∉'} {allowed}"
        )
    return _bool_to_decision(
        not in_set, rule_id, f"{metric_path}={observed} {'∉' if not in_set else '∈'} {allowed}"
    )


def _bool_to_decision(ok: bool, rule_id: str, detail: str) -> SymbolicDecision:
    if ok:
        return SymbolicDecision(verdict=Verdict.CLEAR, reasoning=f"Rule {rule_id} satisfied: {detail}")
    return SymbolicDecision(verdict=Verdict.FLAG, reasoning=f"Rule {rule_id} BREACHED: {detail}")


def _parse_iso(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Accept "...Z" suffix for UTC.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
