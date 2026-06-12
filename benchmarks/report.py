"""Benchmark report rendering — JSON for machines, markdown for humans."""

from __future__ import annotations

import json
from typing import List

from .runner import BenchmarkRun

_STAGE_LABELS = {
    "scope_to": "KG scoping (`scope_to`)",
    "evaluate_verify_sign": "Evaluate + verify + sign",
    "framework_total": "**Framework total (per verdict)**",
    "end_to_end": "**End-to-end (per verdict)**",
}


def to_json(runs: List[BenchmarkRun]) -> str:
    return json.dumps([r.as_dict() for r in runs], indent=2, sort_keys=False)


def to_markdown(runs: List[BenchmarkRun]) -> str:
    lines: List[str] = ["# SKI benchmark report", ""]
    for run in runs:
        prov = run.provenance
        env = prov.get("environment", {})
        lines += [
            f"## Mode: `{run.mode}`",
            "",
            f"- Ran at: {prov.get('ran_at')}",
            f"- Samples: {prov.get('n')} (after {prov.get('warmup')} warmup)",
            f"- Backend/endpoint: `{prov.get('backend', prov.get('endpoint', 'n/a'))}`",
            f"- Workload: `{prov.get('dataset')}` (KG `{prov.get('kg_version', 'n/a')}`)",
            f"- Environment: Python {env.get('python')} · {env.get('platform')} · "
            f"{env.get('cpu_count')} CPUs · commit `{env.get('git_commit')}`",
            "",
            "| Stage | p50 | p90 | p95 | p99 | mean | max | verdicts/s |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name, s in run.stages.items():
            label = _STAGE_LABELS.get(name, f"`{name}`")
            lines.append(
                f"| {label} | {s.p50_ms:.2f} ms | {s.p90_ms:.2f} ms | {s.p95_ms:.2f} ms "
                f"| {s.p99_ms:.2f} ms | {s.mean_ms:.2f} ms | {s.max_ms:.2f} ms "
                f"| {s.throughput_per_s:.0f} |"
            )
        if run.verdict_counts:
            counts = " · ".join(f"{k}: {v}" for k, v in sorted(run.verdict_counts.items()))
            lines += ["", f"Verdict mix: {counts}", ""]
        if run.mode == "pipeline":
            lines += [
                "",
                "Framework overhead only — model inference time is ~0 under the "
                "deterministic FakeLLM backend. End-to-end latency in a deployment "
                "is framework overhead + LLM inference + ledger round-trip; measure "
                "it with `--mode http` against the live stack.",
                "",
            ]
    return "\n".join(lines)
