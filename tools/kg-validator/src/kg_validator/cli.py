"""Command-line interface for kg-validator (v3-only).

The validator now accepts a single subcommand — ``validate`` — which
loads a v3 KG JSON file and runs the spec §3.6 validation passes.

The v2 ``review``, ``detect-conflicts``, ``detect-duplicates``, and
HTML ``report`` subcommands were retired with PR 10e: they targeted
the flat-rule list shape that is no longer the framework's currency.
v3 conflict/duplicate detection happens at the typed-obligation level
inside :mod:`kg_validator.validator` and surfaces as issues in the
:class:`V3ValidationResult`.
"""

from __future__ import annotations

import json
from typing import Optional

import click
from pydantic import ValidationError

from . import __version__
from .loader import load_v3_kg
from .validator import V3Validator


@click.group()
def main() -> None:
    """Validate v3 KG files against SKI Framework spec v3.0 §3."""


@main.command()
@click.option("--input", "-i", required=True, help="Input v3 KG JSON file.")
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output JSON file with validation results. If omitted, results are printed to stdout when issues are found.",
)
def validate(input: str, output: Optional[str]) -> None:
    """Validate a v3 KG against spec §3 schema and §3.6 cross-cutting passes."""
    try:
        click.echo(f"Loading v3 KG from: {input}")
        kg = load_v3_kg(input)
    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except ValidationError as e:
        click.echo("Schema validation failed:", err=True)
        click.echo(str(e), err=True)
        raise SystemExit(2) from e

    click.echo(
        f"Loaded {len(kg.nodes.rules)} rules, {len(kg.nodes.obligations)} obligations, {len(kg.edges)} edges"
    )

    result = V3Validator(kg).run()

    click.echo("\nValidation complete:")
    click.echo(f"  Nodes: {result.total_nodes}")
    click.echo(f"  Edges: {result.total_edges}")
    click.echo(f"  Issues: {result.total_issues}")
    if result.total_issues:
        click.echo("\nIssues by type:")
        by_type: dict[str, int] = {}
        for issue in result.issues:
            key = str(issue.issue_type)
            by_type[key] = by_type.get(key, 0) + 1
        for key in sorted(by_type):
            click.echo(f"  {key}: {by_type[key]}")

    payload = result.model_dump(mode="json")
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        click.echo(f"\nResults saved to: {output}")
    elif result.total_issues:
        click.echo("\n" + json.dumps(payload, indent=2))

    # Exit non-zero on any CRITICAL or HIGH issue so CI flows can gate on it.
    if not result.is_clean:
        raise SystemExit(3)


@main.command()
def examples() -> None:
    """Show usage examples."""
    examples_text = """
kg-validator examples (v3):

1. Validate a v3 KG file:
   kg-validator validate --input kg-energy-v3.json

2. Validate and save the issue report:
   kg-validator validate --input kg-energy-v3.json --output report.json

3. Compile-extract-validate flow:
   kg-extractor extract --file regulation.txt --output kg-extracted.json --jurisdiction us.federal
   kg-validator validate --input kg-extracted.json --output validation-report.json
"""
    click.echo(examples_text)


@main.command()
def version() -> None:
    """Show version."""
    click.echo(f"kg-validator {__version__}")


if __name__ == "__main__":
    main()
