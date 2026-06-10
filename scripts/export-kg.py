#!/usr/bin/env python3
"""export-kg.py — dump the currently-loaded Knowledge Graph to stdout.

Usage:
    python scripts/export-kg.py [--endpoint URL] [--api-key KEY] > kg-backup.json

The exported JSON contains the loaded KG (metadata, nodes, edges) and signature
block exactly as loaded. It can be re-loaded via POST /api/kg/load on any
SKI Model instance with the same signing public key configured.
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
    p.add_argument("--insecure", action="store_true")
    args = p.parse_args()

    headers = {"x-api-key": args.api_key} if args.api_key else {}
    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        resp = client.get(args.endpoint.rstrip("/") + "/api/kg", headers=headers)
        # /api/kg is alpha; fall back to health for KG version if absent.
        if resp.status_code == 404:
            health = client.get(args.endpoint.rstrip("/") + "/api/health", headers=headers).json()
            print(json.dumps({"note": "this build does not expose /api/kg yet", "health": health}, indent=2))
            return 0
        resp.raise_for_status()
        json.dump(resp.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
