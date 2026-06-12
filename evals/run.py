"""CLI entry point: ``python -m evals.run --backend fake|ollama|vllm``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

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
        help="Dataset directory name under evals/datasets/ (default: energy).",
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
    dataset_dir = REPO_ROOT / "evals" / "datasets" / args.dataset
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


if __name__ == "__main__":
    raise SystemExit(main())
