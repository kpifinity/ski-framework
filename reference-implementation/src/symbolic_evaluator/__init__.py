"""Symbolic Evaluator (Track 1) - deterministic predicate evaluation.

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

# Explicit `name as name` re-export so mypy's strict --no-implicit-reexport
# is satisfied (PEP 484). Verdict is imported from the upstream ski_model
# package inside evaluator.py with a local-Enum fallback, so the underlying
# source module is conditional; the alias pattern keeps the public surface
# stable regardless.
from .evaluator import SymbolicDecision as SymbolicDecision
from .evaluator import SymbolicEvaluator as SymbolicEvaluator
from .evaluator import Verdict as Verdict

__all__ = ["SymbolicDecision", "SymbolicEvaluator", "Verdict"]
