"""Tests for the v3 backend factory.

``build_backend()`` reads ``$SKI_V3_LLM_BACKEND`` and returns a
configured backend. The Ollama backend's ``/api/show`` call is allowed
to fail at construction time — the backend falls back to a vendor
commitment string so the runtime still has a deterministic
``model_weight_hash``.
"""

from __future__ import annotations

import pytest

from ski_model.v3 import FakeLLM, OllamaV3Backend, build_backend


class TestFactory:
    def test_default_is_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_V3_LLM_BACKEND", raising=False)
        backend = build_backend()
        assert isinstance(backend, FakeLLM)

    def test_explicit_fake_returns_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
        backend = build_backend()
        assert isinstance(backend, FakeLLM)

    def test_fake_uses_real_framework_hashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
        backend = build_backend()
        # The factory injects the real framework hashes so even FakeLLM
        # reports correct provenance for the framework prompt + grammar.
        from ski_model.v3 import PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH

        assert backend.prompt_template_hash == PROMPT_TEMPLATE_HASH
        assert backend.structured_grammar_hash == STRUCTURED_GRAMMAR_HASH

    def test_unknown_backend_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "claude-magic")
        with pytest.raises(RuntimeError, match="not a known v3 backend"):
            build_backend()

    def test_ollama_backend_constructs_with_fallback_provenance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point at a definitely-unreachable Ollama; /api/show should fail
        # and the backend should fall back to a vendor commitment string.
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.setenv("SKI_MODEL_NAME", "test-model")
        backend = build_backend()
        assert isinstance(backend, OllamaV3Backend)
        assert backend.model_weight_hash.startswith("sha256:")
        # 64 hex chars after sha256:
        assert len(backend.model_weight_hash) == 71
