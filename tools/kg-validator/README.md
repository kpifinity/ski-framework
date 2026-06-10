# kg-validator

> Install from PyPI: `pip install ski-kg-validator` (publishing starts with the first release after June 2026).

> **Status:** v3.0 — first production-target release.

Validate v3 Knowledge Graphs against SKI Framework specification v3.0
§3 (schema) and §3.6 (cross-cutting validation passes). Phase 1
(compilation) tool.

## What it does

- **Schema validation.** Parses a v3 KG JSON file into the typed-node
  Pydantic models. Unknown obligation types, unknown edge types,
  unknown risk tiers, missing required fields, and extra unknown keys
  are all rejected at load time.
- **Cross-cutting validation (§3.6).** Detects duplicate node IDs,
  dangling edges, edges pointing at the wrong target node type, rules
  without any obligation, and orphan obligations.

## What it no longer does (v2 retired in PR 10e)

- The v2 flat-rule-list format is gone. v3 typed obligations are the
  only currency.
- Interactive `review`, `detect-conflicts`, `detect-duplicates`, and
  HTML `report` subcommands were retired with the v2 path — they
  worked on the flat-rule shape and have no v3 equivalent. v3
  conflict and duplicate detection happen at the typed-obligation
  level inside the validation passes and surface as issues in the
  output JSON.
- The `ConfidenceLevel` enum is gone. The extractor now carries an
  `ExtractionQuality` value (separate concept; see `kg-extractor`).

## Installation

```bash
pip install -e tools/kg-validator
```

## Quick start

```bash
# Validate a v3 KG and print the issue summary:
kg-validator validate --input examples/energy/knowledge-graphs/kg-energy-v3-demo.json

# Validate and persist the full issue report:
kg-validator validate \
  --input kg-energy-v3.json \
  --output validation-report.json

# Show usage examples:
kg-validator examples

# Show version:
kg-validator version
```

The `validate` command exits with code 0 on a clean KG, code 2 on a
schema-level Pydantic validation failure, and code 3 on any CRITICAL
or HIGH severity §3.6 issue.

## Architecture

```
kg_validator/
├── __init__.py    public API: KnowledgeGraphV3, V3Validator, load_v3_kg, models
├── loader.py      KnowledgeGraphV3 container + load_v3_kg(path) entry point
├── models.py      typed Pydantic models per spec v3.0 §3 (nodes, edges, enums)
├── validator.py   V3Validator runs the §3.6 cross-cutting passes
└── cli.py         click-based CLI (`validate`, `examples`, `version`)
```

## Conformance

The `examples/energy/knowledge-graphs/kg-energy-v3-demo.json` sample
KG must load cleanly and produce zero validation issues. This is
exercised by `tests/test_v3_validator.py` and by the CI durability
suite.
