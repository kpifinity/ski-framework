"""SKI Model — runtime inference service for the SKI Framework v3.

The v3 architecture is neuro-symbolic: a KG-grounded LLM is the primary
inference path, and a symbolic verifier mechanically cross-checks the
LLM's formalizable assertions against the rule engine. See spec v3.0 in
``docs/specification-v3.md`` and the foundational architecture rationale
in ``docs/RFCs/0002-v3-neuro-symbolic-pivot.md``.

This module implements the Phase 2 (runtime) component: it receives
measurements, routes them through :class:`ski_model.v3.evaluator.V3Evaluator`,
and writes the resulting :class:`ski_model.v3.envelope.V3VerdictEnvelope`
to an immutable, hash-chained audit ledger.
"""

__version__ = "3.0.0-alpha"
