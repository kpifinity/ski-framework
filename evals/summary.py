"""Summarize eval runs across datasets, seeds and models, with Wilson 95% confidence intervals.

Each run (one model, one seed, one dataset) is the JSON ``write_report``
writes. The summary is computed from the per-case results in those files
alone, so runs made on different machines (CI matrix jobs) combine:

    python -m evals.summary evals-report/ [--out evals-report/summary]

Rates are pooled over the datasets of one (model, seed) run, so ``n`` is
the number of cases that metric is defined on. Seeds are not pooled: the
same case under three seeds is not three independent trials, so each seed
gets its own interval and the summary reports how stable the verdicts are
across seeds instead.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion ``k/n`` (``(0, 1)`` when ``n == 0``)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> Optional[float]:
        return self.k / self.n if self.n else None

    def as_dict(self) -> dict[str, Any]:
        lo, hi = wilson(self.k, self.n)
        return {"k": self.k, "n": self.n, "rate": self.value, "ci95": [round(lo, 4), round(hi, 4)]}

    def render(self) -> str:
        if not self.n:
            return "n/a"
        lo, hi = wilson(self.k, self.n)
        return f"{self.k / self.n:.1%} [{lo:.1%}, {hi:.1%}] ({self.k}/{self.n})"


Case = dict[str, Any]


def _rate(cases: list[Case], where: Callable[[Case], bool], hit: Callable[[Case], bool]) -> Rate:
    pool = [c for c in cases if where(c)]
    return Rate(sum(1 for c in pool if hit(c)), len(pool))


def metrics(cases: list[Case]) -> dict[str, Any]:
    """The headline metrics over a list of per-case results, as rates with intervals."""

    def exp(v: str) -> Callable[[Case], bool]:
        return lambda c: c["expected"] == v

    def pred(v: str) -> Callable[[Case], bool]:
        return lambda c: c["predicted"] == v

    rates = {
        "verdict_accuracy": _rate(cases, lambda c: True, lambda c: c["expected"] == c["predicted"]),
        "flag_recall": _rate(cases, exp("FLAG"), pred("FLAG")),
        "flag_precision": _rate(cases, pred("FLAG"), exp("FLAG")),
        "null_unmapped_recall": _rate(cases, exp("NULL_UNMAPPED"), pred("NULL_UNMAPPED")),
        "null_stale_recall": _rate(cases, exp("NULL_STALE"), pred("NULL_STALE")),
        "discretionary_rate": _rate(cases, lambda c: True, pred("DISCRETIONARY")),
        "verifier_agreement": _rate(
            cases,
            lambda c: (c.get("checked_assertions") or 0) > 0,
            lambda c: c["verifier_status"] == "AGREED",
        ),
    }
    out: dict[str, Any] = {name: r.as_dict() for name, r in rates.items()}
    out["breaches_silently_cleared"] = sum(
        1 for c in cases if c["expected"] == "FLAG" and c["predicted"] == "CLEAR"
    )
    out["silent_sensors_cleared"] = sum(
        1 for c in cases if c["expected"] == "NULL_STALE" and c["predicted"] == "CLEAR"
    )
    out["n_cases"] = len(cases)
    return out


def load_runs(root: Path) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(root.rglob("evals-*.json")):
        if path.name.endswith("-raw.json") or path.name.startswith("evals-summary"):
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        if "cases" in run and "provenance" in run:
            runs.append(run)
    return runs


def _model(run: dict[str, Any]) -> str:
    p = run["provenance"]
    return str(p.get("model_id") or p["backend"])


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_model_seed: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_model_seed[(_model(run), int(run["provenance"]["decoder_seed"]))].append(run)

    models: dict[str, Any] = {}
    for (model, seed), group in sorted(by_model_seed.items()):
        entry = models.setdefault(
            model,
            {
                "backend": group[0]["provenance"]["backend"],
                "model_weight_hash": group[0]["provenance"].get("model_weight_hash"),
                "seeds": {},
            },
        )
        pooled = [c for run in group for c in run["cases"]]
        entry["seeds"][str(seed)] = {
            "datasets": sorted(run["dataset"] for run in group),
            "pooled": metrics(pooled),
            "per_dataset": {
                run["dataset"]: metrics(run["cases"]) for run in sorted(group, key=lambda r: r["dataset"])
            },
        }

    for model, entry in models.items():
        verdicts: dict[tuple[str, str], set[str]] = defaultdict(set)
        for (m, _seed), group in by_model_seed.items():
            if m != model:
                continue
            for run in group:
                for c in run["cases"]:
                    verdicts[(run["dataset"], c["case_id"])].add(c["predicted"])
        stable = sum(1 for v in verdicts.values() if len(v) == 1)
        entry["seed_stability"] = Rate(stable, len(verdicts)).as_dict() if len(entry["seeds"]) > 1 else None
    return {"models": models}


def render(summary: dict[str, Any]) -> str:
    rows = [
        ("Verdict accuracy", "verdict_accuracy"),
        ("FLAG recall", "flag_recall"),
        ("FLAG precision", "flag_precision"),
        ("NULL_UNMAPPED recall", "null_unmapped_recall"),
        ("NULL_STALE recall", "null_stale_recall"),
        ("Routed to human review (DISCRETIONARY)", "discretionary_rate"),
        ("LLM-verifier agreement", "verifier_agreement"),
    ]
    lines = [
        "# SKI Evals summary",
        "",
        "Rates are pooled over the datasets of one model and seed; brackets are Wilson 95% intervals.",
        "",
    ]
    for model, entry in summary["models"].items():
        seeds = sorted(entry["seeds"], key=int)
        lines += [f"## `{model}` ({entry['backend']})", ""]
        lines += [
            "| Metric | " + " | ".join(f"seed {s}" for s in seeds) + " |",
            "|---|" + "---|" * len(seeds),
        ]
        for label, key in rows:
            cells = []
            for s in seeds:
                d = entry["seeds"][s]["pooled"][key]
                cells.append(Rate(d["k"], d["n"]).render())
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        for label, key in (
            ("**Breaches silently CLEARed**", "breaches_silently_cleared"),
            ("**Silent sensors CLEARed**", "silent_sensors_cleared"),
        ):
            lines.append(
                f"| {label} | " + " | ".join(f"**{entry['seeds'][s]['pooled'][key]}**" for s in seeds) + " |"
            )
        lines += [
            "",
            "Verdict accuracy by dataset:",
            "",
            "| Dataset | " + " | ".join(f"seed {s}" for s in seeds) + " |",
            "|---|" + "---|" * len(seeds),
        ]
        datasets = sorted({d for s in seeds for d in entry["seeds"][s]["per_dataset"]})
        for ds in datasets:
            cells = []
            for s in seeds:
                d = entry["seeds"][s]["per_dataset"].get(ds, {}).get("verdict_accuracy")
                cells.append(Rate(d["k"], d["n"]).render() if d else "n/a")
            lines.append(f"| {ds} | " + " | ".join(cells) + " |")
        if entry.get("seed_stability"):
            st = entry["seed_stability"]
            lines += ["", f"Same verdict under every seed: {Rate(st['k'], st['n']).render()}."]
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path, help="Directory holding the per-run evals-*.json reports.")
    parser.add_argument(
        "--out", type=Path, help="Write <out>.json and <out>.md (default: <root>/evals-summary)."
    )
    args = parser.parse_args(argv)
    runs = load_runs(args.root)
    if not runs:
        parser.error(f"no eval reports under {args.root}")
    summary = summarize(runs)
    out = args.out or args.root / "evals-summary"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    text = render(summary)
    out.with_suffix(".md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
