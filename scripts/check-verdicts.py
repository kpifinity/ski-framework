#!/usr/bin/env python3
"""check-verdicts.py — print recent verdicts from the SKI Model.

Usage:
    python scripts/check-verdicts.py [--endpoint URL] [--api-key KEY] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default=os.getenv("SKI_MODEL_ENDPOINT", "https://localhost:8000"))
    p.add_argument("--api-key", default=os.getenv("SKI_API_KEY", ""))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--insecure", action="store_true")
    args = p.parse_args()

    headers = {"x-api-key": args.api_key} if args.api_key else {}
    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        resp = client.get(
            args.endpoint.rstrip("/") + "/api/verdicts",
            params={"limit": args.limit, "offset": args.offset},
            headers=headers,
        )
        resp.raise_for_status()
        json.dump(resp.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
