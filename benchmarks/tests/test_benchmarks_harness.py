"""Unit tests for the benchmark harness — stats math and the pipeline path."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.report import to_json, to_markdown
from benchmarks.runner import REPO_ROOT, load_workload, run_pipeline
from benchmarks.stats import percentile, summarize

DATASET = REPO_ROOT / "evals" / "datasets" / "energy"


class TestStats:
    def test_percentile_nearest_rank(self) -> None:
        values = [float(v) for v in range(1, 101)]  # 1..100
        assert percentile(values, 50) == 50.0
        assert percentile(values, 99) == 99.0
        assert percentile(values, 100) == 100.0

    def test_percentile_single_sample(self) -> None:
        assert percentile([7.0], 99) == 7.0

    def test_percentile_rejects_empty_and_bad_q(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 50)
        with pytest.raises(ValueError):
            percentile([1.0], 101)

    def test_summarize_basic(self) -> None:
        s = summarize([1.0, 2.0, 3.0, 4.0])
        assert s.n == 4
        assert s.min_ms == 1.0
        assert s.max_ms == 4.0
        assert s.p50_ms == 2.0
        assert s.mean_ms == pytest.approx(2.5)
        assert s.throughput_per_s == pytest.approx(400.0)

    def test_summarize_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            summarize([])


class TestPipelineBenchmark:
    def test_small_run_produces_sane_report(self) -> None:
        from ski_model.v3.evaluator import FakeLLM

        run = run_pipeline(dataset_dir=DATASET, backend=FakeLLM(), n=20, warmup=2, seed=42)
        assert run.mode == "pipeline"
        assert set(run.stages) == {"scope_to", "evaluate_verify_sign", "framework_total"}
        assert run.stages["framework_total"].n == 20
        # framework total must dominate its parts
        assert run.stages["framework_total"].mean_ms >= run.stages["evaluate_verify_sign"].mean_ms
        assert sum(run.verdict_counts.values()) == 20
        assert run.provenance["transcript_signing"] is True
        assert run.provenance["kg_file_hash"].startswith("sha256:")

    def test_workload_loads_golden_dataset(self) -> None:
        kg, cases, hashes = load_workload(DATASET)
        assert len(cases) >= 50
        assert kg.rules
        assert hashes["cases_file_hash"].startswith("sha256:")

    def test_reports_render(self) -> None:
        from ski_model.v3.evaluator import FakeLLM

        run = run_pipeline(dataset_dir=DATASET, backend=FakeLLM(), n=5, warmup=0, seed=42)
        md = to_markdown([run])
        assert "Framework total" in md and "p99" in md
        js = to_json([run])
        assert '"framework_total"' in js


class TestCLI:
    def test_budget_gate_passes_generously(self) -> None:
        from benchmarks.run import main

        # 5 s budget: this is a correctness test of the gate wiring, not a
        # performance assertion — those live in CI with a real budget.
        assert (
            main(["--mode", "pipeline", "--n", "10", "--warmup", "0", "--max-framework-p99-ms", "5000"]) == 0
        )

    def test_budget_gate_fails_when_exceeded(self) -> None:
        from benchmarks.run import main

        assert (
            main(["--mode", "pipeline", "--n", "10", "--warmup", "0", "--max-framework-p99-ms", "0.000001"])
            == 1
        )
