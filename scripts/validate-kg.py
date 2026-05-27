#!/usr/bin/env python3
"""validate-kg.py — static validation of a signed Knowledge Graph file.

Checks:
  * signature is present and verifies under the embedded public key (Ed25519);
  * every tag_registry entry references an existing rule_id;
  * every rule has a `track` field (symbolic|llm);
  * symbolic rules carry a structured `predicate` with required fields;
  * no rule has `confidence: "IMPLIED"` (B2.1 Anchor Constraint);
  * effective_date and (optionally) sunset_date are ISO-8601;
  * no duplicate rule ids.

Usage:
    python scripts/validate-kg.py PATH/TO/kg.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# Allow running without `pip install`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference-implementation" / "src"))

from ski_model.kg_loader import KnowledgeGraph

_REQUIRED_PREDICATE_FIELDS = {"operator", "metric"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path)
    p.add_argument("--allow-unsigned", action="store_true", help="Permit an unsigned KG (NON-CONFORMANT).")
    args = p.parse_args()

    if not args.path.exists():
        print(f"error: {args.path} does not exist", file=sys.stderr)
        return 2

    with args.path.open() as f:
        data = json.load(f)

    errors: list[str] = []

    try:
        kg = KnowledgeGraph.from_dict(data, require_signature=not args.allow_unsigned)
    except Exception as exc:
        print(f"FAIL: KG could not be parsed / signature failed: {exc}", file=sys.stderr)
        return 1

    rule_ids = [r.get("id") for r in kg.rules]
    if len(set(rule_ids)) != len(rule_ids):
        errors.append("duplicate rule ids present")

    for rule in kg.rules:
        rid = rule.get("id")
        if not rid:
            errors.append("rule with no id")
            continue
        track = rule.get("track")
        if track not in ("symbolic", "llm"):
            errors.append(f"rule {rid}: missing or invalid 'track' (got {track!r})")
        if rule.get("confidence") == "IMPLIED":
            errors.append(f"rule {rid}: confidence=IMPLIED is prohibited by B2.1 Anchor Constraint")
        if track == "symbolic":
            predicate = rule.get("predicate")
            if not isinstance(predicate, dict):
                errors.append(f"rule {rid}: symbolic rule has no structured 'predicate'")
            else:
                missing = _REQUIRED_PREDICATE_FIELDS - predicate.keys()
                if missing:
                    errors.append(f"rule {rid}: predicate missing fields {sorted(missing)}")
        for date_field in ("effective_date", "sunset_date"):
            if rule.get(date_field):
                try:
                    dt.date.fromisoformat(rule[date_field])
                except ValueError:
                    errors.append(f"rule {rid}: {date_field} is not ISO-8601: {rule[date_field]!r}")

    for subject, rid in kg.tag_registry.items():
        if rid not in rule_ids:
            errors.append(f"tag_registry: subject {subject!r} → unknown rule {rid!r}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print(
        f"OK: KG {kg.version!r} — {len(kg.rules)} rules, {len(kg.tag_registry)} tag "
        f"entries, signature_verified={kg.signature_verified}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
