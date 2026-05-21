"""
Command-line interface for KG Validator
"""

import click
import json
from typing import Optional
from .validator import Validator
from .utils import load_rules, save_validation_result, generate_html_report
from .conflict_detector import ConflictDetector


@click.group()
def main():
    """Validate and review extracted compliance rules"""
    pass


@main.command()
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--output", "-o", default=None, help="Output JSON file with validation results")
@click.option("--auto-approve-explicit", is_flag=True, help="Auto-approve EXPLICIT confidence rules")
def validate(input: str, output: Optional[str], auto_approve_explicit: bool):
    """Validate extracted rules (automated checks)"""
    try:
        click.echo(f"Loading rules from: {input}")
        rules = load_rules(input)
        click.echo(f"Loaded {len(rules)} rules")

        click.echo("Running validation checks...")
        validator = Validator()
        result = validator.validate(rules, auto_approve_explicit=auto_approve_explicit)

        # Print summary
        click.echo(f"\nValidation complete:")
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
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


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

        click.echo(f"\nReview complete:")
        click.echo(f"  Approved: {result.metadata.total_approved}")
        click.echo(f"  Rejected: {result.metadata.total_rejected}")
        click.echo(f"  Flagged: {result.metadata.total_flagged}")

        if output:
            save_validation_result(result, output)
            click.echo(f"\nResults saved to: {output}")
        else:
            click.echo("\n" + json.dumps(result.to_json(), indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {str(e)}", err=True)
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
        click.echo(f"Error: {str(e)}", err=True)
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
        click.echo(f"Error: {str(e)}", err=True)
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
        result = validator.validate(rules, auto_approve_explicit=True)

        generate_html_report(result, output)
        click.echo(f"Report saved to: {output}")

    except FileNotFoundError as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
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
