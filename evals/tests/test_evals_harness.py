"""Harness validation: the FakeLLM baseline is a pinned contract.

FakeLLM deliberately mishandles ``must_be_at_least`` (it defaults the
assertion to satisfied=True and verdict=CLEAR regardless of the observed
value). These tests pin the exact consequences so the suite doubles as a
regression net over the whole evaluation pipeline.

With verifier-side satisfied normalisation the pipeline now catches the
blind spots differently than it did before normalisation was added:

* The verifier corrects FakeLLM's wrong ``satisfied=True`` -> ``False``
  for the two must_be_at_least cases, so ``assertion_accuracy`` rises to
  100% (was 94.7% before normalisation).
* After normalisation ``averify`` sees ``satisfied=False`` alongside
  verdict=CLEAR -- a verdict/assertion inconsistency -- and records
  ``NEURO_SYMBOLIC_DIVERGENCE`` (was ``LLM_CONTRADICTION`` before).
* Tier-2 policy still routes NEURO_SYMBOLIC_DIVERGENCE to DISCRETIONARY
  (same outcome as before -- no safety regression).
* Zero silent CLEARs: the invariant holds under the new flow.

If FakeLLM, the evaluator, the verifier, or the scoping logic changes
behaviour, these pins move -- deliberately, in a reviewed diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.report import render_markdown
from evals.runner import run_eval

DATASET = Path(__file__).resolve().parent.parent / "datasets" / "energy"
BLIND_SPOTS = {"flag-flow-just-under", "flag-flow-zero"}


@pytest.fixture(scope="module")
def fake_run():
    import asyncio

    from ski_model.v3.evaluator import FakeLLM

    return asyncio.run(run_eval(dataset_dir=DATASET, backend=FakeLLM(), seed=0))


def test_dataset_shape(fake_run) -> None:
    assert fake_run.metrics.n_cases == 50
    expected = {"CLEAR": 20, "FLAG": 18, "NULL_UNMAPPED": 12}
    totals = {k: sum(v.values()) for k, v in fake_run.metrics.confusion.items()}
    assert totals == expected


def test_fakellm_pinned_baseline(fake_run) -> None:
    m = fake_run.metrics
    assert m.verdict_accuracy == pytest.approx(48 / 50)
    assert m.flag_recall == pytest.approx(16 / 18, abs=1e-4)
    assert m.flag_precision == 1.0
    assert m.unmapped_recall == 1.0
    assert m.assertion_accuracy == 1.0
    assert m.verifier_agreement_rate == pytest.approx(36 / 38, abs=1e-4)


def test_no_breach_is_silently_cleared(fake_run) -> None:
    """The catastrophic failure mode must not occur even with a flawed model."""
    assert fake_run.metrics.breaches_silently_cleared == 0


def test_verifier_catches_the_blind_spots(fake_run) -> None:
    mismatched = {x["case_id"] for x in fake_run.metrics.mismatches}
    assert mismatched == BLIND_SPOTS
    by_id = {r.case_id: r for r in fake_run.results}
    for case_id in BLIND_SPOTS:
        r = by_id[case_id]
        assert r.verifier_status == "NEURO_SYMBOLIC_DIVERGENCE"
        assert r.predicted_verdict == "DISCRETIONARY"


def test_scoping_categories_are_perfect(fake_run) -> None:
    cats = fake_run.metrics.per_category_accuracy
    assert cats["jurisdiction"] == 1.0
    assert cats["effective-date"] == 1.0


def test_report_renders(fake_run) -> None:
    md = render_markdown(fake_run)
    assert "FLAG recall" in md
    assert "Breaches silently CLEARed | **0**" in md
    assert "sha256:" in md
