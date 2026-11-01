"""Scripted language-model answers: the JSON object spec §5.2 binds the model's output to."""

from __future__ import annotations

from typing import Any, Optional

from .prepare import PH_OBLIGATION, PH_RANGE, SO2_LIMIT, SO2_OBLIGATION, VERSION

VERDICTS = {"CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY"}


def citation(node_id: str) -> dict[str, Any]:
    return {"node_id": node_id, "version": VERSION, "role": "obligation"}


def so2(observed: Any, satisfied: bool) -> dict[str, Any]:
    return {
        "predicate": "must_not_exceed",
        "metric": "so2_ppm",
        "value": SO2_LIMIT,
        "observed": observed,
        "satisfied": satisfied,
        "obligation_id": SO2_OBLIGATION,
    }


def ph(observed: Any, satisfied: bool) -> dict[str, Any]:
    return {
        "predicate": "must_be_within",
        "metric": "ph",
        "value": PH_RANGE,
        "observed": observed,
        "satisfied": satisfied,
        "obligation_id": PH_OBLIGATION,
    }


def answer(
    verdict: str,
    assertions: list[dict[str, Any]],
    citations: Optional[list[str]] = None,
    **extra: Any,
) -> dict[str, Any]:
    cited = citations if citations is not None else sorted({a["obligation_id"] for a in assertions})
    return {
        "verdict": verdict,
        "reasoning": "Scripted answer from the black-box conformance suite.",
        "kg_citations": [citation(c) for c in cited],
        "formalizable_assertions": assertions,
        **extra,
    }
