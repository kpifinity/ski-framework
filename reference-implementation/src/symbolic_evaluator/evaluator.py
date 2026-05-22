"""Symbolic Evaluator implementation.

Deterministic predicate evaluator for SKI Track 1 rules. See package
__init__.py for the supported predicate grammar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Use the verdict taxonomy from the SKI Model package. Falls back to local
# definition if the symbolic_evaluator package is imported standalone.
try:
    from ski_model.verdicts import Verdict  # type: ignore
except ImportError:  # pragma: no cover

    from enum import Enum

    class Verdict(str, Enum):  # type: ignore
        CLEAR = "CLEAR"
        FLAG = "FLAG"
        NULL_UNMAPPED = "NULL_UNMAPPED"
        NULL_STALE = "NULL_STALE"
        DISCRETIONARY = "DISCRETIONARY"


@dataclass
class SymbolicDecision:
    verdict: Verdict
    reasoning: str


_NUMERIC_OPS = {"lte", "gte", "lt", "gt", "eq", "range", "between"}
_SET_OPS = {"in_set", "not_in_set"}


class SymbolicEvaluator:
    """Deterministic predicate evaluator for SKI Track 1 rules."""

    def evaluate(self, rule: dict[str, Any], telemetry: dict[str, Any]) -> SymbolicDecision:
        predicate = rule.get("predicate")
        if not isinstance(predicate, dict):
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Rule {rule.get('id')!r} is declared track=symbolic but "
                    "has no structured 'predicate'. Refusing to guess; "
                    "route to human reviewer."
                ),
            )

        op = predicate.get("operator")
        metric_path = predicate.get("metric", "")
        unit_expected = predicate.get("unit")
        observed = _lookup(telemetry.get("measurement", {}), metric_path)

        # Optional time-window check for stateful predicates.
        if predicate.get("requires_recent_within_seconds") is not None:
            freshness_check = _check_freshness(predicate, telemetry)
            if freshness_check is not None:
                return freshness_check

        if observed is None:
            return SymbolicDecision(
                verdict=Verdict.NULL_UNMAPPED,
                reasoning=(
                    f"Rule {rule.get('id')!r} predicate requires metric "
                    f"{metric_path!r} which is not present in telemetry."
                ),
            )

        # Unit check — fail loudly rather than silently coerce.
        observed_value, observed_unit = _value_and_unit(observed)
        if unit_expected and observed_unit and observed_unit != unit_expected:
            return SymbolicDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=(
                    f"Unit mismatch on rule {rule.get('id')!r}: predicate "
                    f"expects {unit_expected!r}, telemetry has {observed_unit!r}. "
                    "No implicit conversion performed."
                ),
            )

        rule_id = rule.get("id", "<unknown>")
        try:
            if op in _NUMERIC_OPS:
                return _eval_numeric(op, predicate, observed_value, rule_id, metric_path)
            if op in _SET_OPS:
                return _eval_set(op, predicate, observed_value, rule_id, metric_path)
            if op == "exists":
                # Already past the None check above.
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


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


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
    """Telemetry metrics may be scalars or {value, unit} objects."""
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
        return _bool_to_decision(
            ok, rule_id, f"{metric_path}={obs} {'in' if ok else 'outside'} [{lo}, {hi}]"
        )
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


def _check_freshness(predicate: dict[str, Any], telemetry: dict[str, Any]) -> Optional[SymbolicDecision]:
    """Stateful evaluation hook (B4.4).

    For the v0.1.0-alpha reference implementation this is a placeholder.
    A complete implementation would consult the telemetry buffer to verify
    that a measurement at least N seconds fresh exists for the metric. If
    not, returns NULL_STALE.
    """
    # TODO(stateful): wire to telemetry buffer. For now we never return STALE.
    return None
