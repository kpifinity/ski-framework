#!/usr/bin/env python3
"""test-verdict.py — submit JSONL telemetry directly to the SKI Model and tally verdicts.

Rejects records that carry a `rule_id` — producers must not pre-route.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

VERDICT_KEYS = ("CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", "-e", default=os.getenv("SKI_MODEL_ENDPOINT", "https://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("SKI_API_KEY", ""))
    parser.add_argument("--telemetry", "-t", default="examples/energy/telemetry/sample.jsonl")
    parser.add_argument("--output", "-o", help="Write the verdicts to a JSON file.")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    headers = {"x-api-key": args.api_key} if args.api_key else {}

    if not os.path.exists(args.telemetry):
        print(f"✗ File not found: {args.telemetry}", file=sys.stderr)
        return 1

    records: list[dict] = []
    with open(args.telemetry) as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"✗ {args.telemetry}:{lineno}: invalid JSON ({exc})", file=sys.stderr)
                return 1
            if "rule_id" in rec:
                print(
                    f"✗ {args.telemetry}:{lineno}: contains a `rule_id` — "
                    "producers must not pre-route to a rule (B4.3).",
                    file=sys.stderr,
                )
                return 1
            records.append(rec)

    counts: dict[str, int] = dict.fromkeys(VERDICT_KEYS, 0)
    verdicts: list[dict] = []

    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        # Quick health probe.
        try:
            client.get(args.endpoint.rstrip("/") + "/api/health", headers=headers).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"✗ Cannot reach SKI Model: {exc}", file=sys.stderr)
            return 1

        for i, rec in enumerate(records, start=1):
            # Adapt the older sample format to the v2.1 contract:
            #   telemetry_id, timestamp, subject, measurement.
            payload = {
                "telemetry_id": rec.get("telemetry_id") or rec.get("id") or f"tel_{i}",
                "timestamp": rec.get("timestamp"),
                "subject": rec.get("subject"),
                "measurement": rec.get("measurement")
                or {k: v for k, v in rec.items() if k not in ("id", "timestamp", "subject", "telemetry_id")},
            }
            try:
                resp = client.post(args.endpoint.rstrip("/") + "/api/evaluate", json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"✗ {i}: HTTP error: {exc}", file=sys.stderr)
                continue
            v = resp.json()
            verdicts.append(v)
            counts[v.get("verdict", "")] = counts.get(v.get("verdict", ""), 0) + 1
            print(f"  [{i}/{len(records)}] {payload['subject']:<40} → {v.get('verdict')}")
            if args.verbose:
                print(f"        rule_id={v.get('rule_id')!r}  reasoning={v.get('reasoning')!r}")

    print("\n" + "=" * 50)
    print("Verdict summary")
    print("=" * 50)
    for v in VERDICT_KEYS:
        pct = (counts[v] / len(records) * 100) if records else 0
        print(f"  {v:<16} {counts[v]:>4}  ({pct:5.1f}%)")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"counts": counts, "verdicts": verdicts}, f, indent=2)
        print(f"\nResults written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
