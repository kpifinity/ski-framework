"""
Command-line interface for KG Validator
"""

import json
from typing import Optional

import click
from pydantic import ValidationError

from .conflict_detector import ConflictDetector
from .utils import generate_html_report, load_rules, save_validation_result
from .v3 import V3Validator, load_v3_kg
from .validator import Validator


@click.group()
def main():
    """Validate and review extracted compliance rules"""


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules or a v3 KG")
@click.option("--output", "-o", default=None, help="Output JSON file with validation results")
@click.option(
    "--schema",
    type=click.Choice(["v2", "v3"], case_sensitive=False),
    default="v2",
    show_default=True,
    help=(
        "KG schema to validate against. v2 (default) is the flat-rule-list shape used by "
        "v0.2.x releases. v3 is the typed graph defined by spec v3.0 §3 (RFC 0002)."
    ),
)
def validate(input: str, output: Optional[str], schema: str):
    """Validate a KG against the selected schema.

    v2 default behaviour (unchanged): automated checks on the extracted
    rule list. Every rule still needs human approval via the
    interactive-review workflow.

    v3 (``--schema v3``): parse the input as a typed-graph v3 KG and
    run the spec §3.6 validation passes implemented in
    :mod:`kg_validator.v3`.
    """
    if schema.lower() == "v3":
        _validate_v3(input, output)
        return

    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)
        click.echo(f"Loaded {len(rules)} rules")

        click.echo("Running validation checks...")
        validator = Validator()
        result = validator.validate(rules)

        # Print summary
        click.echo("\nValidation complete:")
        click.echo(f"  Approved: {result.metadata.total_approved}")
        click.echo(f"  Rejected: {result.metadata.total_rejected}")
        click.echo(f"  Flagged: {result.metadata.total_flagged}")
        click.echo(f"  Issues found: {result.metadata.total_issues_found}")
        click.echo(f"  Conflicts: {len(result.conflicts)}")
        click.echo(f"  Duplicates: {len(result.duplicates)}")

        # Save results
        if output:
            save_validation_result(result, output)
            click.echo(f"\nResults saved to: {output}")
        else:
            click.echo("\n" + json.dumps(result.to_json(), indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e


def _validate_v3(input_path: str, output_path: Optional[str]) -> None:
    """v3 validation path. Loads the typed-graph KG and runs §3.6 passes."""
    try:
        click.echo(f"Loading v3 KG from: {input_path}")
        kg = load_v3_kg(input_path)
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

    click.echo("\nv3 validation complete:")
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
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        click.echo(f"\nResults saved to: {output_path}")
    elif result.total_issues:
        click.echo("\n" + json.dumps(payload, indent=2))


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--output", "-o", default=None, help="Output JSON file with validation results")
def review(input: str, output: Optional[str]):
    """Interactive review of rules (simulated for now)"""
    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)
        click.echo(f"Loaded {len(rules)} rules")

        click.echo("Starting interactive review...")
        validator = Validator()
        result = validator.interactive_review(rules)

        click.echo("\nReview complete:")
        click.echo(f"  Approved: {result.metadata.total_approved}")
        click.echo(f"  Rejected: {result.metadata.total_rejected}")
        click.echo(f"  Flagged: {result.metadata.total_flagged}")

        if output:
            save_validation_result(result, output)
            click.echo(f"\nResults saved to: {output}")
        else:
            click.echo("\n" + json.dumps(result.to_json(), indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--output", "-o", default=None, help="Output JSON file with conflicts")
def detect_conflicts(input: str, output: Optional[str]):
    """Detect conflicts between rules"""
    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)

        click.echo("Detecting conflicts...")
        conflicts = ConflictDetector.detect_conflicts(rules)

        click.echo(f"Found {len(conflicts)} conflicting rule pairs")

        output_data = {
            "total_conflicts": len(conflicts),
            "conflicts": [c.dict() for c in conflicts],
        }

        if output:
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)
            click.echo(f"Results saved to: {output}")
        else:
            click.echo(json.dumps(output_data, indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--output", "-o", default=None, help="Output JSON file with duplicates")
@click.option("--threshold", "-t", default=0.85, type=float, help="Similarity threshold (0-1)")
def detect_duplicates(input: str, output: Optional[str], threshold: float):
    """Detect duplicate rules"""
    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)

        click.echo(f"Detecting duplicates (threshold={threshold})...")
        duplicates = ConflictDetector.detect_duplicates(rules, threshold=threshold)

        click.echo(f"Found {len(duplicates)} duplicate pairs")

        output_data = {
            "total_duplicates": len(duplicates),
            "threshold": threshold,
            "duplicates": [d.dict() for d in duplicates],
        }

        if output:
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)
            click.echo(f"Results saved to: {output}")
        else:
            click.echo(json.dumps(output_data, indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--validated-rules", "-v", default=None, help="JSON file with validated rules")
@click.option("--output", "-o", required=True, help="Output HTML report file")
def report(input: str, validated_rules: Optional[str], output: str):
    """Generate validation report"""
    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)

        click.echo("Generating report...")
        validator = Validator()
        result = validator.validate(rules)

        generate_html_report(result, output)
        click.echo(f"Report saved to: {output}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
def examples():
    """Show usage examples"""
    examples_text = """
KG Validator Examples:

1. Validate extracted rules:
   kg-validator validate --input extracted-rules.json --output validated-rules.json

2. Interactive review:
   kg-validator review --input extracted-rules.json --output reviewed-rules.json

3. Detect conflicts:
   kg-validator detect-conflicts --input rules.json --output conflicts.json

4. Detect duplicates:
   kg-validator detect-duplicates --input rules.json --threshold 0.85

5. Generate HTML report:
   kg-validator report --input extracted-rules.json --output validation-report.html

6. Complete workflow (extract -> validate -> report):
   kg-extractor extract --file regulation.txt --output extracted.json
   kg-validator validate --input extracted.json --output validated.json
   kg-validator report --input extracted.json --output report.html
"""
    click.echo(examples_text)


@main.command()
def version():
    """Show version"""
    from . import __version__

    click.echo(f"kg-validator {__version__}")


if __name__ == "__main__":
    main()
