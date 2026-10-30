"""Framework-side hashes recorded in :class:`ModelProvenance`.

Every conformant ``V3LLMBackend`` reports these hashes to the evaluator so
the produced :class:`V3VerdictEnvelope` provenance fields are accurate:

  * :data:`PROMPT_TEMPLATE_HASH` — sha256 of the canonical
    :data:`PROMPT_TEMPLATE` text. If the template is edited the hash
    changes; auditors notice and can flag verdicts produced under an
    older template.
  * :data:`STRUCTURED_GRAMMAR_HASH` — sha256 of the spec §7.3 canonical
    JSON of :data:`RESPONSE_GRAMMAR`. Same reasoning.

These are deliberately computed once at import time so every backend in
the same process reports identical values.
"""

from __future__ import annotations

import hashlib

from ski_schemas.canonical import sha256_canonical

from ..evaluator import PROMPT_TEMPLATE, RESPONSE_GRAMMAR


def _sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


PROMPT_TEMPLATE_HASH: str = _sha256_prefixed(PROMPT_TEMPLATE.encode("utf-8"))
"""sha256 of :data:`PROMPT_TEMPLATE` as UTF-8 bytes."""


STRUCTURED_GRAMMAR_HASH: str = sha256_canonical(RESPONSE_GRAMMAR)
"""sha256 of the spec §7.3 canonical JSON of :data:`RESPONSE_GRAMMAR`."""


__all__ = ["PROMPT_TEMPLATE_HASH", "STRUCTURED_GRAMMAR_HASH"]
