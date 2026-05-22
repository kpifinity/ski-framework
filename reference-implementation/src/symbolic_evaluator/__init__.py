"""Symbolic Evaluator (Track 1) — deterministic predicate evaluation.

The Symbolic Evaluator is the deterministic-by-construction half of the SKI
Framework v2.1 hybrid runtime. It evaluates structured predicates of the form

    {"operator": "lte" | "gte" | "lt" | "gt" | "eq" | "range" | "in_set" |
                 "not_in_set" | "between" | "exists",
     "metric": "<dotted.path.into.measurement>",
     "value": <number | string | list>,
     "unit": "<unit string, optional>"}

against a telemetry record. No LLM is involved; the result of evaluation is
purely a function of the predicate AST and the input record.

Track 1 rules MUST be expressible as one of the supported predicates. Rules
that require natural-language interpretation must be declared `track: "llm"`
and are routed to the SKI Model wrapper instead.
"""

from .evaluator import SymbolicDecision, SymbolicEvaluator

__all__ = ["SymbolicEvaluator", "SymbolicDecision"]
