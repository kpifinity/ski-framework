# SKI Evals report — `energy` dataset

Backend **fake-llm** · seed 42 · 50 cases · 2026-06-12T21:05:48.111727+00:00

## Headline metrics

| Metric | Value |
|---|---|
| Verdict accuracy | **96.0%** |
| FLAG recall (missed breaches are the misses) | **88.9%** |
| FLAG precision | 100.0% |
| Breaches silently CLEARed | **0** |
| NULL_UNMAPPED recall | 100.0% |
| Assertion correctness | 94.7% |
| LLM-verifier agreement rate | 94.7% |

## Accuracy by category

| Category | Accuracy |
|---|---|
| boundary | 94.4% |
| clear | 100.0% |
| effective-date | 100.0% |
| flag | 88.9% |
| jurisdiction | 100.0% |
| null_unmapped | 100.0% |

## Confusion (expected → predicted)

- **CLEAR** → CLEAR: 20
- **FLAG** → DISCRETIONARY: 2, FLAG: 16
- **NULL_UNMAPPED** → NULL_UNMAPPED: 12

## Mismatches

| Case | Expected | Predicted | Verifier | Notes |
|---|---|---|---|---|
| `flag-flow-just-under` | FLAG | DISCRETIONARY | LLM_CONTRADICTION | must_be_at_least breach; known FakeLLM blind spot |
| `flag-flow-zero` | FLAG | DISCRETIONARY | LLM_CONTRADICTION | must_be_at_least breach; known FakeLLM blind spot |

## Provenance

```json
{
  "ran_at": "2026-06-12T21:05:48.111727+00:00",
  "backend": "fake-llm",
  "model_weight_hash": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "prompt_template_id": "ski.v3.evaluate.5",
  "prompt_template_hash": "sha256:f1a04845e3fb5ed6c59ba96f063efa392d2d0dceb9a5f5c66a8f5a52de2443b0",
  "structured_grammar_hash": "sha256:c67866106b1759e4fc4f3d4f203459bbd9f8f6bea08d9383403bee6cfbd60789",
  "decoder_seed": 42,
  "kg_version": "ski-evals-energy-1.0.0",
  "kg_file_hash": "sha256:af6aef66572e49e73957f1dd3cd919bd14a7fdc8b9a0f0725822ae4bb27577d6",
  "cases_file_hash": "sha256:e9a7def6b30af9379b7bd3b06c78a672e7d9b971d48fa14a9c95fea58d5311bf",
  "n_cases": 50
}
```

_Methodology: docs/evals.md. A missed breach (FLAG recall < 100%) is the failure
mode that matters most; treat any drop as a release blocker._
