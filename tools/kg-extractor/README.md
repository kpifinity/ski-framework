# KG Extractor

Extract compliance rules from regulatory documents using LLM-assisted parsing.

## What It Does

KG Extractor transforms regulatory documents (PDFs, HTML, plain text) into structured compliance rules that can be used to build Knowledge Graphs. It uses Claude to:

1. **Parse documents** — Extract relevant compliance clauses
2. **Identify rules** — Find compliance obligations and constraints
3. **Structure as triplets** — Convert rules to Subject-Relation-Object format
4. **Flag ambiguities** — Mark rules that need human review
5. **Generate metadata** — Track source, clause references, and confidence

## Installation

```bash
# Clone the repository
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework/tools/kg-extractor

# Install dependencies
pip install -r requirements.txt

# Install the tool
pip install -e .
```

## Quick Start

### Extract rules from a document

```bash
python -m kg_extractor extract --file regulatory-doc.txt --sector energy
```

### Output format

```json
{
  "rules": [
    {
      "id": "rule_001",
      "subject": "Facility discharge",
      "relation": "must_be_within",
      "object": "100 ppm sulfur dioxide",
      "source_document": "Clean Air Act Section 112",
      "source_clause": "112(b)(1)",
      "confidence": "EXPLICIT",
      "reasoning": "The regulation explicitly states..."
    }
  ],
  "metadata": {
    "document_name": "regulatory-doc.txt",
    "document_type": "regulation",
    "sector": "energy",
    "extraction_timestamp": "2026-05-21T10:30:00Z",
    "total_rules_extracted": 5,
    "rules_needing_review": 1
  }
}
```

## Usage

### Basic extraction

```bash
kg-extractor extract --file document.txt
```

### With sector context

```bash
kg-extractor extract --file finance-regulation.pdf --sector finance
```

### Batch process multiple documents

```bash
kg-extractor batch --input-dir ./regulations --output-dir ./extracted-rules --sector energy
```

### Review flagged rules

```bash
kg-extractor review --input extracted-rules.json --output validated-rules.json
```

## API Usage

```python
from kg_extractor import Extractor

# Initialize extractor
extractor = Extractor(api_key="sk-...")

# Extract from text
rules = extractor.extract_from_text(
    text="The facility must maintain discharge below 100 ppm...",
    sector="energy",
    source_document="Clean Air Act"
)

# Extract from file
rules = extractor.extract_from_file(
    file_path="regulation.txt",
    sector="manufacturing"
)

# Get structured output
for rule in rules:
    print(f"Subject: {rule['subject']}")
    print(f"Relation: {rule['relation']}")
    print(f"Object: {rule['object']}")
```

## Configuration

Create a `.env` file in your project:

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-...

# Extraction settings
EXTRACTION_MODEL=claude-opus-4-6
EXTRACTION_TEMPERATURE=0.3
MAX_TOKENS=2000
BATCH_SIZE=5

# Output settings
OUTPUT_FORMAT=json
INCLUDE_CONFIDENCE=true
INCLUDE_REASONING=true
```

## How It Works

### 1. Document Parsing
- Reads regulatory documents (PDF, HTML, TXT, DOCX)
- Extracts relevant sections
- Identifies compliance-related clauses

### 2. Rule Extraction
- Uses Claude to parse each clause
- Identifies Subject-Relation-Object triplets
- Flags ambiguous or discretionary rules
- Preserves verbatim source references

### 3. Confidence Assessment
- **EXPLICIT** — Rule clearly stated in document
- **IMPLIED** — Rule inferred from multiple clauses
- **DISCRETIONARY** — Rule ambiguous, needs review
- **CONFLICTING** — Multiple interpretations possible

### 4. Output Generation
- Structures rules in standard SKI format
- Includes traceability to source documents
- Marks rules for human validation
- Generates metadata for audit trail

## Common Tasks

### Extract rules from environmental regulation

```bash
kg-extractor extract \
  --file clean-air-act.pdf \
  --sector energy \
  --output energy-rules.json
```

### Extract and validate in one step

```bash
kg-extractor extract --file regulation.txt | \
kg-extractor validate --interactive
```

### Merge rules from multiple documents

```bash
kg-extractor merge \
  --input rules1.json rules2.json rules3.json \
  --output combined-rules.json \
  --handle-conflicts manual
```

## Help & Documentation

```bash
# Get help on any command
kg-extractor --help
kg-extractor extract --help

# See examples
kg-extractor examples
```

## Limitations

- **Document size** — Works best with documents up to 50 pages
- **Language** — English documents only (for v1.0)
- **Clarity** — Requires reasonably well-structured regulatory text
- **Ambiguity** — Flags unclear rules but doesn't resolve them automatically

## Requirements

- Python 3.9+
- Anthropic API key (free tier or paid)
- 2GB RAM minimum
- Internet connection for API calls

## Testing

```bash
# Run tests
pytest tests/

# Test with sample document
python -m kg_extractor extract --file examples/sample-regulation.txt

# Test coverage
pytest --cov=src tests/
```

## Contributing

To improve KG Extractor:

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

### "API key not found"
Make sure you've set `ANTHROPIC_API_KEY` in your `.env` file or environment variables.

### "Document format not supported"
Supported formats: .txt, .pdf, .html, .docx, .md
Make sure your file has one of these extensions.

### "Extraction too slow"
Large documents are processed in batches. Reduce `BATCH_SIZE` in `.env` to process in smaller chunks.

### "Rules look incomplete"
Some regulatory language is complex. Try:
- Running with different `EXTRACTION_TEMPERATURE` (lower = more focused)
- Marking ambiguous rules for manual review
- Splitting document into sections and extracting separately

## Roadmap

- **v1.0** — Basic extraction with confidence flags
- **v1.1** — Multi-language support
- **v1.2** — PDF OCR for scanned documents
- **v1.3** — Conflict detection across documents
- **v1.4** — Interactive validation UI

## License

CC BY 4.0 — See [LICENSE.md](../../LICENSE.md)

---

For more information:
- [SKI Framework Architecture](../../docs/ARCHITECTURE.md)
- [Knowledge Graph Guide](../../docs/KNOWLEDGE_GRAPH.md)
- [Getting Started](../../docs/GETTING_STARTED.md)
