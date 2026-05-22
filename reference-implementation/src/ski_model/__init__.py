"""SKI Model — runtime inference service for the SKI Framework v2.1.

Implements the Phase 2 (runtime) component. Routes telemetry through the
Symbolic Evaluator (Track 1) or a bounded local LLM (Track 2) based on rule
classification. Writes verdicts to an immutable, hash-chained audit ledger.
"""

__version__ = "0.1.0-alpha"
