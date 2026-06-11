"""Pure metric computation over eval case results. No I/O."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CaseResult:
    """One golden case joined with what the evaluator actually produced."""

    case_id: str
    category: str
    expected_verdict: str
    predicted_verdict: str
    expected_assertions: List[Dict[str, Any]]
    emitted_assertions: List[Dict[str, Any]]
    verifier_status: str
    checked_assertions: int
    notes: str = ""

    @property
    def verdict_correct(self) -> bool:
        return self.expected_verdict == self.predicted_verdict

    @property
    def assertions_correct(self) -> Optional[bool]:
        """True/False for cases with expected assertions; None otherwise.

        Correct means: every expected assertion has an emitted assertion
        with the same ``obligation_id`` and the same ``satisfied`` flag.
        """
        if not self.expected_assertions:
            return None
        emitted = {(a.get("obligation_id"), a.get("satisfied")) for a in self.emitted_assertions}
        return all((e["obligation_id"], e["satisfied"]) in emitted for e in self.expected_assertions)


def _safe_div(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


@dataclass
class EvalMetrics:
    """Aggregated metrics; renderable straight into the report."""

    n_cases: int = 0
    verdict_accuracy: Optional[float] = None
    flag_recall: Optional[float] = None
    flag_precision: Optional[float] = None
    breaches_silently_cleared: int = 0
    unmapped_recall: Optional[float] = None
    assertion_accuracy: Optional[float] = None
    verifier_agreement_rate: Optional[float] = None
    confusion: Dict[str, Dict[str, int]] = field(default_factory=dict)
    per_category_accuracy: Dict[str, Optional[float]] = field(default_factory=dict)
    mismatches: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_cases": self.n_cases,
            "verdict_accuracy": self.verdict_accuracy,
            "flag_recall": self.flag_recall,
            "flag_precision": self.flag_precision,
            "breaches_silently_cleared": self.breaches_silently_cleared,
            "unmapped_recall": self.unmapped_recall,
            "assertion_accuracy": self.assertion_accuracy,
            "verifier_agreement_rate": self.verifier_agreement_rate,
            "confusion": self.confusion,
            "per_category_accuracy": self.per_category_accuracy,
            "mismatches": self.mismatches,
        }


def compute_metrics(results: List[CaseResult]) -> EvalMetrics:
    m = EvalMetrics(n_cases=len(results))
    if not results:
        return m

    correct = [r for r in results if r.verdict_correct]
    m.verdict_accuracy = _safe_div(len(correct), len(results))

    # FLAG recall: of all true breaches, how many did we catch? The
    # regulator's number — a missed breach is the expensive failure.
    expected_flags = [r for r in results if r.expected_verdict == "FLAG"]
    caught = [r for r in expected_flags if r.predicted_verdict == "FLAG"]
    m.flag_recall = _safe_div(len(caught), len(expected_flags))

    # FLAG precision: of everything we flagged, how much was a real breach?
    predicted_flags = [r for r in results if r.predicted_verdict == "FLAG"]
    true_flags = [r for r in predicted_flags if r.expected_verdict == "FLAG"]
    m.flag_precision = _safe_div(len(true_flags), len(predicted_flags))

    # The catastrophic failure mode: a true breach the system waved
    # through as CLEAR. A breach routed to DISCRETIONARY is safe-but-
    # costly (human review); a breach CLEARed is a compliance miss.
    m.breaches_silently_cleared = len([r for r in expected_flags if r.predicted_verdict == "CLEAR"])

    expected_unmapped = [r for r in results if r.expected_verdict == "NULL_UNMAPPED"]
    got_unmapped = [r for r in expected_unmapped if r.predicted_verdict == "NULL_UNMAPPED"]
    m.unmapped_recall = _safe_div(len(got_unmapped), len(expected_unmapped))

    with_assertions = [r for r in results if r.assertions_correct is not None]
    m.assertion_accuracy = _safe_div(
        len([r for r in with_assertions if r.assertions_correct]), len(with_assertions)
    )

    checked = [r for r in results if r.checked_assertions > 0]
    agreed = [r for r in checked if r.verifier_status == "AGREED"]
    m.verifier_agreement_rate = _safe_div(len(agreed), len(checked))

    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r.expected_verdict][r.predicted_verdict] += 1
    m.confusion = {k: dict(v) for k, v in confusion.items()}

    by_cat: Dict[str, List[CaseResult]] = defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)
    m.per_category_accuracy = {
        cat: _safe_div(len([r for r in rs if r.verdict_correct]), len(rs))
        for cat, rs in sorted(by_cat.items())
    }

    m.mismatches = [
        {
            "case_id": r.case_id,
            "expected": r.expected_verdict,
            "predicted": r.predicted_verdict,
            "verifier_status": r.verifier_status,
            "notes": r.notes,
        }
        for r in results
        if not r.verdict_correct
    ]
    return m
