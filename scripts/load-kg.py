#!/usr/bin/env python3
"""load-kg.py — POST a signed Knowledge Graph to a running SKI Model.

For the alpha this is a thin wrapper around /api/kg/load. Use
`ski-model-deploy load-kg` for production deployments — that tool also
verifies the signature locally before uploading.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kg_file", help="Knowledge Graph JSON file to load (must be signed).")
    parser.add_argument("--endpoint", "-e", default=os.getenv("SKI_MODEL_ENDPOINT", "https://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("SKI_API_KEY", ""))
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    try:
        with open(args.kg_file) as f:
            kg_data = json.load(f)
    except FileNotFoundError:
        print(f"✗ File not found: {args.kg_file}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"✗ Invalid JSON: {exc}", file=sys.stderr)
        return 1

    if "signature" not in kg_data:
        print("✗ Refusing to upload: KG has no `signature` block.", file=sys.stderr)
        print("  Sign with your production Ed25519 key first, or use ski-model-deploy.", file=sys.stderr)
        return 1

    headers = {"x-api-key": args.api_key} if args.api_key else {}

    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        # Check SKI Model health first.
        try:
            client.get(args.endpoint.rstrip("/") + "/api/health", headers=headers).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"✗ Cannot reach SKI Model: {exc}", file=sys.stderr)
            return 1

        try:
            resp = client.post(args.endpoint.rstrip("/") + "/api/kg/load", json=kg_data, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"✗ Load failed: {exc}", file=sys.stderr)
            if hasattr(exc, "response") and exc.response is not None:
                print(exc.response.text, file=sys.stderr)
            return 1

    result = resp.json()
    print(
        f"✓ Knowledge Graph loaded ({result.get('rules_loaded', 0)} rules, version={result.get('version')!r})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
