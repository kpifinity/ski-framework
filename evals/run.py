"""CLI entry point: ``python -m evals.run --backend fake|ollama|vllm``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, List

from .report import render_markdown, write_report
from .runner import REPO_ROOT, run_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SKI Evals verdict-accuracy suite.")
    parser.add_argument(
        "--backend",
        choices=["fake", "ollama", "vllm"],
        default="fake",
        help="LLM backend. 'fake' validates the harness; 'ollama'/'vllm' produce real model numbers.",
    )
    parser.add_argument(
        "--dataset",
        default="energy",
        help="Dataset directory name under evals/datasets/, or 'all' (default: energy).",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        help="Run every dataset once per decoder seed and write a summary with Wilson 95%% intervals "
        "(evals/summary.py). Overrides --seed.",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "evals-report"),
        help="Output directory for the JSON + Markdown report.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Decoder seed recorded in provenance.")
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help="Also write the raw LLM output for every case (diagnosis of format/citation failures).",
    )
    args = parser.parse_args()

    # Route through the same factory the server uses, so backend
    # configuration (model name, base URL, seed) behaves identically.
    os.environ["SKI_V3_LLM_BACKEND"] = args.backend
    from ski_model.v3.backends import build_backend

    backend = build_backend()
    root = REPO_ROOT / "evals" / "datasets"
    if args.dataset == "all" or args.seeds:
        names = (
            sorted(p.parent.name for p in root.glob("*/cases.jsonl"))
            if args.dataset == "all"
            else [args.dataset]
        )
        return _run_matrix(backend, [root / n for n in names], args.seeds or [args.seed], Path(args.out))
    dataset_dir = root / args.dataset
    if not dataset_dir.is_dir():
        print(f"error: no dataset at {dataset_dir}", file=sys.stderr)
        return 2

    run = asyncio.run(run_eval(dataset_dir=dataset_dir, backend=backend, seed=args.seed))
    write_report(run, Path(args.out))
    if args.dump_raw:
        import json as _json

        raw_path = Path(args.out) / f"evals-{run.dataset}-{run.provenance['backend']}-raw.json"
        raw_path.write_text(_json.dumps(run.raw_outputs, indent=2) + "\n", encoding="utf-8")
        print(f"raw outputs -> {raw_path}", file=sys.stderr)
    print(render_markdown(run))
    return 0


def _run_matrix(backend: Any, dataset_dirs: List[Path], seeds: List[int], out: Path) -> int:
    """Every dataset under every seed, one report each, then the cross-run summary."""
    from .summary import load_runs, render, summarize

    model = str(getattr(backend, "model_id", backend.name)).replace("/", "_").replace(":", "_")
    for dataset_dir in dataset_dirs:
        if not dataset_dir.is_dir():
            print(f"error: no dataset at {dataset_dir}", file=sys.stderr)
            return 2
    for seed in seeds:
        for dataset_dir in dataset_dirs:
            run = asyncio.run(run_eval(dataset_dir=dataset_dir, backend=backend, seed=seed))
            write_report(run, out / model / f"seed-{seed}")
            print(f"{dataset_dir.name} seed {seed}: accuracy {run.metrics.verdict_accuracy}", file=sys.stderr)
    summary = summarize(load_runs(out / model))
    (out / model / "evals-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    text = render(summary)
    (out / model / "evals-summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
