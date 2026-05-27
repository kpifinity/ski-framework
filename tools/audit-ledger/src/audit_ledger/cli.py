"""CLI for the audit-ledger tool.

v2.1 changes:
  * Five-verdict taxonomy in `--verdict-filter` (NULL → NULL_UNMAPPED, NULL_STALE).
  * `verify` reports entry-hash recomputation separately from chain
    linkage — these are different integrity checks.
  * `backup` actually invokes `pg_dump` and verifies with `pg_restore --list`.
"""

from __future__ import annotations

from typing import Optional

import click

from .ledger import Ledger

VERDICT_CHOICES = ["CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY"]


@click.group()
@click.version_option(version="0.1.0a0")
def main() -> None:
    """audit-ledger — manage SKI Framework compliance ledger."""


@main.command()
@click.option("--ledger-db", required=True, envvar="LEDGER_DSN", help="PostgreSQL connection string.")
@click.option("--verbose", is_flag=True)
@click.option("--output", help="Write a plain-text summary to file.")
def verify(ledger_db: str, verbose: bool, output: Optional[str]) -> None:
    """Verify ledger integrity: chain linkage AND entry-hash recomputation."""
    ledger = Ledger(ledger_db)
    result = ledger.verify_integrity(verbose=verbose)

    lines = [
        "Ledger integrity verification",
        "=" * 40,
        f"Total entries:                {result.total_entries}",
        f"Sequence range:               {result.sequence_range}",
        f"Time range:                   {result.time_range}",
        f"Sequence continuity:          {'OK' if result.chain_continuity else 'FAIL'}",
        f"Timestamp ordering:           {'OK' if result.timestamp_ordering else 'FAIL'}",
        f"Chain linkage verified:       {result.chain_link_verified_count} / {result.hash_verification_total}",
        f"Entry-hash recomputation:     {result.entry_hash_verified_count} / {result.hash_verification_total}",
        "",
        "Verdict distribution:",
    ]
    for v in VERDICT_CHOICES:
        lines.append(f"  {v}: {result.verdict_distribution.get(v, 0)}")

    lines += [
        "",
        f"Overall: {'PASS' if result.is_valid else 'FAIL'}",
        f"Recommendation: {result.recommendation}",
    ]

    if result.issues:
        lines.append("")
        lines.append("Issues:")
        for issue in result.issues:
            lines.append(
                f"  [{issue.severity}] {issue.issue_type} @ seq={issue.sequence_number}: {issue.description}"
            )

    out = "\n".join(lines)
    click.echo(out)
    if output:
        with open(output, "w") as f:
            f.write(out + "\n")
    if not result.is_valid:
        raise SystemExit(1)


@main.command()
@click.option("--source", required=True, envvar="LEDGER_DSN")
@click.option("--output", required=True)
@click.option("--format", "out_format", type=click.Choice(["json", "csv", "jsonl"]), default="json")
@click.option("--fields")
@click.option("--date-range", help='"YYYY-MM-DD,YYYY-MM-DD"')
@click.option("--verdict-filter", type=click.Choice(VERDICT_CHOICES))
@click.option("--rule-id")
@click.option("--limit", type=int)
def export(
    source: str,
    output: str,
    out_format: str,
    fields: Optional[str],
    date_range: Optional[str],
    verdict_filter: Optional[str],
    rule_id: Optional[str],
    limit: Optional[int],
) -> None:
    """Export ledger entries for analysis."""
    ledger = Ledger(source)
    start_date = end_date = None
    if date_range:
        parts = [s.strip() or None for s in date_range.split(",")]
        start_date = parts[0] if parts else None
        end_date = parts[1] if len(parts) > 1 else None
    field_list = [s.strip() for s in fields.split(",")] if fields else None

    result = ledger.export_entries(
        output_file=output,
        format=out_format,
        start_date=start_date,
        end_date=end_date,
        verdict_filter=verdict_filter,
        rule_id_filter=rule_id,
        fields=field_list,
        limit=limit,
    )
    click.echo(f"Exported {result.entry_count} entries → {output}")
    click.echo(f"Size: {result.size_bytes} bytes  SHA-256: {result.checksum}")


@main.command()
@click.option("--source", required=True, envvar="LEDGER_DSN")
@click.option("--output", required=True)
@click.option("--start-date", required=True)
@click.option("--end-date", required=True)
@click.option("--include-violations/--no-include-violations", default=True)
@click.option("--organization", default="Organization")
def report(
    source: str, output: str, start_date: str, end_date: str, include_violations: bool, organization: str
) -> None:
    """Generate an HTML compliance report from ledger data."""
    ledger = Ledger(source)
    result = ledger.generate_report(
        start_date=start_date,
        end_date=end_date,
        include_violations=include_violations,
        organization=organization,
    )
    with open(output, "w") as f:
        f.write(_html_report(result, "Compliance report"))
    click.echo(f"Report written to {output}")
    click.echo(f"Period: {start_date} → {end_date}")
    click.echo(f"Total entries analysed: {result.total_entries_analyzed}")


@main.command()
@click.option("--source", required=True, envvar="LEDGER_DSN")
@click.option("--output", "--out", required=True, help="pg_dump custom-format output path.")
@click.option("--compress/--no-compress", default=False)
@click.option("--verify/--no-verify", default=True, help="Run `pg_restore --list` after dump.")
def backup(source: str, output: str, compress: bool, verify: bool) -> None:
    """Create a real backup via pg_dump. No stub."""
    ledger = Ledger(source)
    result = ledger.backup_database(output_file=output, compress=compress, verify=verify)
    click.echo(f"Backup created:    {result.backup_file}")
    click.echo(f"Backup date:       {result.backup_date}")
    click.echo(f"Size:              {result.size_bytes} bytes")
    click.echo(f"Compressed:        {result.compressed}")
    click.echo(f"Verified:          {result.verified}")
    click.echo(f"SHA-256:           {result.checksum}")
    if result.verification_status:
        click.echo(f"Verification:      {result.verification_status}")


@main.command()
@click.option("--source", required=True, envvar="LEDGER_DSN")
@click.option(
    "--from-sequence",
    "from_sequence",
    required=True,
    type=int,
    help="Lowest sequence number to replay (inclusive).",
)
@click.option(
    "--to-sequence",
    "to_sequence",
    required=True,
    type=int,
    help="Highest sequence number to replay (inclusive).",
)
@click.option(
    "--kg-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Signed KG used during the original evaluation.",
)
@click.option("--tenant-id", default="default", show_default=True)
@click.option("--output", default=None, help="Optional path to write the JSON replay report.")
@click.option(
    "--strict/--no-strict", default=True, show_default=True, help="Exit non-zero on any verdict divergence."
)
def replay(
    source: str,
    from_sequence: int,
    to_sequence: int,
    kg_path: str,
    tenant_id: str,
    output: Optional[str],
    strict: bool,
) -> None:
    """v0.2.0 — replay ledger entries against the recorded KG and buffer.

    For every entry in [from-sequence, to-sequence] this command re-runs
    the Symbolic Evaluator against the telemetry buffer state at the
    entry's timestamp and compares the produced verdict to what was
    recorded. v0.1 ledger entries and Track 2 (LLM) entries are skipped
    with a note.
    """
    import json as _json

    from .replay import replay as run_replay

    report = run_replay(
        dsn=source,
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        kg_path=kg_path,
        tenant_id=tenant_id,
    )

    click.echo(
        f"Replay: {report.replayed_entries}/{report.total_entries} entries replayed, "
        f"{report.matched_entries} matched, {len(report.mismatches)} diverged, "
        f"{report.skipped_entries} skipped."
    )
    for note in report.notes[:5]:
        click.echo(f"  note: {note}")
    if len(report.notes) > 5:
        click.echo(f"  ... and {len(report.notes) - 5} more notes")
    if report.mismatches:
        click.echo("\nDivergences:")
        for m in report.mismatches[:10]:
            click.echo(
                f"  seq={m.sequence_number}: recorded={m.recorded_verdict} replayed={m.replayed_verdict} ({m.reason})"
            )
        if len(report.mismatches) > 10:
            click.echo(f"  ... and {len(report.mismatches) - 10} more")
    if output:
        with open(output, "w") as f:
            _json.dump(report.to_dict(), f, indent=2, default=str)
        click.echo(f"\nFull report: {output}")

    if strict and not report.is_clean:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# HTML report (5-verdict)
# ---------------------------------------------------------------------------


def _html_report(result, title: str) -> str:
    vs = result.verdict_summary
    rows = [
        ("CLEAR", vs.clear, vs.clear_percent, "verdict-clear"),
        ("FLAG", vs.flag, vs.flag_percent, "verdict-flag"),
        ("NULL_UNMAPPED", vs.null_unmapped, vs.null_unmapped_percent, "verdict-null"),
        ("NULL_STALE", vs.null_stale, vs.null_stale_percent, "verdict-null"),
        ("DISCRETIONARY", vs.discretionary, vs.discretionary_percent, "verdict-discretionary"),
    ]
    rows_html = "\n".join(
        f'<tr><td class="{cls}">{name}</td><td>{count}</td><td>{pct:.1f}%</td></tr>'
        for name, count, pct, cls in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:system-ui,Arial,sans-serif;margin:20px;}}
.header{{border-bottom:2px solid #333;padding-bottom:10px;margin-bottom:20px;}}
.section{{margin-bottom:30px;}}
.section h2{{background-color:#f0f0f0;padding:10px;}}
table{{border-collapse:collapse;width:100%;margin-top:10px;}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;}}
th{{background-color:#f0f0f0;}}
.verdict-clear{{color:green;}}
.verdict-flag{{color:red;}}
.verdict-discretionary{{color:orange;}}
.verdict-null{{color:gray;}}
</style></head><body>
<div class="header">
  <h1>{title}</h1>
  <p><strong>Organization:</strong> {result.organization}</p>
  <p><strong>Period:</strong> {result.start_date.date()} to {result.end_date.date()}</p>
  <p><strong>Generated:</strong> {result.report_date}</p>
</div>
<div class="section">
  <h2>Verdict summary</h2>
  <table>
    <tr><th>Verdict</th><th>Count</th><th>Percent</th></tr>
    {rows_html}
  </table>
</div>
<div class="section">
  <h2>Analysis</h2>
  <p><strong>Total entries analysed:</strong> {result.total_entries_analyzed}</p>
  <p><strong>Compliance status:</strong>
    {("CLEAR" if vs.flag == 0 else "BREACHES DETECTED")}
  </p>
</div>
<div class="section">
  <p><em>Generated by audit-ledger (SKI Framework v2.1).</em></p>
</div>
</body></html>
"""


if __name__ == "__main__":  # pragma: no cover
    main()
