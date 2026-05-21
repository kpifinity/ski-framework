# KG Validator

Validate and review extracted compliance rules with human expert oversight.

## What It Does

KG Validator is a framework for human experts to review rules extracted by kg-extractor. It provides:

1. **Conflict Detection** — Identify rules that contradict each other
2. **Duplicate Detection** — Find identical or nearly-identical rules
3. **Quality Checks** — Verify rules are well-structured and complete
4. **Interactive Review** — Approve, reject, or flag rules for discussion
5. **Validation Report** — Generate audit trail of review decisions
6. **Approved Export** — Output validated rules ready for deployment

## Installation

```bash
# Clone the repository
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework/tools/kg-validator

# Install dependencies
pip install -r requirements.txt

# Install the tool
pip install -e .
```

## Quick Start

### Validate extracted rules

```bash
kg-validator validate --input extracted-rules.json --output validated-rules.json
```

### Interactive review mode

```bash
kg-validator review --input extracted-rules.json --interactive
```

### Generate validation report

```bash
kg-validator report --input extracted-rules.json --output validation-report.html
```

## Usage

### Basic validation (automated checks only)

```bash
kg-validator validate \
  --input rules-from-extraction.json \
  --output rules-validated.json
```

### Interactive validation with expert review

```bash
kg-validator review \
  --input rules-from-extraction.json \
  --output validated-rules.json \
  --interactive
```

This launches an interactive session where you can:
- Review each rule
- See detected conflicts and duplicates
- Approve (✓), reject (✗), or flag (?) rules
- Add notes and decisions
- Save progress and resume later

### Conflict detection only

```bash
kg-validator detect-conflicts \
  --input rules.json \
  --output conflicts.json
```

### Check for duplicates

```bash
kg-validator detect-duplicates \
  --input rules.json \
  --threshold 0.85
```

The threshold (0-1) determines similarity level for duplicate detection.

### Generate validation report

```bash
kg-validator report \
  --input extracted-rules.json \
  --validated-rules validated-rules.json \
  --output validation-report.html
```

## API Usage

```python
from kg_validator import Validator

# Initialize validator
validator = Validator()

# Load extracted rules
extracted_rules = validator.load_rules("extracted-rules.json")

# Detect conflicts
conflicts = validator.detect_conflicts(extracted_rules)
print(f"Found {len(conflicts)} conflicting rule pairs")

# Detect duplicates
duplicates = validator.detect_duplicates(extracted_rules, threshold=0.85)
print(f"Found {len(duplicates)} potential duplicates")

# Run automated quality checks
issues = validator.check_quality(extracted_rules)
for issue in issues:
    print(f"Rule {issue['rule_id']}: {issue['issue']}")

# Interactive validation
validator.validate_interactive(extracted_rules)

# Get approved rules
approved_rules = validator.get_approved_rules()
validator.save_rules(approved_rules, "validated-rules.json")
```

## How It Works

### Phase 1: Automated Checks

1. **Conflict Detection**
   - Identifies rules where the same subject-relation pair has contradictory objects
   - Flags rules with different effective dates that might overlap
   - Detects logical inconsistencies (e.g., max=100 and max=50)

2. **Duplicate Detection**
   - Finds exact duplicates
   - Identifies near-duplicates using semantic similarity
   - Suggests deduplication actions

3. **Quality Checks**
   - Validates all required fields are present
   - Checks for overly broad or vague rules
   - Verifies source references exist
   - Detects rules missing confidence levels

### Phase 2: Expert Review (Interactive Mode)

For each rule, the expert can:

```
Rule #1: Facility discharge must be within 100 ppm sulfur dioxide
Source: Clean Air Act Section 112(b)(1)
Confidence: EXPLICIT
Conflicts: None detected
Duplicates: None detected

Review this rule? [✓ Approve / ✗ Reject / ? Flag / ↪ Skip]
```

Expert options:
- **✓ Approve** — Rule is valid and should be included in Knowledge Graph
- **✗ Reject** — Rule is incorrect or not applicable
- **? Flag** — Rule needs discussion/clarification before approval
- **↪ Skip** — Review later
- **Note** — Add expert notes for audit trail

### Phase 3: Validation Report

Generated report includes:
- Total rules reviewed
- Approval/rejection/flag breakdown
- All detected conflicts (with expert decision)
- All detected duplicates (with deduplication decision)
- Audit trail of all decisions
- Final validated rule count
- Ready-for-deployment status

### Phase 4: Export

```json
{
  "validated_rules": [
    {
      "id": "rule_001",
      "subject": "Facility discharge",
      "relation": "must_be_within",
      "object": "100 ppm sulfur dioxide",
      "source_document": "Clean Air Act",
      "source_clause": "Section 112(b)(1)",
      "confidence": "EXPLICIT",
      "reasoning": "...",
      "validation_status": "APPROVED",
      "validation_timestamp": "2026-05-21T10:30:00Z",
      "validator_notes": "Confirmed against source document"
    }
  ],
  "validation_metadata": {
    "total_rules_reviewed": 25,
    "total_approved": 23,
    "total_rejected": 1,
    "total_flagged": 1,
    "validation_duration": 1800,
    "validators": ["john.doe@company.com"],
    "timestamp": "2026-05-21T10:30:00Z"
  }
}
```

## Configuration

Create a `.env` file:

```bash
# Validation settings
SIMILARITY_THRESHOLD=0.85
CHECK_EFFECTIVE_DATES=true
CHECK_EXPIRATION_DATES=true

# Interactive mode
INTERACTIVE_BATCH_SIZE=10
AUTO_SAVE_INTERVAL=300  # seconds

# Report generation
REPORT_FORMAT=html  # html or pdf
INCLUDE_AUDIT_TRAIL=true
```

## Common Workflows

### 1. Extract then Validate

```bash
# Extract rules from regulatory document
kg-extractor extract --file regulation.txt --output extracted.json

# Validate with expert review
kg-validator review --input extracted.json --output validated.json
```

### 2. Batch validation with conflict detection

```bash
# Validate multiple extracted rule sets
kg-validator batch-validate \
  --input-dir ./extracted-rules \
  --output-dir ./validated-rules \
  --detect-conflicts
```

### 3. Continuous validation process

```bash
# Start validation session
kg-validator review --input extracted.json --checkpoint validated-checkpoint.json

# Work through rules, save progress
# Can resume later:
kg-validator resume --checkpoint validated-checkpoint.json
```

## Help & Documentation

```bash
# Get help
kg-validator --help
kg-validator validate --help

# See examples
kg-validator examples

# Detailed conflict detection help
kg-validator detect-conflicts --help
```

## Limitations

- **Language** — English documents only (v1.0)
- **Scale** — Best for <500 rules per validation session
- **Context** — Requires expert domain knowledge for meaningful review
- **Time** — Expect 2-5 minutes per rule for thorough review

## Requirements

- Python 3.9+
- Expert reviewer with domain knowledge
- ~15 minutes per 50 rules for interactive validation
- Text editor or browser for reviewing validation reports

## Testing

```bash
# Run tests
pytest tests/

# Test with sample rules
python -m kg_validator validate --input examples/sample-extracted-rules.json

# Test conflict detection
pytest tests/test_conflict_detection.py -v
```

## Contributing

To improve KG Validator:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines.

## Support

- **Issues?** Open an issue on GitHub
- **Questions?** Check the examples/ folder
- **Need help?** See the troubleshooting section below

## Troubleshooting

### "Rules file not found"
Make sure the JSON file from kg-extractor exists at the specified path.

### "Interactive mode stuck"
Press Ctrl+C to exit current rule, saves progress automatically.

### "Conflict detection too strict"
Adjust `SIMILARITY_THRESHOLD` in `.env` (lower = more lenient, 0-1 scale).

### "Report generation slow"
For large rule sets (>500), consider validating in batches or reducing report detail.

## Roadmap

- **v1.0** — Automated checks + interactive review
- **v1.1** — Multi-validator support with voting
- **v1.2** — Machine learning suggestion for approvals
- **v1.3** — Integration with version control (Git)
- **v1.4** — Web-based review interface

## License

CC BY 4.0 — See [LICENSE.md](../../LICENSE.md)

---

For more information:
- [KG Extractor](../kg-extractor/README.md) — Extract rules first
- [SKI Architecture](../../docs/ARCHITECTURE.md)
- [Getting Started](../../docs/GETTING_STARTED.md)
