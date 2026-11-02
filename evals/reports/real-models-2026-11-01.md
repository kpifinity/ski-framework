# Real-model evals — 2026-11-01

**Run:** [https://github.com/kpifinity/ski-framework/actions/runs/41346707708](https://github.com/kpifinity/ski-framework/actions/runs/41346707708) (`evals-real.yml`, PR head `19e8a56`), 18 jobs: two model
families × three decoder seeds × three datasets (312 cases), Ollama 0.6.8 on CPU.

## Reading these numbers

- **The safety property held on every run: 0 breaches and 0 silent sensors were
  CLEARed** across 1,872 evaluations (2 models × 3 seeds × 312 cases).
- **Models this small cannot do the task.** Neither `llama3.2:1b` nor
  `qwen2.5:1.5b` produced a single formalizable assertion the Symbolic Verifier
  could agree with (LLM-verifier agreement 0%), so no verdict was honoured on the
  model's word alone: the eval KGs declare no `risk_tier`, so the strictest tier
  applies and every unverified answer was routed to human review
  (`DISCRETIONARY`) or reported as unmapped. No FLAG was emitted, so FLAG recall
  is 0% and FLAG precision is undefined. What these models got right is mostly
  what the runtime decides without them (silent sensors, out-of-scope records).
- **Not a pipeline fault, as far as can be checked:** the same parser and verifier
  return `AGREED` for a correct answer in the black-box conformance suite, and the
  earlier 7B runs (docs/evals.md) reached 69–75% agreement. The per-case raw
  outputs of this run were not kept; from the next run on `--dump-raw` stores them
  in the artifacts.
- Small models were chosen so the whole matrix fits CPU runners. Accuracy numbers
  that mean something need a production-size model on the vLLM backend; this run
  measures the floor, and the floor is safe.

## Summary (as printed by `python -m evals.summary`)

Rates are pooled over the datasets of one model and seed; brackets are Wilson 95% intervals.

## `llama3.2:1b` (ollama-v3)

| Metric | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| Verdict accuracy | 11.5% [8.5%, 15.6%] (36/312) | 11.5% [8.5%, 15.6%] (36/312) | 11.5% [8.5%, 15.6%] (36/312) |
| FLAG recall | 0.0% [0.0%, 3.8%] (0/97) | 0.0% [0.0%, 3.8%] (0/97) | 0.0% [0.0%, 3.8%] (0/97) |
| FLAG precision | n/a | n/a | n/a |
| NULL_UNMAPPED recall | 54.7% [42.6%, 66.3%] (35/64) | 54.7% [42.6%, 66.3%] (35/64) | 54.7% [42.6%, 66.3%] (35/64) |
| NULL_STALE recall | 2.3% [0.4%, 12.1%] (1/43) | 2.3% [0.4%, 12.1%] (1/43) | 2.3% [0.4%, 12.1%] (1/43) |
| Routed to human review (DISCRETIONARY) | 79.5% [74.7%, 83.6%] (248/312) | 79.5% [74.7%, 83.6%] (248/312) | 79.5% [74.7%, 83.6%] (248/312) |
| LLM-verifier agreement | 0.0% [0.0%, 1.5%] (0/245) | 0.0% [0.0%, 1.5%] (0/245) | 0.0% [0.0%, 1.5%] (0/245) |
| **Breaches silently CLEARed** | **0** | **0** | **0** |
| **Silent sensors CLEARed** | **0** | **0** | **0** |

Verdict accuracy by dataset:

| Dataset | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| energy | 21.8% [12.9%, 34.4%] (12/55) | 21.8% [12.9%, 34.4%] (12/55) | 21.8% [12.9%, 34.4%] (12/55) |
| finance | 10.1% [6.0%, 16.5%] (13/129) | 10.1% [6.0%, 16.5%] (13/129) | 10.1% [6.0%, 16.5%] (13/129) |
| manufacturing | 8.6% [4.9%, 14.7%] (11/128) | 8.6% [4.9%, 14.7%] (11/128) | 8.6% [4.9%, 14.7%] (11/128) |

Same verdict under every seed: 100.0% [98.8%, 100.0%] (312/312).

## `qwen2.5:1.5b` (ollama-v3)

| Metric | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| Verdict accuracy | 17.0% [13.2%, 21.5%] (53/312) | 17.0% [13.2%, 21.5%] (53/312) | 17.6% [13.8%, 22.2%] (55/312) |
| FLAG recall | 0.0% [0.0%, 3.8%] (0/97) | 0.0% [0.0%, 3.8%] (0/97) | 0.0% [0.0%, 3.8%] (0/97) |
| FLAG precision | n/a | n/a | n/a |
| NULL_UNMAPPED recall | 17.2% [9.9%, 28.2%] (11/64) | 17.2% [9.9%, 28.2%] (11/64) | 18.8% [11.1%, 30.0%] (12/64) |
| NULL_STALE recall | 95.3% [84.5%, 98.7%] (41/43) | 95.3% [84.5%, 98.7%] (41/43) | 95.3% [84.5%, 98.7%] (41/43) |
| Routed to human review (DISCRETIONARY) | 32.7% [27.7%, 38.1%] (102/312) | 32.7% [27.7%, 38.1%] (102/312) | 33.7% [28.6%, 39.1%] (105/312) |
| LLM-verifier agreement | 0.0% [0.0%, 2.4%] (0/153) | 0.0% [0.0%, 2.4%] (0/153) | 0.0% [0.0%, 2.5%] (0/148) |
| **Breaches silently CLEARed** | **0** | **0** | **0** |
| **Silent sensors CLEARed** | **0** | **0** | **0** |

Verdict accuracy by dataset:

| Dataset | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| energy | 12.7% [6.3%, 24.0%] (7/55) | 12.7% [6.3%, 24.0%] (7/55) | 12.7% [6.3%, 24.0%] (7/55) |
| finance | 14.7% [9.6%, 21.9%] (19/129) | 14.7% [9.6%, 21.9%] (19/129) | 16.3% [10.9%, 23.6%] (21/129) |
| manufacturing | 21.1% [14.9%, 29.0%] (27/128) | 21.1% [14.9%, 29.0%] (27/128) | 21.1% [14.9%, 29.0%] (27/128) |

Same verdict under every seed: 89.7% [85.9%, 92.6%] (280/312).

