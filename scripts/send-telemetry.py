#!/usr/bin/env python3
"""send-telemetry.py — replay a JSONL telemetry file through the sidecar.

Usage:
    python scripts/send-telemetry.py PATH [--endpoint URL] [--api-key KEY] [--insecure]

Reads one JSON object per line from PATH and POSTs each to the sidecar's
/api/telemetry endpoint. Records that include a `rule_id` will be REJECTED
client-side — the architecture forbids the producer telling the engine
which rule to apply (B4.3 Tag Registry).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path, help="JSONL telemetry file to replay")
    p.add_argument("--endpoint", default=os.getenv("SIDECAR_ENDPOINT", "http://localhost:8001"))
    p.add_argument(
        "--ski-endpoint",
        default=os.getenv("SKI_MODEL_ENDPOINT", "https://localhost:8000"),
        help="If set, posts directly to the SKI Model /api/evaluate endpoint instead of the sidecar.",
    )
    p.add_argument("--direct", action="store_true", help="POST directly to SKI Model.")
    p.add_argument("--api-key", default=os.getenv("SKI_API_KEY", ""))
    p.add_argument("--insecure", action="store_true", help="Disable TLS verification (self-signed certs).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.path.exists():
        print(f"error: {args.path} does not exist", file=sys.stderr)
        return 2

    headers: dict[str, str] = {}
    if args.api_key:
        headers["x-api-key"] = args.api_key

    if args.direct:
        url = args.ski_endpoint.rstrip("/") + "/api/evaluate"
    else:
        url = args.endpoint.rstrip("/") + "/api/telemetry"

    verify: bool | str = not args.insecure
    sent = 0
    rejected = 0
    with httpx.Client(timeout=30.0, verify=verify) as client, args.path.open() as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"line {line_no}: invalid JSON ({exc}); skipping", file=sys.stderr)
                continue

            if "rule_id" in record:
                rejected += 1
                print(
                    f"line {line_no}: REJECTED — telemetry record contains 'rule_id'. "
                    "Producers must not pre-route to a rule; the Tag Registry resolves "
                    "subject→rule. (See spec B4.3.)",
                    file=sys.stderr,
                )
                continue

            try:
                resp = client.post(url, json=record, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"line {line_no}: HTTP error: {exc}", file=sys.stderr)
                continue
            print(json.dumps(resp.json()))
            sent += 1

    print(f"\nSent: {sent}    Rejected (client-side): {rejected}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
