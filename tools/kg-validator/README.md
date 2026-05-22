# kg-validator

> **⚠ STATUS: EARLY ALPHA (v0.1.0a0).** Alpha-quality tooling. See the
> repo root `README.md` for the project-wide status.

Validate compliance rules extracted by `kg-extractor` and prepare them
for human review. Phase 1 (compilation) tool.

## v2.1 highlights

- **No auto-approval.** The pre-v2.1 `auto_approve_explicit` option has
  been **removed**. Per spec B2.3 (Universal Coverage), every rule must
  be reviewed by a qualified human. Even as opt-in, auto-approval
  defaults the operator toward non-conformance.
- **Conflict detection.** Identifies rule pairs that contradict each
  other so reviewers can either declare an explicit precedence or
  reject one.
- **Duplicate detection.** Catches near-identical rules so they can be
  merged in review.
- **Quality checks.** Flags vague language, missing fields, and
  `DISCRETIONARY` confidence as items needing reviewer attention.
- **No `IMPLIED`.** The validator refuses to approve a rule with
  `confidence: IMPLIED` — kg-extractor should already have prevented
  this (B2.1 Anchor Constraint).

## Installation

```bash
pip install -e tools/kg-validator
```

## Quick start

```bash
# Automated checks. Surfaces issues but does NOT approve any rule.
kg-validator validate --input extracted-rules.json --output validation.json

# Interactive review (CLI). Walks through every flagged rule with the
# reviewer; approval requires explicit action.
kg-validator review --input extracted-rules.json --interactive

# HTML validation report (read-only summary; does not approve).
kg-validator report --input extracted-rules.json --output report.html
```

## Output

`validate` writes a JSON object containing:

```json
{
  "approved_rules":   [],                /* always empty here; approval
                                            requires interactive review */
  "issues":           [ ... ],
  "conflicts":        [ ... ],
  "duplicates":       [ ... ],
  "metadata": {
    "total_rules_reviewed": 47,
    "total_approved": 0,
    "total_flagged":  18,
    "total_issues_found": 23,
    "validation_timestamp": "2026-05-22T10:30:00Z",
    "validators": ["automated"]
  }
}
```

Approval happens during interactive review. The approved rules then
feed into the KG-signing step.

## Licensing

Apache 2.0 — see [`../../LICENSE`](../../LICENSE).
