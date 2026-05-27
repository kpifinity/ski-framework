"""
Command-line interface for KG Extractor
"""

import json
import os
from typing import Optional

import click

from .extractor import Extractor


@click.group()
def main():
    """Extract compliance rules from regulatory documents"""


@main.command()
@click.option("--file", "-f", required=True, help="Input document file")
@click.option(
    "--sector", "-s", default="general", help="Industry sector (energy, finance, manufacturing, defense)"
)
@click.option("--output", "-o", default=None, help="Output JSON file (default: stdout)")
@click.option("--document-type", "-t", default="regulation", help="Type of document")
def extract(file: str, sector: str, output: Optional[str], document_type: str):
    """Extract rules from a document"""
    try:
        click.echo(f"Extracting rules from: {file}")

        extractor = Extractor()
        result = extractor.extract_from_file(
            file_path=file,
            sector=sector,
            document_type=document_type,
        )

        # Prepare output
        output_data = result.to_json()

        # Print summary
        click.echo("\nExtraction complete:")
        click.echo(f"  Total rules: {result.metadata.total_rules_extracted}")
        click.echo(f"  Duration: {result.metadata.extraction_duration_seconds:.2f} seconds")
        click.echo("  Confidence breakdown:")

        for confidence, count in result.metadata.rules_by_confidence.items():
            click.echo(f"    {confidence}: {count}")

        # Output results
        if output:
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)
            click.echo(f"\nResults saved to: {output}")
        else:
            click.echo("\n" + json.dumps(output_data, indent=2))

        # Print warnings if any
        if result.warnings:
            click.echo("\nWarnings:")
            for warning in result.warnings:
                click.echo(f"  ⚠️  {warning}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--input-dir", "-i", required=True, help="Directory with document files")
@click.option("--output-dir", "-o", required=True, help="Output directory for results")
@click.option("--sector", "-s", default="general", help="Industry sector")
def batch(input_dir: str, output_dir: str, sector: str):
    """Extract rules from multiple documents"""
    try:
        if not os.path.exists(input_dir):
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        os.makedirs(output_dir, exist_ok=True)

        extractor = Extractor()
        files = [f for f in os.listdir(input_dir) if f.endswith((".txt", ".pdf", ".html", ".docx"))]

        if not files:
            click.echo(f"No document files found in: {input_dir}")
            return

        click.echo(f"Processing {len(files)} files...")

        for i, filename in enumerate(files, 1):
            try:
                filepath = os.path.join(input_dir, filename)
                click.echo(f"  [{i}/{len(files)}] {filename}...", nl=False)

                result = extractor.extract_from_file(
                    file_path=filepath,
                    sector=sector,
                )

                # Save output
                output_filename = f"{os.path.splitext(filename)[0]}-rules.json"
                output_path = os.path.join(output_dir, output_filename)

                with open(output_path, "w") as f:
                    json.dump(result.to_json(), f, indent=2)

                click.echo(f" ✓ {result.metadata.total_rules_extracted} rules")

            except Exception as e:
                click.echo(f" ✗ Error: {e!s}")

        click.echo(f"\nResults saved to: {output_dir}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--confidence", "-c", default="DISCRETIONARY", help="Filter by confidence level")
@click.option("--input", "-i", required=True, help="Input JSON file with extracted rules")
@click.option("--output", "-o", default=None, help="Output file for filtered rules")
def filter(confidence: str, input: str, output: Optional[str]):
    """Filter rules by confidence level"""
    try:
        with open(input) as f:
            data = json.load(f)

        rules = data.get("rules", [])
        filtered = [r for r in rules if r.get("confidence") == confidence]

        click.echo(f"Filtered {len(filtered)}/{len(rules)} rules with confidence: {confidence}")

        if output:
            with open(output, "w") as f:
                json.dump({"rules": filtered}, f, indent=2)
            click.echo(f"Results saved to: {output}")
        else:
            click.echo(json.dumps({"rules": filtered}, indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {input}: {e!s}", err=True)
        raise SystemExit(1)


@main.command()
def examples():
    """Show usage examples"""
    examples_text = """
KG Extractor Examples:

1. Extract rules from a single document:
   kg-extractor extract --file regulation.txt --sector energy

2. Extract and save to JSON:
   kg-extractor extract --file law.pdf --sector finance --output rules.json

3. Batch process multiple documents:
   kg-extractor batch --input-dir ./regulations --output-dir ./extracted --sector energy

4. Filter rules by confidence level:
   kg-extractor filter --input rules.json --confidence EXPLICIT --output explicit-only.json

5. Using Python API:
   from kg_extractor import Extractor

   extractor = Extractor()
   result = extractor.extract_from_file("regulation.txt", sector="energy")

   for rule in result.rules:
       print(f"{rule.subject} {rule.relation} {rule.object}")
"""
    click.echo(examples_text)


@main.command()
def version():
    """Show version"""
    from . import __version__

    click.echo(f"kg-extractor {__version__}")


if __name__ == "__main__":
    main()
