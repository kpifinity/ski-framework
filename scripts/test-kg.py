#!/usr/bin/env python3

"""
Test Knowledge Graph - Validate Knowledge Graph schema and structure
"""

import argparse
import json
import sys


def validate_rule(rule):
    """Validate a single rule"""
    errors = []
    warnings = []

    # Check required fields
    required_fields = [
        "id",
        "subject",
        "relation",
        "object",
        "source_document",
        "source_clause",
        "confidence",
        "reasoning",
    ]

    for field in required_fields:
        if field not in rule:
            errors.append(f"Missing required field: {field}")
        elif not rule[field] or not str(rule[field]).strip():
            errors.append(f"Empty required field: {field}")

    # Check confidence level
    if "confidence" in rule:
        valid_levels = ["EXPLICIT", "IMPLIED", "DISCRETIONARY", "CONFLICTING"]
        if rule["confidence"] not in valid_levels:
            errors.append(f"Invalid confidence level: {rule['confidence']}")

    # Check for overly vague language
    vague_words = ["may", "might", "possibly", "apparently", "seems"]
    subject_text = str(rule.get("subject", "")).lower()
    relation_text = str(rule.get("relation", "")).lower()
    object_text = str(rule.get("object", "")).lower()

    combined = f"{subject_text} {relation_text} {object_text}"
    for word in vague_words:
        if word in combined:
            warnings.append(f"Vague language detected: '{word}'")

    return errors, warnings


def check_for_conflicts(rules):
    """Check for conflicting rules"""
    conflicts = []

    for i, rule1 in enumerate(rules):
        for rule2 in rules[i + 1 :]:
            # Check if same subject-relation pair with different objects
            if (
                rule1.get("subject", "").lower() == rule2.get("subject", "").lower()
                and rule1.get("relation", "").lower() == rule2.get("relation", "").lower()
                and rule1.get("object", "").lower() != rule2.get("object", "").lower()
            ):
                conflicts.append(
                    {
                        "rule1": rule1.get("id"),
                        "rule2": rule2.get("id"),
                        "reason": "Conflicting objects for same subject-relation pair",
                    }
                )

    return conflicts


def check_for_duplicates(rules):
    """Check for duplicate rules"""
    duplicates = []
    seen = {}

    for rule in rules:
        key = (
            rule.get("subject", "").lower(),
            rule.get("relation", "").lower(),
            rule.get("object", "").lower(),
        )

        if key in seen:
            duplicates.append(
                {"rule1": seen[key], "rule2": rule.get("id"), "reason": "Identical subject-relation-object"}
            )
        else:
            seen[key] = rule.get("id")

    return duplicates


def main():
    parser = argparse.ArgumentParser(description="Validate Knowledge Graph")
    parser.add_argument("file", help="Knowledge Graph JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--fix-duplicates", action="store_true", help="Remove duplicates")

    args = parser.parse_args()

    # Load file
    try:
        with open(args.file) as f:
            kg_data = json.load(f)
    except FileNotFoundError:
        print(f"✗ File not found: {args.file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        sys.exit(1)

    # Validate structure
    print(f"\n📋 Validating Knowledge Graph: {args.file}\n")

    if "rules" not in kg_data:
        print("✗ No 'rules' array found in Knowledge Graph")
        sys.exit(1)

    rules = kg_data["rules"]
    print(f"Total rules: {len(rules)}\n")

    # Validate each rule
    total_errors = 0
    total_warnings = 0

    for rule in rules:
        errors, warnings = validate_rule(rule)

        if errors:
            print(f"✗ Rule {rule.get('id', 'unknown')}:")
            for error in errors:
                print(f"  - {error}")
            total_errors += len(errors)

        if warnings and args.verbose:
            print(f"⚠ Rule {rule.get('id', 'unknown')}:")
            for warning in warnings:
                print(f"  - {warning}")
            total_warnings += len(warnings)

    # Check for conflicts
    print("\n🔍 Checking for conflicts...")
    conflicts = check_for_conflicts(rules)
    if conflicts:
        print(f"Found {len(conflicts)} potential conflicts:")
        for conflict in conflicts:
            print(f"  - {conflict['rule1']} vs {conflict['rule2']}: {conflict['reason']}")
        total_errors += len(conflicts)
    else:
        print("✓ No conflicts detected")

    # Check for duplicates
    print("\n🔍 Checking for duplicates...")
    duplicates = check_for_duplicates(rules)
    if duplicates:
        print(f"Found {len(duplicates)} duplicate rules:")
        for dup in duplicates:
            print(f"  - {dup['rule1']} vs {dup['rule2']}: {dup['reason']}")
        total_warnings += len(duplicates)

        if args.fix_duplicates:
            print("Removing duplicates...")
            # Keep only first occurrence
            seen = set()
            filtered_rules = []
            for rule in rules:
                key = (rule.get("subject", ""), rule.get("relation", ""), rule.get("object", ""))
                if key not in seen:
                    filtered_rules.append(rule)
                    seen.add(key)

            kg_data["rules"] = filtered_rules
            with open(args.file, "w") as f:
                json.dump(kg_data, f, indent=2)
            print(f"✓ Removed {len(duplicates)} duplicates. Knowledge Graph updated.")
    else:
        print("✓ No duplicates detected")

    # Summary
    print("\n" + "=" * 50)
    print(f"Errors: {total_errors}")
    print(f"Warnings: {total_warnings}")
    print(f"Rules validated: {len(rules)}")
    print("=" * 50)

    if total_errors > 0:
        print("\n✗ Validation failed")
        sys.exit(1)
    else:
        print("\n✓ Knowledge Graph is valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
