"""Tag Registry (B4.3) — governed mapping from telemetry subject to KG rule.

The Tag Registry is the ONLY mechanism by which a telemetry subject is
resolved to a Knowledge Graph rule at runtime. It is compiled during
Phase 1 (KG compilation) and ships embedded in the signed KG. Runtime tag
inference (substring matching, embedding lookup, LLM disambiguation, etc.)
is architecturally prohibited because it would inject probabilistic
ambiguity into what must be a deterministic routing decision.

This package exposes a single class:

    TagRegistry — immutable lookup table built from a signed Knowledge Graph.

The lookup is keyed on a normalised form of the subject (lowercase, trimmed,
whitespace collapsed). Disambiguation between similar subjects must happen
at compile time in the KG, not at runtime.
"""

from .registry import TagRegistry

__all__ = ["TagRegistry"]
