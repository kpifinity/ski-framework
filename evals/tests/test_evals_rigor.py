"""Eval rigor: the generated datasets, the Wilson intervals, the cross-run summary, and the FakeLLM pins.

The finance and manufacturing datasets are generated (``evals/datasets/generate.py``);
these tests keep the committed files in step with the generator, check every
label against the predicate definitions independently, and pin the FakeLLM
baseline on all three sectors, whose only misses must be routed to human
review, never CLEARed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evals.datasets import generate
from evals.runner import run_eval
from evals.summary import load_runs, render, summarize, wilson

DATASETS = Path(__file__).resolve().parent.parent / "datasets"
SECTORS = ("energy", "finance", "manufacturing")


def _cases(sector: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATASETS / sector / "cases.jsonl").read_text().splitlines() if line]


def test_generated_datasets_are_current() -> None:
    assert generate.main(["--check"]) == 0, "run: python -m evals.datasets.generate"


def test_at_least_300_cases_across_three_sectors() -> None:
    counts = {s: len(_cases(s)) for s in SECTORS}
    assert sum(counts.values()) >= 300, counts
    assert all(n >= 50 for n in counts.values()), counts


def _holds(kind: str, x: float, v: Any) -> bool:
    if kind == "must_not_exceed":
        return x <= v
    if kind == "must_be_at_least":
        return x >= v
    assert kind == "must_be_within"
    return bool(v[0] <= x <= v[1])


@pytest.mark.parametrize("sector", ["finance", "manufacturing"])
def test_generated_labels_follow_the_predicates(sector: str) -> None:
    """Each CLEAR / FLAG label agrees with the obligation's predicate applied to the reading."""
    kg = json.loads((DATASETS / sector / "eval-kg.json").read_text())
    obligations = {o["id"]: o for o in kg["nodes"]["obligations"]}
    for case in _cases(sector):
        verdict = case["expected"]["verdict"]
        if verdict not in {"CLEAR", "FLAG"}:
            assert case["expected"]["assertions"] == []
            continue
        outcomes = []
        for a in case["expected"]["assertions"]:
            ob = obligations[a["obligation_id"]]
            holds = _holds(ob["obligation_type"], case["measurement"][ob["metric"]], ob["value"])
            assert a["satisfied"] is holds, case["case_id"]
            outcomes.append(holds)
        assert verdict == ("CLEAR" if all(outcomes) else "FLAG"), case["case_id"]


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (10, 10, 0.7225, 1.0), (81, 263, 0.2553, 0.3662)],
)
def test_wilson_interval(k: int, n: int, lo: float, hi: float) -> None:
    got = wilson(k, n)
    assert got == pytest.approx((lo, hi), abs=1e-4)


def test_wilson_empty_is_uninformative() -> None:
    assert wilson(0, 0) == (0.0, 1.0)


@pytest.fixture(scope="module")
def fake_runs() -> dict[str, Any]:
    from ski_model.v3.evaluator import FakeLLM

    return {s: asyncio.run(run_eval(dataset_dir=DATASETS / s, backend=FakeLLM(), seed=0)) for s in SECTORS}


@pytest.mark.parametrize(("sector", "correct", "total"), [("finance", 112, 129), ("manufacturing", 115, 128)])
def test_fakellm_pinned_baseline(fake_runs: dict[str, Any], sector: str, correct: int, total: int) -> None:
    m = fake_runs[sector].metrics
    assert m.n_cases == total
    assert m.verdict_accuracy == pytest.approx(correct / total, abs=1e-4)
    assert m.flag_precision == 1.0
    assert m.unmapped_recall == 1.0
    assert m.stale_recall == 1.0


@pytest.mark.parametrize("sector", SECTORS)
def test_every_fakellm_miss_goes_to_human_review(fake_runs: dict[str, Any], sector: str) -> None:
    """FakeLLM's blind spots (must_be_at_least, several metrics in one record) are caught, never CLEARed."""
    m = fake_runs[sector].metrics
    assert m.breaches_silently_cleared == 0
    assert m.silent_sensors_cleared == 0
    assert {x["predicted"] for x in m.mismatches} <= {"DISCRETIONARY"}


def test_summary_across_runs(tmp_path: Path, fake_runs: dict[str, Any]) -> None:
    from evals.report import write_report

    for seed in (0, 1):
        for run in fake_runs.values():
            run.provenance["decoder_seed"] = seed
            write_report(run, tmp_path / f"seed-{seed}")
    for run in fake_runs.values():
        run.provenance["decoder_seed"] = 0
    summary = summarize(load_runs(tmp_path))
    (model,) = summary["models"].values()
    pooled = model["seeds"]["0"]["pooled"]
    assert pooled["n_cases"] == sum(len(_cases(s)) for s in SECTORS)
    assert pooled["verdict_accuracy"]["k"] == sum(
        1 for r in fake_runs.values() for c in r.results if c.verdict_correct
    )
    lo, hi = pooled["verdict_accuracy"]["ci95"]
    assert lo < pooled["verdict_accuracy"]["rate"] < hi
    assert model["seed_stability"]["rate"] == 1.0
    text = render(summary)
    assert "Wilson 95%" in text and "seed 1" in text and "**Breaches silently CLEARed**" in text
