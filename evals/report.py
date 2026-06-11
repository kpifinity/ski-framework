"""Render an :class:`~evals.runner.EvalRun` as JSON + Markdown."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .runner import EvalRun


def _pct(value: Optional[float]) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def render_markdown(run: EvalRun) -> str:
    m = run.metrics
    p = run.provenance
    lines = [
        f"# SKI Evals report — `{run.dataset}` dataset",
        "",
        f"Backend **{p['backend']}** · seed {p['decoder_seed']} · {p['n_cases']} cases · {p['ran_at']}",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Verdict accuracy | **{_pct(m.verdict_accuracy)}** |",
        f"| FLAG recall (missed breaches are the misses) | **{_pct(m.flag_recall)}** |",
        f"| FLAG precision | {_pct(m.flag_precision)} |",
        f"| Breaches silently CLEARed | **{m.breaches_silently_cleared}** |",
        f"| NULL_UNMAPPED recall | {_pct(m.unmapped_recall)} |",
        f"| Assertion correctness | {_pct(m.assertion_accuracy)} |",
        f"| LLM-verifier agreement rate | {_pct(m.verifier_agreement_rate)} |",
        "",
        "## Accuracy by category",
        "",
        "| Category | Accuracy |",
        "|---|---|",
    ]
    lines += [f"| {cat} | {_pct(acc)} |" for cat, acc in m.per_category_accuracy.items()]
    lines += ["", "## Confusion (expected → predicted)", ""]
    for expected, row in sorted(m.confusion.items()):
        cells = ", ".join(f"{pred}: {n}" for pred, n in sorted(row.items()))
        lines.append(f"- **{expected}** → {cells}")
    if m.mismatches:
        lines += [
            "",
            "## Mismatches",
            "",
            "| Case | Expected | Predicted | Verifier | Notes |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| `{x['case_id']}` | {x['expected']} | {x['predicted']} | {x['verifier_status']} | {x['notes']} |"
            for x in m.mismatches
        ]
    else:
        lines += ["", "No mismatches."]
    lines += [
        "",
        "## Provenance",
        "",
        "```json",
        json.dumps(p, indent=2),
        "```",
        "",
        "_Methodology: docs/evals.md. A missed breach (FLAG recall < 100%) is the failure",
        "mode that matters most; treat any drop as a release blocker._",
        "",
    ]
    return "\n".join(lines)


def write_report(run: EvalRun, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"evals-{run.dataset}-{run.provenance['backend']}.json").write_text(
        json.dumps(run.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / f"evals-{run.dataset}-{run.provenance['backend']}.md").write_text(
        render_markdown(run), encoding="utf-8"
    )
