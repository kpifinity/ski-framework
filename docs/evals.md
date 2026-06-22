# SKI Evals — verdict accuracy

Conformance proves the **plumbing** (envelopes well-formed, ledger
append-only, KG signed). SKI Evals proves the **judgment**: that the
neuro-symbolic evaluator produces the right verdict on telemetry whose
correct outcome is known in advance. For a compliance system, this
evidence *is* the product — publishing it, including the failures, is
the point.

## How it works

Each dataset under
[`evals/datasets/<sector>/`](https://github.com/kpifinity/ski-framework/tree/main/evals/datasets)
pairs an **evaluation Knowledge Graph** with **human-labeled golden
cases** (`cases.jsonl`): a measurement, its jurisdiction and timestamp,
and the expected verdict plus expected formalizable assertions.

The runner drives the **real production path** — `kg_loader` loading,
jurisdiction + effective-date scoping via `scope_to`, then
`V3Evaluator.aevaluate` with the configured LLM backend and the
Symbolic Verifier cross-checking every assertion. Nothing is mocked
between the case file and the verdict envelope.

```bash
python -m evals.run --backend fake     # harness check (CI, deterministic)
python -m evals.run --backend ollama   # real model numbers (local LLM)
```

Reports (JSON + Markdown) carry a full provenance block: backend,
model-weight hash, prompt-template hash, decoder seed, KG hash, and
dataset hash — the same discipline as a verdict envelope.

## Metrics

| Metric | Question it answers |
|---|---|
| **Verdict accuracy** | Of all cases, how many got the exactly-right verdict? |
| **FLAG recall** | Of all true breaches, how many were flagged? *The regulator's number.* |
| **FLAG precision** | Of everything flagged, how much was a real breach? (False-alarm control.) |
| **Breaches silently CLEARed** | The catastrophic failure mode: a true breach waved through as CLEAR. Must be **0**. A breach routed to DISCRETIONARY is safe-but-costly; a breach CLEARed is a compliance miss. |
| **NULL_UNMAPPED recall** | Are out-of-scope subjects honestly reported as unmapped (vs. guessed at)? Exercises jurisdiction and effective-date scoping. |
| **Assertion correctness** | Do the LLM's formalizable assertions cite the right obligation with the right satisfied flag? |
| **LLM-verifier agreement rate** | How often does the independent Symbolic Verifier agree with the LLM? |

## The energy dataset (v1)

50 cases against a 10-rule evaluation KG: 20 CLEAR, 18 FLAG, 12
NULL_UNMAPPED, deliberately including boundary values (at-limit is
CLEAR; `must_not_exceed` is inclusive), jurisdiction-scoping cases
(an Alberta-only rule must not bind a US-federal tenant and vice
versa), and effective-date cases (a future rule and a sunset rule must
both scope out). No DISCRETIONARY golden cases yet — deterministic
labeling of judgment calls is future work, tracked for v3.1.

## The FakeLLM baseline — why 96% is the *correct* score

The deterministic `FakeLLM` backend deliberately mishandles
`must_be_at_least` obligations. The pinned baseline
(`evals/tests/test_evals_harness.py`) asserts exactly what the
architecture promises happens next:

| Metric | FakeLLM pinned baseline |
|---|---|
| Verdict accuracy | 96.0% (48/50) |
| FLAG recall | 88.9% (16/18) |
| FLAG precision | 100% |
| **Breaches silently CLEARed** | **0** |
| Assertion correctness | **100%** (38/38) |
| LLM-verifier agreement | 94.7% (36/38) |

On both blind-spot cases the Symbolic Verifier normalised
the wrong ``satisfied`` flag and then detected **NEURO_SYMBOLIC_DIVERGENCE**
(verdict=CLEAR inconsistent with the corrected satisfied=False), and the
pipeline routed both to **DISCRETIONARY** (human review). Even with a
deliberately flawed model,
no breach was silently cleared — that is the neuro-symbolic
architecture doing its job, demonstrated by the eval suite itself.

Real-model numbers (Ollama, `qwen2.5:7b-instruct`, seed 42) run
nightly in [`evals.yml`](https://github.com/kpifinity/ski-framework/blob/main/.github/workflows/evals.yml)
and are published as workflow artifacts; a results page will be added
once enough nightly history exists to report stable numbers.

## Real-model iteration log (qwen2.5:7b-instruct, seed 42)

The evals exist to drive iteration, so the history is published, not
hidden. Each run is one nightly execution of the full 50-case energy
dataset through the production path on a local Ollama backend.

| Run (2026-06) | Prompt / decode | Accuracy | FLAG recall | Agreement | **Silently CLEARed breaches** |
|---|---|---|---|---|---|
| 1 | `evaluate.1`, free-form JSON | 26% | 5.6% | n/a | **0** |
| 2 | `evaluate.2` + schema-constrained decoding | 22% | 11% | n/a (no checkable assertions) | **0** |
| 3 | `evaluate.3` + output-contract guard, raised token budget | 54% | 33% | 75% | **0** |
| 4 | `evaluate.4` (scoping clarified, mapping defined, worked example) | 76% | 66.7% | 73% | **0** |
| 5 | `evaluate.5` + verifier observation grounding | 72% | 72.2% | 69% | **0** |
| 6 | taxonomy guard (no unverified CLEAR) + obligation-side grounding | — pending | — | — | **0 required** |

What each iteration found and fixed:

1. **Run 1 → 2:** the model invented node ids (citation enforcement
   degraded them to NULL_UNMAPPED) and emitted malformed JSON (backend
   degraded it to DISCRETIONARY). Fix: schema-constrained decoding +
   the valid-node-id list injected into the prompt.
2. **Run 2 → 3:** verdicts collapsed to DISCRETIONARY with zero
   checkable assertions (token-budget truncation), and one response
   shape — `"value": {"min": ..., "max": ...}` — crashed the evaluator
   outright. Fixes: raised token budget; three-layer output-contract
   hardening (evaluator guard, typed grammar, pinned shapes). The crash
   fix shipped to the runtime itself — the evals caught a production
   bug.
3. **Run 3 → 4:** 18 of 23 remaining misses were `X → NULL_UNMAPPED`
   where the model re-checked jurisdictions and effective dates the
   framework had already scoped — and the prompt itself taught the
   confusion (it described a past `effective_date` as a staleness
   signal; in the taxonomy NULL_STALE means stale *telemetry*). Fixes:
   the prompt now states the snapshot is pre-scoped, defines "maps"
   mechanically (obligation `metric` = measurement key), corrects the
   NULL_STALE definition, and includes one worked example.

4. **Run 4 → 5:** NULL_UNMAPPED over-prediction collapsed (18 misses →
   1); accuracy 54% → 76%. The remaining misses were raw 7B comparison
   errors ("60 exceeds 75"; 100 ≤ 100 called a breach) — every one
   caught by the Symbolic Verifier as LLM_CONTRADICTION and routed to
   DISCRETIONARY. But run 4 also produced the suite's most valuable
   finding yet: one **false FLAG** on a deliberately unmapped
   measurement key (`so2` vs `so2_ppm`), where the model fuzzy-matched
   the metric and *fabricated the observed value*. The arithmetic was
   internally consistent, so the arithmetic-only verifier agreed.
   Fixes: the verifier now **grounds observations** — `observed` must
   match what the measurement actually records, and asserting a metric
   the measurement doesn't contain is a fabrication, both degraded as
   LLM_CONTRADICTION; the prompt pins explicit comparison semantics
   (inclusive boundaries, range membership) per predicate.

5. **Run 5 → 6:** observation grounding worked — the false-FLAG class
   is gone (FLAG precision back to 100%) and FLAG recall rose to 72%.
   But run 5 found the framework's own deepest gap yet: on two
   deliberately unmapped cases the model *reasoned correctly* ("nothing
   maps") and then emitted **CLEAR anyway** — zero citations, zero
   assertions — and the envelope shipped as CLEAR. An unverifiable
   compliance claim; a coverage gap masked as green. Fixes: the
   **taxonomy guard** — a CLEAR with no formalizable assertions is
   remapped deterministically (no citations → NULL_UNMAPPED; citations
   → DISCRETIONARY) and noted in the envelope; and **obligation-side
   grounding** — an assertion's `metric` and `value` must now match the
   obligation it cites, closing the fabricated-cap hole the same
   analysis exposed. Accuracy (72% vs 76%) is qwen-7B noise at this
   dataset size; the remaining misses are arithmetic errors the
   verifier catches and routes to human review. Model-quality gains
   from here come from a larger model on the vLLM backend, not from
   prompt surgery.


6. **Run 6 → 7:** Run 6 confirmed observation grounding landed cleanly
   (FLAG precision 100%, 0 silent CLEARs) and put a number on the
   remaining gap: 13 mismatches, all `LLM_CONTRADICTION`, all caused by
   the model emitting the right verdict (CLEAR for NOx=60 vs limit=75,
   FLAG for pH=9.1 vs [6.0,8.5]) but the wrong `satisfied` boolean in
   the formalizable assertion. The model was doing the arithmetic
   correctly in its reasoning but then mis-transcribing the result into
   the structured JSON field -- a known failure mode of constrained
   decoding at 7B. Fix: **verifier-side `satisfied` normalization** --
   for any assertion whose predicate is stateless and mechanically
   evaluable (`must_not_exceed`, `must_be_at_least`, `must_be_within`,
   etc.) the Symbolic Verifier computes the correct boolean and
   replaces the LLM's claim before the aggregate check runs. The raw
   LLM claim is preserved in the signed transcript; the envelope
   carries the mechanically correct value. Grounding failures
   (fabricated observations, wrong obligation values) are intentionally
   left uncorrected -- the grounding error is still caught by
   `averify`. This is the correct neuro-symbolic split: the model
   identifies obligations and observes values; the verifier computes
   predicate truth. Expected impact: 11 of the 13 Run 6 mismatches
   resolved, targeting >90% accuracy in Run 7.

The row that never moves is the point: **across every run, zero
breaches were silently CLEARed and FLAG precision held at 100%.** Every
model failure degraded to a human-reviewed or coverage-gap verdict —
NULL_UNMAPPED, DISCRETIONARY (5 of run 3's misses were the Symbolic
Verifier catching the LLM's wrong `satisfied` flags as
LLM_CONTRADICTION) — never to a false CLEAR. Accuracy is an iteration
target; the safety property is an architectural invariant.

## Contributing cases

Add a JSONL line with a unique `case_id`, the measurement, jurisdiction,
timestamp, expected verdict, and expected assertions, then run
`pytest evals/tests/` — the dataset-shape test will tell you what to
update. Hard cases that expose model weaknesses are the most valuable
contribution; a failing eval with a correct label is a gift.
