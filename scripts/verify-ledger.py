#!/usr/bin/env python3
"""verify-ledger.py — re-verify the audit ledger end-to-end.

Recomputes the entry hash for every row in `ledger_entries` from the
canonical serialization documented in
`tools/audit-ledger/src/audit_ledger/canonical.py` and reports any
divergence. Connects via the LEDGER_DSN environment variable or --dsn.
"""
from __future__ import annotations

import argparse
import os
import sys

# Allow running from the repo root without installing the tool.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "audit-ledger" / "src"))

from audit_ledger.ledger import Ledger  # noqa: E402  (sys.path mutation above)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", default=os.getenv("LEDGER_DSN", ""))
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any WARNING is reported.")
    args = p.parse_args()
    if not args.dsn:
        print("error: provide LEDGER_DSN env var or --dsn", file=sys.stderr)
        return 2

    ledger = Ledger(args.dsn)
    result = ledger.verify_integrity()

    print(f"Total entries:                {result.total_entries}")
    print(f"Sequence range:               {result.sequence_range}")
    print(f"Time range:                   {result.time_range}")
    print(f"Chain linkage verified:       {result.chain_link_verified_count} / {result.hash_verification_total}")
    print(f"Entry hash recomputed:        {result.entry_hash_verified_count} / {result.hash_verification_total}")
    print(f"Sequence continuity:          {result.chain_continuity}")
    print(f"Timestamp ordering:           {result.timestamp_ordering}")
    print(f"\nRecommendation:")
    print(f"  {result.recommendation}")

    if result.issues:
        print("\nIssues:")
        for issue in result.issues:
            print(f"  [{issue.severity}] {issue.issue_type} @ seq={issue.sequence_number}: {issue.description}")

    if not result.is_valid:
        return 1
    if args.strict and result.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
