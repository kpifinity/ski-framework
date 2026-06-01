"""Command-line interface for kg-extractor (v3).

The extractor reads a regulatory document, asks the configured LLM
backend to produce a flat rule list, then wraps the rules into a
v3 KG JSON file ready to be consumed by ``kg-validator`` and the
SKI Model runtime.

PR 10e — v2-only paths retired:

* ``extract`` and ``batch`` now emit v3 KG JSON by default.
* The ``filter --confidence`` subcommand is renamed ``filter
  --quality`` to reflect the ``ExtractionQuality`` rename (the field
  on the rule is no longer called ``confidence``).
"""

from __future__ import annotations

import json
import os
from typing import Optional

import click

from . import __version__
from .extractor import Extractor
from .v3_emitter import emit_v3_kg


@click.group()
def main() -> None:
    """Extract v3 KGs from regulatory documents."""


@main.command()
@click.option("--file", "-f", required=True, help="Input document file.")
@click.option(
    "--sector",
    "-s",
    default="general",
    help="Industry sector (energy, finance, manufacturing, defense).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output v3 KG JSON file (default: stdout).",
)
@click.option("--document-type", "-t", default="regulation", help="Type of document.")
@click.option(
    "--jurisdiction",
    "-j",
    default="global",
    show_default=True,
    help="Jurisdiction id for every rule in this run (e.g., 'us.federal', 'eu', 'global').",
)
@click.option(
    "--jurisdiction-name",
    default=None,
    help="Human-readable jurisdiction name (defaults to --jurisdiction).",
)
@click.option(
    "--emit-raw",
    is_flag=True,
    default=False,
    help="Emit the raw extractor output (flat rule list) instead of a v3 KG. For debugging only.",
)
def extract(
    file: str,
    sector: str,
    output: Optional[str],
    document_type: str,
    jurisdiction: str,
    jurisdiction_name: Optional[str],
    emit_raw: bool,
) -> None:
    """Extract rules from a document and emit a v3 KG."""
    try:
        click.echo(f"Extracting rules from: {file}")
        extractor = Extractor()
        result = extractor.extract_from_file(
            file_path=file,
            sector=sector,
            document_type=document_type,
        )

        click.echo("\nExtraction complete:")
        click.echo(f"  Total rules: {result.metadata.total_rules_extracted}")
        click.echo(f"  Duration: {result.metadata.extraction_duration_seconds:.2f} seconds")
        click.echo("  Extraction-quality breakdown:")
        for quality, count in result.metadata.rules_by_quality.items():
            click.echo(f"    {quality}: {count}")

        payload = (
            result.to_json()
            if emit_raw
            else emit_v3_kg(
                result,
                jurisdiction=jurisdiction,
                jurisdiction_name=jurisdiction_name,
                sector=sector,
            )
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            click.echo(f"\nResults saved to: {output}")
        else:
            click.echo("\n" + json.dumps(payload, indent=2))

        if result.warnings:
            click.echo("\nWarnings:")
            for warning in result.warnings:
                click.echo(f"  - {warning}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except ValueError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e


@main.command()
@click.option("--input-dir", "-i", required=True, help="Directory with document files.")
@click.option("--output-dir", "-o", required=True, help="Output directory for v3 KG files.")
@click.option("--sector", "-s", default="general", help="Industry sector.")
@click.option(
    "--jurisdiction",
    "-j",
    default="global",
    show_default=True,
    help="Jurisdiction id applied to every KG produced in this batch.",
)
def batch(input_dir: str, output_dir: str, sector: str, jurisdiction: str) -> None:
    """Extract v3 KGs from multiple documents."""
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

                kg_payload = emit_v3_kg(result, jurisdiction=jurisdiction, sector=sector)

                output_filename = f"{os.path.splitext(filename)[0]}-kg-v3.json"
                output_path = os.path.join(output_dir, output_filename)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(kg_payload, f, indent=2)

                click.echo(f" OK {result.metadata.total_rules_extracted} rules")

            except Exception as e:
                click.echo(f" FAIL: {e!s}")

        click.echo(f"\nResults saved to: {output_dir}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except Exception as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e


@main.command()
@click.option(
    "--quality",
    "-q",
    default="DISCRETIONARY",
    show_default=True,
    type=click.Choice(["EXPLICIT", "DISCRETIONARY", "CONFLICTING"], case_sensitive=False),
    help="Extraction quality to filter on.",
)
@click.option(
    "--input",
    "-i",
    required=True,
    help="Input flat-rule JSON file (the --emit-raw output of `extract`).",
)
@click.option("--output", "-o", default=None, help="Output file for filtered rules.")
def filter(quality: str, input: str, output: Optional[str]) -> None:
    """Filter raw extracted rules by extraction quality."""
    try:
        with open(input, encoding="utf-8") as f:
            data = json.load(f)

        rules = data.get("rules", [])
        target = quality.upper()
        filtered = [r for r in rules if (r.get("extraction_quality") or "").upper() == target]

        click.echo(f"Filtered {len(filtered)}/{len(rules)} rules with extraction_quality: {target}")

        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump({"rules": filtered}, f, indent=2)
            click.echo(f"Results saved to: {output}")
        else:
            click.echo(json.dumps({"rules": filtered}, indent=2))

    except FileNotFoundError as e:
        click.echo(f"Error: {e!s}", err=True)
        raise SystemExit(1) from e
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {input}: {e!s}", err=True)
        raise SystemExit(1) from e


@main.command()
def examples() -> None:
    """Show usage examples."""
    examples_text = """
kg-extractor examples (v3):

1. Extract a v3 KG from a document:
   kg-extractor extract --file regulation.txt --sector energy \\
       --jurisdiction us.federal --output kg-extracted-v3.json

2. Validate the emitted KG:
   kg-validator validate --input kg-extracted-v3.json

3. Batch process multiple documents:
   kg-extractor batch --input-dir ./regulations --output-dir ./kgs \\
       --sector energy --jurisdiction us.federal

4. Inspect the raw flat rules (debugging only):
   kg-extractor extract --file regulation.txt --emit-raw --output flat-rules.json

5. Filter flat rules by extraction quality:
   kg-extractor filter --input flat-rules.json --quality EXPLICIT \\
       --output explicit-only.json

6. Python API:
   from kg_extractor import Extractor, emit_v3_kg

   extractor = Extractor()
   result = extractor.extract_from_file("regulation.txt", sector="energy")
   kg = emit_v3_kg(result, jurisdiction="us.federal", sector="energy")
"""
    click.echo(examples_text)


@main.command()
def version() -> None:
    """Show version."""
    click.echo(f"kg-extractor {__version__}")


if __name__ == "__main__":
    main()
