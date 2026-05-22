# kg-extractor

> **⚠ STATUS: EARLY ALPHA (v0.1.0a0).** Alpha-quality tooling. See the
> repo root `README.md` for the project-wide status.

Extract structured compliance rules from regulatory documents
(LLM-assisted) for use in SKI Knowledge Graphs.

`kg-extractor` is a **Phase 1 (compilation)** tool. The output goes
through `kg-validator` (human review) and is then signed before
crossing the sovereign boundary. The extractor's LLM backend may be
local or cloud — its output is not part of the runtime path.

## Highlights (v2.1)

- **LLM backend is pluggable.** Default is **Ollama** (local). Cloud
  backends (`anthropic`, `openai`) exist for compilation-phase use only.
- **Deterministic by default.** Temperature 0, fixed seed, recorded
  prompt SHA-256 in extraction metadata for reproducibility audits.
- **`IMPLIED` is prohibited (B2.1 Anchor Constraint).** The prompt
  instructs the model not to emit `IMPLIED` and the parser downgrades
  any that slip through to `DISCRETIONARY` with a warning. Rules cannot
  be inferred beyond source text.
- **No more PyPDF2.** Replaced with `pypdf` (PyPDF2 is deprecated and
  carries known CVEs).
- **Source-version binding.** Every rule records the
  `source_document_version` so updates are traceable.

## Installation

```bash
pip install -e tools/kg-extractor
```

## Quick start

```bash
# Default backend is local Ollama. Pull the model once:
docker exec ski-ollama ollama pull qwen2.5:7b-instruct

# Extract:
kg-extractor extract \
  --file regulatory-doc.pdf \
  --sector energy \
  --source-document-version "2025-12-31" \
  --output extracted-rules.json
```

To use a cloud backend (compilation phase only — do not use at runtime):

```bash
KG_EXTRACTOR_LLM_BACKEND=anthropic ANTHROPIC_API_KEY=... \
kg-extractor extract --file regulatory-doc.pdf --sector energy
```

## Output format

```json
{
  "rules": [
    {
      "id": "rule_0_0",
      "subject": "Facility SO2 discharge",
      "relation": "must_not_exceed",
      "object": "100 ppm",
      "source_document": "regulatory-doc.pdf",
      "source_clause": "Section 112(b)(1)",
      "source_document_version": "2025-12-31",
      "confidence": "EXPLICIT",
      "reasoning": "The regulation explicitly states 'sulfur dioxide emissions shall not exceed 100 ppm'."
    }
  ],
  "metadata": {
    "document_name": "regulatory-doc.pdf",
    "sector": "energy",
    "extraction_timestamp": "2026-05-22T10:30:00Z",
    "total_rules_extracted": 12,
    "backend": "ollama",
    "model_used": "qwen2.5:7b-instruct",
    "model_file_sha256": "...",
    "temperature": 0.0,
    "seed": 42,
    "prompt_sha256": "..."
  },
  "warnings": []
}
```

The extractor produces draft rules. **Every rule must be reviewed by a
qualified human via `kg-validator` before signing.** B2.3 Universal
Coverage forbids auto-approval.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `KG_EXTRACTOR_LLM_BACKEND` | `ollama` | `ollama`, `anthropic`, `openai`. Cloud backends are Phase 1 only. |
| `KG_EXTRACTOR_MODEL` | `qwen2.5:7b-instruct` | Model name for the active backend. |
| `KG_EXTRACTOR_TEMPERATURE` | `0` | Do not raise without recording the change. |
| `KG_EXTRACTOR_SEED` | `42` | Recorded into extraction metadata. |
| `KG_EXTRACTOR_MODEL_FILE_SHA256` | unset | If set, recorded into metadata for audit. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `ANTHROPIC_API_KEY` | unset | Required only for `anthropic` backend. |
| `OPENAI_API_KEY` | unset | Required only for `openai` backend. |

## Licensing

Apache 2.0 — see [`../../LICENSE`](../../LICENSE).
