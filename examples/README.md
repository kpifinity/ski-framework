# Examples — DEMO ONLY

> **⚠ Every file under `examples/` is demo-grade.** The Knowledge
> Graphs are minimal, unsigned, and illustrative; the regulatory
> citations are placeholders, not legal references. Production KG
> libraries (energy, finance, manufacturing, defense) are proprietary —
> see [KpiFinity](https://kpifinity.com).

Each sector directory contains one **v3 Knowledge Graph**
(`kg-<sector>-v3-demo.json`) and one telemetry sample
(`telemetry/*.jsonl`). The two are paired: replaying the telemetry
against the KG produces a known mix of verdicts.

## The v3 KG shape (spec v3.0 §3)

Every demo KG is a typed graph with the same skeleton:

```jsonc
{
  "metadata":  { "name", "schema_version": "3.0", "sector", ... },
  "nodes": {
    "subjects":      [ ... ],   // what telemetry is about
    "rules":         [ ... ],   // named rules with a declared risk_tier
    "obligations":   [ ... ],   // typed: obligation_type, metric, value, unit,
                                //        effective_date_start, summary
    "definitions":   [ ... ],
    "exemptions":    [ ... ],
    "precedents":    [ ... ],
    "jurisdictions": [ ... ],
    "citations":     [ ... ]    // every obligation traces to a source clause
  },
  "edges": [
    { "type": "applies_to",  "from": "<rule>",       "to": "<subject>" },
    { "type": "consists_of", "from": "<rule>",       "to": "<obligation>" },
    { "type": "scoped_to",   "from": "<obligation>", "to": "<jurisdiction>" },
    { "type": "cited_by",    "from": "<obligation>", "to": "<citation>" }
  ]
}
```

`obligation_type` is a closed enumeration (spec §3.3). The demo KGs use
only types the Symbolic Verifier can mechanically cross-check
(`must_not_exceed`, `must_be_at_least`, `must_be_within`), so every
demo verdict exercises the full neuro-symbolic path: LLM reasoning →
formalizable assertions → independent verifier result.

## Structural rules every demo follows

1. **Unsigned.** Loading one requires `KG_REQUIRE_SIGNATURE=false` —
   deliberately non-conformant so nobody mistakes a demo for a
   deployable artifact.
2. **Validates clean.** `kg-validator validate -i <file>` passes for
   every demo KG. CI-checked intent: if you edit one, re-validate.
3. **Telemetry is paired.** Each sample includes conforming records
   (CLEAR), breaches (FLAG), and an unmapped subject (NULL_UNMAPPED)
   to demonstrate the Coverage Register.
4. **Citations are fake.** Anything that looks like a real regulation
   citation is illustrative.

## Run any sector

```bash
# Stack up (see reference-implementation/QUICKSTART.md), then:
python scripts/send-telemetry.py examples/<sector>/telemetry/<file>.jsonl --insecure
python scripts/check-verdicts.py --insecure --limit 20
```

## Path to a real KG

Extract candidate obligations with `kg-extractor`, validate every rule
with a qualified human expert via `kg-validator`, sign with your
production Ed25519 key, deploy with `ski-model-deploy`, then run the
conformance suite. Or contract KpiFinity for the production KG library,
regulator-update subscriptions, and certification support.
