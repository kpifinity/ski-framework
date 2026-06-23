#!/usr/bin/env python3
"""
SKI Framework -- Interactive Quickstart
----------------------------------------
Walks you through four real compliance evaluations step-by-step, showing
exactly how SKI's neuro-symbolic architecture works -- no technical
background required.

Usage
-----
  python quickstart.py          # guided walkthrough (4 cases)
  python quickstart.py --all    # run all 50 eval cases, then show summary
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: add reference-implementation/src and the repo root to sys.path
# so all packages are importable whether or not they've been pip-installed.
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
_SRC = HERE / "reference-implementation" / "src"
for _p in [str(HERE), str(_SRC)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Bootstrap rich (auto-install if missing)
# ---------------------------------------------------------------------------
def _ensure_rich() -> None:
    try:
        import rich  # noqa: F401
    except ImportError:
        print("One-time setup: installing display library (rich)...")
        import subprocess

        subprocess.run(
            [sys.executable, "-m", "pip", "install", "rich", "--quiet"],
            check=True,
        )


_ensure_rich()

from rich import box  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from rich.rule import Rule  # noqa: E402
from rich.table import Table  # noqa: E402

# ---------------------------------------------------------------------------
# Import SKI components
# ---------------------------------------------------------------------------
try:
    from ski_model.kg_loader import KnowledgeGraph
    from ski_model.v3.evaluator import FakeLLM, V3Evaluator
except ImportError as exc:
    print(f"\n[ERROR] SKI packages not found: {exc}")
    print("\nInstall them with:")
    print("  pip install -e reference-implementation/ -e tools/ski-schemas/src")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EVAL_KG_PATH = HERE / "evals" / "datasets" / "energy" / "eval-kg.json"
AS_OF = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
JURISDICTION = "us.federal"

CONSOLE = Console()

# ---------------------------------------------------------------------------
# The four walkthrough cases (human-readable metadata + raw eval inputs)
# ---------------------------------------------------------------------------
DEMO_CASES = [
    {
        "id": "clear-so2-mid",
        "title": "Case 1 of 4 -- Normal reading, no issues",
        "story": (
            "A power plant in the US just sent a sensor reading: "
            "[bold]sulfur dioxide (SO₂) at 85 ppm[/bold].\n"
            "The federal limit is 100 ppm. SKI checks whether this reading complies."
        ),
        "subject": "facility.so2_ppm",
        "measurement": {"so2_ppm": 85},
        "expected": "CLEAR",
    },
    {
        "id": "flag-so2-gross",
        "title": "Case 2 of 4 -- Clear breach",
        "story": (
            "Same plant, next hour: SO₂ jumps to [bold]500 ppm[/bold] -- "
            "five times the federal limit of 100 ppm.\n"
            "SKI must catch this and flag it immediately."
        ),
        "subject": "facility.so2_ppm",
        "measurement": {"so2_ppm": 500},
        "expected": "FLAG",
    },
    {
        "id": "clear-so2-boundary",
        "title": "Case 3 of 4 -- Exactly at the limit",
        "story": (
            "Reading: SO₂ at [bold]exactly 100 ppm[/bold] -- right on the line.\n"
            "The regulation says 'must not exceed 100 ppm', which means 100 is still allowed.\n"
            "This is a precision test: SKI must know that at-the-limit is CLEAR, not a breach."
        ),
        "subject": "facility.so2_ppm",
        "measurement": {"so2_ppm": 100},
        "expected": "CLEAR",
    },
    {
        "id": "unmapped-co-future-breach",
        "title": "Case 4 of 4 -- A rule that isn't in force yet",
        "story": (
            "Reading: carbon monoxide (CO) at [bold]60 ppm[/bold] on June 15, 2026.\n"
            "A federal CO rule exists -- but it doesn't take effect until September 1, 2026.\n"
            "SKI must not apply a rule before its effective date. "
            "The honest answer is: [italic]no current rule covers this[/italic]."
        ),
        "subject": "facility.co_ppm",
        "measurement": {"co_ppm": 60},
        "expected": "NULL_UNMAPPED",
    },
]

# Human-readable verdict labels for non-technical users
VERDICT_DISPLAY: dict[str, tuple[str, str, str]] = {
    "CLEAR": (
        "CLEAR",
        "bold green",
        "No compliance issue -- this reading is within all applicable limits.",
    ),
    "FLAG": (
        "BREACH DETECTED",
        "bold red",
        "A regulatory limit has been exceeded. Escalate to your compliance team.",
    ),
    "DISCRETIONARY": (
        "HUMAN REVIEW",
        "bold yellow",
        "The system cannot make a confident decision. A compliance officer should review.",
    ),
    "NULL_UNMAPPED": (
        "NOT COVERED",
        "bold blue",
        "No current rule applies to this measurement. The KG does not map this subject.",
    ),
    "NULL_STALE": (
        "DATA EXPIRED",
        "bold yellow",
        "The rule's time window has passed. Check data freshness upstream.",
    ),
}

VERIFIER_DISPLAY: dict[str, tuple[str, str]] = {
    "AGREED": (
        "Independent rule-checker confirmed the verdict.",
        "green",
    ),
    "LLM_CONTRADICTION": (
        "Rule-checker disagreed with the AI and overrode it. Sent to human review.",
        "yellow",
    ),
    "NEURO_SYMBOLIC_DIVERGENCE": (
        "Rule-checker found an internal contradiction. Sent to human review.",
        "yellow",
    ),
    "UNVERIFIABLE": (
        "Rule requires historical data -- human review scheduled.",
        "dim",
    ),
    "UNVERIFIED_CLEAR": (
        "No assertions to verify -- verdict treated as unverified.",
        "dim",
    ),
}


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _pause(prompt: str = "Press [bold]Enter[/bold] to continue...") -> None:
    CONSOLE.print()
    Prompt.ask(f"  [dim]{prompt}[/dim]", default="", show_default=False)
    CONSOLE.print()


def _show_measurement_table(case: dict[str, Any]) -> None:
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("Key", style="dim")
    t.add_column("Value", style="bold")
    for k, v in case["measurement"].items():
        t.add_row(k, str(v))
    t.add_row("subject", case["subject"])
    t.add_row("jurisdiction", JURISDICTION)
    t.add_row("timestamp", AS_OF.strftime("%Y-%m-%d %H:%M UTC"))
    CONSOLE.print(t)


def _show_verdict(envelope: Any) -> None:
    raw = getattr(envelope.verdict, "value", str(envelope.verdict))
    label, style, description = VERDICT_DISPLAY.get(raw, (raw, "bold", "Unknown verdict."))
    CONSOLE.print(
        Panel(
            f"[{style}]{label}[/{style}]\n\n[dim]{description}[/dim]",
            title="Verdict",
            border_style=style.replace("bold ", ""),
            padding=(1, 4),
        )
    )

    # Verifier result
    v_status = getattr(envelope.verifier_result.status, "value", str(envelope.verifier_result.status))
    v_msg, v_color = VERIFIER_DISPLAY.get(v_status, (v_status, "white"))
    CONSOLE.print(f"  [dim]Symbolic Verifier:[/dim] [{v_color}]{v_msg}[/{v_color}]")

    # Show assertions if present
    assertions = envelope.formalizable_assertions
    if assertions:
        CONSOLE.print()
        t = Table(
            title="What was checked",
            box=box.SIMPLE,
            show_header=True,
            header_style="dim",
            padding=(0, 2),
        )
        t.add_column("Rule", style="dim", no_wrap=True)
        t.add_column("Satisfied?")
        for a in assertions:
            ok = a.satisfied
            t.add_row(
                a.obligation_id,
                "[green]Yes[/green]" if ok else "[red]No -- limit breached[/red]",
            )
        CONSOLE.print(t)


# ---------------------------------------------------------------------------
# Core: load KG and evaluator
# ---------------------------------------------------------------------------


def _load_kg() -> KnowledgeGraph:
    if not EVAL_KG_PATH.exists():
        CONSOLE.print(
            f"[red]Knowledge Graph not found at {EVAL_KG_PATH}[/red]\nRun this script from the repo root."
        )
        sys.exit(1)
    raw = json.loads(EVAL_KG_PATH.read_text(encoding="utf-8"))
    return KnowledgeGraph.from_dict(raw, require_signature=False)


def _show_kg_overview(kg: KnowledgeGraph) -> None:
    snapshot = kg.scope_to(jurisdiction=JURISDICTION, as_of=AS_OF)
    obligations = snapshot.get("obligations", [])

    CONSOLE.print(Rule("[bold]The Knowledge Graph[/bold]", style="dim"))
    CONSOLE.print()
    CONSOLE.print(
        "  The [bold]Knowledge Graph (KG)[/bold] is SKI's rulebook. "
        "It contains the regulations\n"
        "  translated into machine-readable obligations that the evaluator checks against.\n"
    )

    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    t.add_column("Rule ID", style="dim", no_wrap=True)
    t.add_column("What it checks")
    t.add_column("Limit / Range", justify="right")

    rule_descriptions = {
        "energy.so2.cap": ("SO₂ emissions (sulfur dioxide)", "≤ 100 ppm"),
        "energy.nox.cap": ("NOₓ emissions (nitrogen oxides)", "≤ 75 ppm"),
        "energy.ph.range": ("Wastewater pH (acidity/alkalinity)", "6.0 - 8.5"),
        "energy.temp.range": ("Effluent temperature", "5 - 40 °C"),
        "energy.methane.cap": ("Methane emissions", "≤ 12 kg/h"),
        "energy.turbidity.cap": ("Water turbidity", "≤ 1.0 NTU"),
        "energy.flow.min": ("Cooling water flow rate", "≥ 10 m³/h"),
    }

    for ob in obligations:
        ob_id = ob.get("id", "")
        desc, limit = rule_descriptions.get(ob_id, (ob_id, ""))
        t.add_row(ob_id, desc, limit)

    if not obligations:
        CONSOLE.print("  [dim](No obligations in scope for this jurisdiction / date.)[/dim]")
    else:
        CONSOLE.print(t)

    CONSOLE.print(
        f"\n  [dim]{len(obligations)} rules currently in force "
        f"for {JURISDICTION} as of {AS_OF.strftime('%B %d, %Y')}.[/dim]"
        "\n  (The CO rule is intentionally absent -- it takes effect on September 1, 2026.)"
    )


# ---------------------------------------------------------------------------
# Run one demo case
# ---------------------------------------------------------------------------


async def _run_case(
    evaluator: V3Evaluator,
    kg: KnowledgeGraph,
    case: dict[str, Any],
) -> tuple[str, str]:
    """Returns (predicted_verdict, expected_verdict)."""
    snapshot = kg.scope_to(jurisdiction=JURISDICTION, as_of=AS_OF)
    envelope = await evaluator.aevaluate(
        measurement=case["measurement"],
        kg_snapshot=snapshot,
        subject=case["subject"],
        as_of=AS_OF,
    )
    return envelope, getattr(envelope.verdict, "value", str(envelope.verdict))


# ---------------------------------------------------------------------------
# Main walkthrough
# ---------------------------------------------------------------------------


async def _walkthrough(kg: KnowledgeGraph, evaluator: V3Evaluator) -> None:
    correct = 0

    for i, case in enumerate(DEMO_CASES):
        CONSOLE.print(Rule(f"[bold]{case['title']}[/bold]", style="cyan"))
        CONSOLE.print()
        CONSOLE.print(f"  {case['story']}\n", markup=True)
        _show_measurement_table(case)
        _pause("Press Enter to run the evaluation...")

        with CONSOLE.status("  Evaluating...", spinner="dots"):
            envelope, verdict = await _run_case(evaluator, kg, case)

        _show_verdict(envelope)

        # Correctness check
        expected = case["expected"]
        if verdict == expected:
            correct += 1
            CONSOLE.print(
                f"\n  [green]Correct.[/green] Expected [bold]{expected}[/bold] -- got [bold]{verdict}[/bold]."
            )
        else:
            CONSOLE.print(
                f"\n  [yellow]Unexpected result.[/yellow] "
                f"Expected [bold]{expected}[/bold] -- got [bold]{verdict}[/bold]."
            )

        if i < len(DEMO_CASES) - 1:
            _pause()

    # Summary
    CONSOLE.print()
    CONSOLE.print(Rule("[bold]Summary[/bold]", style="dim"))
    CONSOLE.print()
    accuracy = correct / len(DEMO_CASES) * 100
    CONSOLE.print(
        Panel(
            f"[bold]{correct} / {len(DEMO_CASES)} cases correct[/bold]  "
            f"[dim]({accuracy:.0f}% accuracy)[/dim]\n\n"
            "[dim]The neuro-symbolic architecture means:\n"
            "  •  The LLM reasons over the Knowledge Graph to reach a verdict\n"
            "  •  The Symbolic Verifier independently checks the arithmetic\n"
            "  •  If they disagree, the verdict goes to a human reviewer -- never silently cleared[/dim]",
            title="Walkthrough complete",
            border_style="green",
            padding=(1, 4),
        )
    )
    CONSOLE.print()
    CONSOLE.print(
        "  [bold]Next steps:[/bold]\n"
        "  •  Run all 50 eval cases:  [bold]python quickstart.py --all[/bold]\n"
        "  •  Use a real LLM:         [bold]python -m evals.run --backend ollama[/bold]\n"
        "  •  Read the docs:          [bold]https://skiframework.org[/bold]\n"
    )


async def _run_all(kg: KnowledgeGraph, evaluator: V3Evaluator) -> None:
    """Run all 50 eval cases and show a summary table."""
    from evals.metrics import CaseResult, compute_metrics
    from evals.runner import load_cases

    cases_path = HERE / "evals" / "datasets" / "energy" / "cases.jsonl"
    cases = load_cases(cases_path)

    CONSOLE.print(f"  Running {len(cases)} cases...\n")
    results = []
    with CONSOLE.status("", spinner="dots") as status:
        for c in cases:
            status.update(f"  Evaluating [bold]{c['case_id']}[/bold]...")
            snapshot = kg.scope_to(
                jurisdiction=c.get("jurisdiction"),
                as_of=datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00")),
            )
            envelope = await evaluator.aevaluate(
                measurement=c["measurement"],
                kg_snapshot=snapshot,
                subject=c.get("subject"),
                as_of=datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00")),
            )
            predicted = getattr(envelope.verdict, "value", str(envelope.verdict))
            v_status = getattr(
                envelope.verifier_result.status,
                "value",
                str(envelope.verifier_result.status),
            )
            results.append(
                CaseResult(
                    case_id=c["case_id"],
                    category=c.get("category", ""),
                    expected_verdict=c["expected"]["verdict"],
                    predicted_verdict=predicted,
                    expected_assertions=c["expected"].get("assertions", []),
                    emitted_assertions=[a.model_dump() for a in envelope.formalizable_assertions],
                    verifier_status=v_status,
                    checked_assertions=envelope.verifier_result.checked_assertions,
                    notes=c.get("notes", ""),
                )
            )

    m = compute_metrics(results)
    mismatches = [r for r in results if not r.verdict_correct]

    t = Table(box=box.SIMPLE_HEAD, header_style="bold", padding=(0, 2))
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Verdict accuracy", f"{m.verdict_accuracy * 100:.1f}%")
    t.add_row("FLAG recall (breach detection)", f"{m.flag_recall * 100:.1f}%")
    t.add_row("FLAG precision (false-alarm rate)", f"{m.flag_precision * 100:.1f}%")
    t.add_row(
        "[bold red]Breaches silently CLEARed[/bold red]",
        f"[bold red]{m.breaches_silently_cleared}[/bold red]",
    )
    t.add_row("Assertion correctness", f"{m.assertion_accuracy * 100:.1f}%")
    t.add_row("Verifier agreement rate", f"{m.verifier_agreement_rate * 100:.1f}%")
    CONSOLE.print(t)

    if mismatches:
        CONSOLE.print(f"\n  [dim]{len(mismatches)} mismatch(es):[/dim]")
        for r in mismatches:
            CONSOLE.print(
                f"  [dim]  {r.case_id}: expected {r.expected_verdict} "
                f"-- got {r.predicted_verdict} ({r.verifier_status})[/dim]"
            )


async def main() -> None:
    run_all = "--all" in sys.argv

    # Welcome banner
    CONSOLE.print()
    CONSOLE.print(
        Panel(
            "[bold]SKI Framework[/bold] -- Sovereign Knowledge Intelligence\n\n"
            "This quickstart walks you through real compliance evaluations.\n"
            "You will see how a local AI model, guided by a structured Knowledge\n"
            "Graph, checks sensor readings against regulatory limits -- and how\n"
            "an independent rule-checker verifies every conclusion.\n\n"
            "[dim]No cloud. No external APIs. Everything runs on your machine.[/dim]",
            title="Welcome",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    CONSOLE.print()

    # Load KG
    with CONSOLE.status("  Loading Knowledge Graph...", spinner="dots"):
        kg = _load_kg()
        evaluator = V3Evaluator(llm=FakeLLM(), kg_version_hash="quickstart", decoder_seed=42)

    CONSOLE.print("  [green]Knowledge Graph loaded.[/green]\n")

    if run_all:
        CONSOLE.print(Rule("[bold]Full eval suite (50 cases)[/bold]", style="dim"))
        CONSOLE.print()
        await _run_all(kg, evaluator)
    else:
        _show_kg_overview(kg)
        _pause("Press Enter to start the walkthrough...")
        await _walkthrough(kg, evaluator)


if __name__ == "__main__":
    asyncio.run(main())
