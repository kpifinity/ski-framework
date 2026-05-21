#!/usr/bin/env python3

"""
Test Verdicts - Submit telemetry and test verdict results
"""

import json
import sys
import argparse
import requests
from pathlib import Path


def load_telemetry(file_path):
    """Load telemetry from JSONL file"""
    telemetry = []

    try:
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    telemetry.append(json.loads(line))
    except FileNotFoundError:
        print(f"✗ File not found: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON in {file_path}: {e}")
        sys.exit(1)

    return telemetry


def submit_telemetry(endpoint, telemetry):
    """Submit telemetry to MiLM and get verdict"""
    try:
        response = requests.post(
            f"{endpoint}/api/evaluate",
            json=telemetry,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print(f"✗ Connection refused: {endpoint}")
        print("  Is MiLM running? Check: curl http://localhost:8000/api/health")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"✗ Request timeout: {endpoint}")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"✗ HTTP Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Test verdict evaluation")
    parser.add_argument("--endpoint", "-e", default="http://localhost:8000",
                       help="MiLM endpoint (default: http://localhost:8000)")
    parser.add_argument("--telemetry", "-t", default="examples/telemetry/sample-data.jsonl",
                       help="Telemetry JSONL file")
    parser.add_argument("--output", "-o", help="Output file for results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Load telemetry
    print(f"\n📊 Testing Verdicts\n")
    print(f"MiLM Endpoint: {args.endpoint}")
    print(f"Telemetry File: {args.telemetry}\n")

    telemetry_records = load_telemetry(args.telemetry)
    print(f"Loaded {len(telemetry_records)} telemetry records")

    # Check MiLM health
    print(f"\n🔍 Checking MiLM health...")
    try:
        response = requests.get(f"{args.endpoint}/api/health", timeout=5)
        health = response.json()
        print(f"✓ MiLM is running")
        print(f"  Knowledge Graph loaded: {health.get('kg_loaded')}")
        print(f"  Verdicts produced: {health.get('verdicts_produced')}")
    except Exception as e:
        print(f"✗ MiLM health check failed: {e}")
        print("  Make sure MiLM is running: docker-compose up -d")
        sys.exit(1)

    # Submit telemetry and get verdicts
    print(f"\n📬 Submitting telemetry...\n")

    verdicts = []
    verdict_counts = {"CLEAR": 0, "FLAG": 0, "NULL": 0, "DISCRETIONARY": 0}

    for i, telemetry in enumerate(telemetry_records, 1):
        print(f"  [{i}/{len(telemetry_records)}] Evaluating: {telemetry.get('subject')}", end="")

        verdict = submit_telemetry(args.endpoint, telemetry)
        verdicts.append(verdict)

        verdict_type = verdict.get("verdict", "UNKNOWN")
        verdict_counts[verdict_type] = verdict_counts.get(verdict_type, 0) + 1

        print(f" → {verdict_type}")

        if args.verbose:
            print(f"        Reasoning: {verdict.get('reasoning')}")

    # Summary
    print("\n" + "=" * 50)
    print("Verdict Summary:")
    print("=" * 50)
    for verdict_type, count in verdict_counts.items():
        percentage = (count / len(telemetry_records) * 100) if telemetry_records else 0
        print(f"{verdict_type:15} {count:3} ({percentage:5.1f}%)")

    # Save results if requested
    if args.output:
        results = {
            "total_verdicts": len(verdicts),
            "verdict_counts": verdict_counts,
            "verdicts": verdicts,
            "endpoint": args.endpoint
        }

        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\n✓ Results saved to: {args.output}")

    print("\n✓ Verdict testing complete")


if __name__ == "__main__":
    main()
