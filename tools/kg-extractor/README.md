# kg-extractor

> **Status:** v3.0 — first production-target release.

Extract structured compliance rules from regulatory documents
(LLM-assisted) and emit a **v3 Knowledge Graph** ready for
`kg-validator` and the SKI Model runtime.

`kg-extractor` is a **Phase 1 (compilation)** tool. The output goes
through `kg-validator` (schema + §3.6 validation passes) and is then
signed before crossing the sovereign boundary. The extractor's LLM
backend may be local or cloud — its output is not part of the runtime
path.

## Highlights (v3.0)

- **Emits v3 KG JSON by default.** Each extracted rule is wrapped into
  the typed-graph shape from spec v3.0 §3: a Rule node, an Obligation
  with a guessed `obligation_type` and numeric `value`/`unit`, a
  Subject, a Citation, and the four edges connecting them
  (`applies_to`, `consists_of`, `scoped_to`, `cited_by`).
- **`--jurisdiction` flag.** Every KG carries a Jurisdiction node and
  every rule is `scoped_to` it. Defaults to `global`.
- **Pluggable LLM backend.** Default is **Ollama** (local). Cloud
  backends (`anthropic`, `openai`) exist for compilation-phase use only.
- **Deterministic by default.** Temperature 0, fixed seed, recorded
  prompt SHA-256 in extraction metadata for reproducibility audits.
- **`IMPLIED` is prohibited (B2.1 Anchor Constraint).** The prompt
  instructs the model not to emit `IMPLIED` and the parser downgrades
  any that slip through to `DISCRETIONARY` with a warning. Rules
  cannot be inferred beyond source text.
- **`extraction_quality` replaces `confidence`.** The per-rule trust
  signal is now `extraction_quality` (EXPLICIT / DISCRETIONARY /
  CONFLICTING) — a Phase-1 authoring concept, separate from the
  runtime's categorical verdict (Axiom 2 prohibits confidence scores
  in the audit trail).

## Installation

```bash
pip install -e tools/kg-extractor
```

## Quick start

```bash
# Extract a v3 KG from a regulation:
kg-extractor extract --file regulation.txt --sector energy \
    --jurisdiction us.federal \
    --output kg-extracted-v3.json

# Validate the emitted KG:
kg-validator validate --input kg-extracted-v3.json

# Batch:
kg-extractor batch --input-dir ./regulations --output-dir ./kgs \
    --sector energy --jurisdiction us.federal

# Debugging — dump the raw flat-rule list before wrapping:
kg-extractor extract --file regulation.txt --emit-raw --output flat.json
```

## Architecture

```
kg_extractor/
├── __init__.py     public API: Extractor, ExtractionResult, ExtractionQuality, emit_v3_kg
├── extractor.py    chunk → LLM → flat ComplianceRule list
├── models.py       ComplianceRule, ExtractionResult, ExtractionQuality enum
├── backends.py     Ollama / Anthropic / OpenAI backends (compilation phase only)
├── v3_emitter.py   wraps ExtractionResult into a v3 KG dict (spec §3 shape)
├── utils.py        chunking, document parsing, rule validation
└── cli.py          click-based CLI (`extract`, `batch`, `filter`, `examples`, `version`)
```

## Notes on `extraction_quality`

- **EXPLICIT** — the LLM produced a verbatim source quote in
  `reasoning`. The rule is safe to ship without further review.
- **DISCRETIONARY** — the LLM could not anchor the rule in a verbatim
  source quote. A human reviewer must approve before shipping.
- **CONFLICTING** — the LLM detected internal contradiction in the
  source. Surface for legal review.

This is **not** a confidence score in the probabilistic sense. The
runtime never reads it. It exists solely to drive the Phase-1
human-review queue.
