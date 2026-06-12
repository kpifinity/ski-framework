"""CLI for the SKI benchmark suite.

Usage:

    # Framework overhead (in-process, FakeLLM, no infra needed):
    python -m benchmarks.run --mode pipeline --n 2000 --warmup 200

    # End-to-end against a live deployment:
    python -m benchmarks.run --mode http \\
        --endpoint https://localhost:8000 --api-key "$SKI_API_KEY" \\
        --n 200 --warmup 20

    # Gate on a framework-overhead budget (CI):
    python -m benchmarks.run --mode pipeline --max-framework-p99-ms 100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .report import to_json, to_markdown
from .runner import REPO_ROOT, run_http, run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.run", description=__doc__)
    parser.add_argument("--mode", choices=["pipeline", "http"], default="pipeline")
    parser.add_argument("--n", type=int, default=2000, help="measured samples (default 2000)")
    parser.add_argument("--warmup", type=int, default=200, help="warmup iterations (default 200)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "evals" / "datasets" / "energy",
        help="workload dataset dir (default: evals/datasets/energy)",
    )
    parser.add_argument("--endpoint", default=None, help="live SKI Model endpoint (http mode)")
    parser.add_argument("--api-key", default=None, help="API key (http mode)")
    parser.add_argument("--verify-tls", action="store_true", help="verify TLS certs (http mode)")
    parser.add_argument("--json-out", type=Path, default=None, help="write JSON report here")
    parser.add_argument("--md-out", type=Path, default=None, help="write markdown report here")
    parser.add_argument(
        "--max-framework-p99-ms",
        type=float,
        default=None,
        help="exit non-zero if pipeline framework_total p99 exceeds this budget",
    )
    args = parser.parse_args(argv)

    if args.mode == "pipeline":
        from ski_model.v3.evaluator import FakeLLM

        run = run_pipeline(
            dataset_dir=args.dataset,
            backend=FakeLLM(),
            n=args.n,
            warmup=args.warmup,
            seed=args.seed,
        )
    else:
        if not args.endpoint or not args.api_key:
            parser.error("--mode http requires --endpoint and --api-key")
        run = run_http(
            dataset_dir=args.dataset,
            endpoint=args.endpoint,
            api_key=args.api_key,
            n=args.n,
            warmup=args.warmup,
            insecure=not args.verify_tls,
        )

    md = to_markdown([run])
    print(md)
    if args.json_out:
        args.json_out.write_text(to_json([run]), encoding="utf-8")
    if args.md_out:
        args.md_out.write_text(md, encoding="utf-8")

    if args.max_framework_p99_ms is not None and args.mode == "pipeline":
        p99 = run.stages["framework_total"].p99_ms
        if p99 > args.max_framework_p99_ms:
            print(
                f"FAIL: framework_total p99 {p99:.2f} ms exceeds budget {args.max_framework_p99_ms:.2f} ms",
                file=sys.stderr,
            )
            return 1
        print(f"OK: framework_total p99 {p99:.2f} ms within budget {args.max_framework_p99_ms:.2f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
