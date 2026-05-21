#!/usr/bin/env python3

"""
Load Knowledge Graph - Load validated Knowledge Graph into running MiLM
"""

import json
import sys
import argparse
import requests


def main():
    parser = argparse.ArgumentParser(description="Load Knowledge Graph into MiLM")
    parser.add_argument("kg_file", help="Knowledge Graph JSON file to load")
    parser.add_argument("--endpoint", "-e", default="http://localhost:8000",
                       help="MiLM endpoint (default: http://localhost:8000)")
    parser.add_argument("--verify", action="store_true", help="Verify Knowledge Graph before loading")

    args = parser.parse_args()

    # Load KG file
    print(f"\n📚 Loading Knowledge Graph\n")
    print(f"File: {args.kg_file}")
    print(f"Endpoint: {args.endpoint}\n")

    try:
        with open(args.kg_file, "r") as f:
            kg_data = json.load(f)
    except FileNotFoundError:
        print(f"✗ File not found: {args.kg_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        sys.exit(1)

    # Verify KG structure if requested
    if args.verify:
        print("🔍 Verifying Knowledge Graph structure...")
        if "rules" not in kg_data:
            print("✗ Invalid Knowledge Graph: missing 'rules' array")
            sys.exit(1)

        rules = kg_data.get("rules", [])
        required_fields = ["id", "subject", "relation", "object", "source_document"]

        errors = 0
        for rule in rules:
            for field in required_fields:
                if field not in rule:
                    print(f"✗ Rule {rule.get('id', 'unknown')}: missing field '{field}'")
                    errors += 1

        if errors > 0:
            print(f"✗ Validation failed with {errors} errors")
            sys.exit(1)

        print(f"✓ Knowledge Graph is valid")

    # Check MiLM health
    print("\n🔍 Checking MiLM health...")
    try:
        response = requests.get(f"{args.endpoint}/api/health", timeout=5)
        health = response.json()
        print(f"✓ MiLM is running")
    except Exception as e:
        print(f"✗ Cannot connect to MiLM: {e}")
        print("  Make sure MiLM is running: docker-compose up -d")
        sys.exit(1)

    # Load Knowledge Graph
    print(f"\n📤 Loading Knowledge Graph...")
    try:
        response = requests.post(
            f"{args.endpoint}/api/kg/load",
            json=kg_data,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

        print(f"✓ Knowledge Graph loaded successfully")
        print(f"  Rules loaded: {result.get('rules_loaded', 0)}")
        print(f"  Version: {result.get('version', 'unknown')}")

    except requests.exceptions.HTTPError as e:
        print(f"✗ Failed to load Knowledge Graph: {e}")
        print(f"  Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

    # Verify loading
    print(f"\n✓ Knowledge Graph is now active")
    print(f"  Status: curl {args.endpoint}/api/status")
    print(f"  Submit telemetry: python3 scripts/test-verdict.py")


if __name__ == "__main__":
    main()
