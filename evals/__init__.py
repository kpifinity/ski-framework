"""SKI Evals — the verdict-accuracy evaluation suite.

Conformance (``conformance/``) proves the plumbing: envelopes are
well-formed, ledgers are append-only, KGs are signed. SKI Evals proves
the *judgment*: that the neuro-symbolic evaluator produces the right
verdict on telemetry whose correct outcome is known in advance.

Each dataset under ``evals/datasets/<sector>/`` pairs an evaluation
Knowledge Graph with human-labeled golden cases. The runner drives the
real production path — ``kg_loader`` scoping followed by
``V3Evaluator.aevaluate`` — against any configured LLM backend, and
reports accuracy, FLAG recall (missed breaches), FLAG precision,
assertion correctness, and the LLM-verifier agreement rate.

Run it:

    python -m evals.run --backend fake            # CI / harness check
    python -m evals.run --backend ollama          # real model numbers

See ``docs/evals.md`` for the methodology.
"""

__version__ = "0.1.0"
