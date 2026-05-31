"""Tests for the framework-side provenance hashes.

PROMPT_TEMPLATE_HASH and STRUCTURED_GRAMMAR_HASH are sha256 over the
canonical framework constants. Every conformant backend records these
in ModelProvenance so an auditor can confirm the backend was bound to
the framework's contract at evaluation time.
"""

from __future__ import annotations

from ski_model.v3 import PROMPT_TEMPLATE, PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH
from ski_model.v3.backends.hashes import _sha256_prefixed


class TestFrameworkHashes:
    def test_prompt_template_hash_is_sha256_prefixed_hex(self) -> None:
        assert PROMPT_TEMPLATE_HASH.startswith("sha256:")
        assert len(PROMPT_TEMPLATE_HASH) == len("sha256:") + 64
        # All-hex tail
        int(PROMPT_TEMPLATE_HASH[len("sha256:") :], 16)

    def test_structured_grammar_hash_is_sha256_prefixed_hex(self) -> None:
        assert STRUCTURED_GRAMMAR_HASH.startswith("sha256:")
        assert len(STRUCTURED_GRAMMAR_HASH) == len("sha256:") + 64
        int(STRUCTURED_GRAMMAR_HASH[len("sha256:") :], 16)

    def test_prompt_hash_matches_actual_template_bytes(self) -> None:
        assert _sha256_prefixed(PROMPT_TEMPLATE.encode("utf-8")) == PROMPT_TEMPLATE_HASH

    def test_hashes_are_distinct(self) -> None:
        assert PROMPT_TEMPLATE_HASH != STRUCTURED_GRAMMAR_HASH
