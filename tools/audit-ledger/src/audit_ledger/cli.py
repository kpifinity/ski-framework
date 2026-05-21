"""
Command-line interface for Audit Ledger Tool
"""

import click
import os
from datetime import datetime
from tabulate import tabulate
from .ledger import Ledger
from .models import ExportResult


@click.group()
@click.version_option(version="1.0.0")
def main():
    """Audit Ledger Tool - Manage SKI Framework compliance ledger"""
    pass


@main.command()
@click.option(
    "--ledger-db",
    required=True,
    help="PostgreSQL connection string (e.g., postgresql://user:pass@localhost/ledger)",
    envvar="LEDGER_DB"
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Show detailed verification output"
)
@click.option(
    "--check-timestamps",
    is_flag=True,
    help="Verify timestamp ordering"
)
@click.option(
    "--output",
    help="Write results to file"
)
def verify(ledger_db, verbose, check_timestamps, output):
    """Verify ledger integrity and hash chain validity"""
    try:
        ledger = Ledger(ledger_db)
        result = ledger.verify_integrity(verbose=verbose)

        # Format output
        output_lines = []
        output_lines.append("Ledger Integrity Verification")
        output_lines.append("=" * 40)
        output_lines.append(f"Total entries: {result.total_entries}")
        output_lines.append(f"Chain integrity: {'✓ VERIFIED' if result.chain_continuity else '✗ BROKEN'}")
        output_lines.append(f"Hash verification: ✓ {result.hash_verification_count}/{result.hash_verification_total} valid")
        output_lines.append(f"Timestamp order: {'✓ VALID' if result.timestamp_ordering else '✗ INVALID'}")
        output_lines.append(f"Data consistency: {'✓ VALID' if result.data_consistency else '✗ INVALID'}")
        output_lines.append("")
        output_lines.append("Verdict Distribution:")
        for verdict, count in result.verdict_distribution.items():
            output_lines.append(f"  {verdict}: {count}")
        output_lines.append("")
        output_lines.append(f"Status: {'✓ VALID' if result.is_valid else '✗ INVALID'}")
        output_lines.append(f"Recommendation: {result.recommendation}")

        output_text = "\n".join(output_lines)
        click.echo(output_text)

        if output:
            with open(output, "w") as f:
                f.write(output_text)
            click.echo(f"\nResults written to {output}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Exit(1)


@main.command()
@click.option(
    "--source",
    required=True,
    help="PostgreSQL connection string",
    envvar="LEDGER_DB"
)
@click.option(
    "--output",
    required=True,
    help="Output file path"
)
@click.option(
    "--format",
    type=click.Choice(["json", "csv", "jsonl"]),
    default="json",
    help="Output format (default: json)"
)
@click.option(
    "--fields",
    help="Comma-separated field names to include"
)
@click.option(
    "--date-range",
    help="Start,end dates (YYYY-MM-DD,YYYY-MM-DD)"
)
@click.option(
    "--verdict-filter",
    type=click.Choice(["CLEAR", "FLAG", "NULL", "DISCRETIONARY"]),
    help="Filter by verdict"
)
@click.option(
    "--rule-id",
    help="Filter by rule ID"
)
@click.option(
    "--limit",
    type=int,
    help="Maximum entries to export"
)
def export(source, output, format, fields, date_range, verdict_filter, rule_id, limit):
    """Export ledger entries for analysis"""
    try:
        ledger = Ledger(source)

        # Parse date range
        start_date = None
        end_date = None
        if date_range:
            parts = date_range.split(",")
            start_date = parts[0] if len(parts) > 0 else None
            end_date = parts[1] if len(parts) > 1 else None

        # Parse fields
        field_list = None
        if fields:
            field_list = [f.strip() for f in fields.split(",")]

        result = ledger.export_entries(
            output_file=output,
            format=format,
            start_date=start_date,
            end_date=end_date,
            verdict_filter=verdict_filter,
            rule_id_filter=rule_id,
            fields=field_list,
            limit=limit,
        )

        click.echo(f"Exported {result.entry_count} entries to {output}")
        click.echo(f"File size: {result.size_bytes} bytes")
        click.echo(f"Format: {result.file_format}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Exit(1)


@main.command()
@click.option(
    "--source",
    required=True,
    help="PostgreSQL connection string",
    envvar="LEDGER_DB"
)
@click.option(
    "--output",
    required=True,
    help="Output HTML file path"
)
@click.option(
    "--start-date",
    required=True,
    help="Report start date (YYYY-MM-DD)"
)
@click.option(
    "--end-date",
    required=True,
    help="Report end date (YYYY-MM-DD)"
)
@click.option(
    "--include-verdicts",
    is_flag=True,
    help="Include verdict summary"
)
@click.option(
    "--include-violations",
    is_flag=True,
    help="Include violation details"
)
@click.option(
    "--include-timeline",
    is_flag=True,
    help="Include timeline visualization"
)
@click.option(
    "--title",
    default="Compliance Report",
    help="Report title"
)
@click.option(
    "--organization",
    default="Organization",
    help="Organization name"
)
def report(source, output, start_date, end_date, include_verdicts,
           include_violations, include_timeline, title, organization):
    """Generate compliance report from ledger data"""
    try:
        ledger = Ledger(source)
        result = ledger.generate_report(
            start_date=start_date,
            end_date=end_date,
            include_verdicts=include_verdicts,
            include_violations=include_violations,
            include_timeline=include_timeline,
            organization=organization
        )

        # Generate HTML report
        html = _generate_html_report(result, title)

        with open(output, "w") as f:
            f.write(html)

        click.echo(f"Report generated: {output}")
        click.echo(f"Organization: {organization}")
        click.echo(f"Period: {start_date} to {end_date}")
        click.echo(f"Total verdicts: {result.total_entries_analyzed}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Exit(1)


@main.command()
@click.option(
    "--source",
    required=True,
    help="PostgreSQL connection string",
    envvar="LEDGER_DB"
)
@click.option(
    "--output",
    required=True,
    help="Output file path"
)
@click.option(
    "--compress",
    is_flag=True,
    help="Gzip compress the backup"
)
@click.option(
    "--verify",
    is_flag=True,
    help="Verify backup integrity"
)
def backup(source, output, compress, verify):
    """Create backup of ledger database"""
    try:
        ledger = Ledger(source)
        result = ledger.backup_database(
            output_file=output,
            compress=compress,
            verify=verify
        )

        click.echo(f"Backup created: {output}")
        click.echo(f"Backup date: {result.backup_date}")
        click.echo(f"Compressed: {result.compressed}")
        click.echo(f"Verified: {result.verified}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Exit(1)


def _generate_html_report(result, title):
    """Generate HTML report"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 20px; }}
            .section {{ margin-bottom: 30px; }}
            .section h2 {{ background-color: #f0f0f0; padding: 10px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f0f0f0; }}
            .verdict-clear {{ color: green; }}
            .verdict-flag {{ color: red; }}
            .verdict-discretionary {{ color: orange; }}
            .verdict-null {{ color: gray; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>{title}</h1>
            <p><strong>Organization:</strong> {result.organization}</p>
            <p><strong>Period:</strong> {result.start_date.date()} to {result.end_date.date()}</p>
            <p><strong>Generated:</strong> {result.report_date}</p>
        </div>

        <div class="section">
            <h2>Verdict Summary</h2>
            <table>
                <tr>
                    <th>Verdict</th>
                    <th>Count</th>
                    <th>Percentage</th>
                </tr>
                <tr>
                    <td class="verdict-clear">CLEAR</td>
                    <td>{result.verdict_summary.clear}</td>
                    <td>{result.verdict_summary.clear_percent:.1f}%</td>
                </tr>
                <tr>
                    <td class="verdict-flag">FLAG</td>
                    <td>{result.verdict_summary.flag}</td>
                    <td>{result.verdict_summary.flag_percent:.1f}%</td>
                </tr>
                <tr>
                    <td class="verdict-discretionary">DISCRETIONARY</td>
                    <td>{result.verdict_summary.discretionary}</td>
                    <td>{result.verdict_summary.discretionary_percent:.1f}%</td>
                </tr>
                <tr>
                    <td class="verdict-null">NULL</td>
                    <td>{result.verdict_summary.null}</td>
                    <td>{result.verdict_summary.null_percent:.1f}%</td>
                </tr>
            </table>
        </div>

        <div class="section">
            <h2>Analysis</h2>
            <p><strong>Total Entries Analyzed:</strong> {result.total_entries_analyzed}</p>
            <p><strong>Compliance Status:</strong>
                {('✓ COMPLIANT' if result.verdict_summary.flag == 0 else '⚠ ISSUES DETECTED')}
            </p>
        </div>

        <div class="section">
            <p><em>Generated by SKI Framework Audit Ledger Tool</em></p>
        </div>
    </body>
    </html>
    """
    return html


@main.group()
def examples():
    """Show example commands"""
    pass


@examples.command()
def verify_ledger():
    """Example: Verify ledger integrity"""
    click.echo("""
    audit-ledger verify \\
        --ledger-db postgresql://user:pass@localhost/ski_ledger \\
        --verbose
    """)


@examples.command()
def export_violations():
    """Example: Export violations"""
    click.echo("""
    audit-ledger export \\
        --source postgresql://user:pass@localhost/ski_ledger \\
        --output violations.json \\
        --format json \\
        --verdict-filter FLAG
    """)


@examples.command()
def generate_report():
    """Example: Generate monthly report"""
    click.echo("""
    audit-ledger report \\
        --source postgresql://user:pass@localhost/ski_ledger \\
        --start-date 2026-05-01 \\
        --end-date 2026-05-31 \\
        --output may-report.html \\
        --include-verdicts \\
        --include-violations \\
        --organization "Acme Corp"
    """)


if __name__ == "__main__":
    main()
