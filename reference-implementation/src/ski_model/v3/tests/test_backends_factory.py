"""Tests for the v3 backend factory.

``build_backend()`` reads ``$SKI_V3_LLM_BACKEND`` (alias
``$SKI_INFERENCE_BACKEND``) and returns a configured backend. Without a
weight pin, the Ollama backend's ``/api/show`` call is allowed to fail at
construction time: the backend records a labelled name commitment
(``model_hash_verified=false``) so the runtime still has a deterministic
``model_weight_hash``.
"""

from __future__ import annotations

import pytest

from ski_model.v3 import FakeLLM, OllamaV3Backend, build_backend
from ski_model.v3.backends import (
    BackendConfigError,
    ModelHashError,
    fake_llm_allowed,
    resolve_backend_name,
)


class TestBackendSelection:
    """v3.2.0: backend truth (C4). The alias is honoured, conflicts and an
    implicit FakeLLM refuse to start."""

    def test_canonical_name_wins_and_is_lowercased(self) -> None:
        assert resolve_backend_name({"SKI_V3_LLM_BACKEND": " Ollama "}) == "ollama"

    def test_alias_is_accepted(self) -> None:
        assert resolve_backend_name({"SKI_INFERENCE_BACKEND": "ollama"}) == "ollama"

    def test_both_set_and_equal_is_fine(self) -> None:
        env = {"SKI_V3_LLM_BACKEND": "vllm", "SKI_INFERENCE_BACKEND": "VLLM"}
        assert resolve_backend_name(env) == "vllm"

    def test_both_set_and_different_refuses(self) -> None:
        env = {"SKI_V3_LLM_BACKEND": "fake", "SKI_INFERENCE_BACKEND": "ollama"}
        with pytest.raises(BackendConfigError, match="disagree"):
            resolve_backend_name(env)

    def test_unset_defaults_to_fake(self) -> None:
        assert resolve_backend_name({}) == "fake"
        assert resolve_backend_name({"SKI_V3_LLM_BACKEND": "", "SKI_INFERENCE_BACKEND": " "}) == "fake"

    @pytest.mark.parametrize("value", ["true", "TRUE", " True "])
    def test_fake_allowed_only_when_explicitly_true(self, value: str) -> None:
        assert fake_llm_allowed({"SKI_ALLOW_FAKE_LLM": value}) is True

    @pytest.mark.parametrize("value", ["", "1", "yes", "false", "on"])
    def test_fake_not_allowed_otherwise(self, value: str) -> None:
        assert fake_llm_allowed({"SKI_ALLOW_FAKE_LLM": value}) is False
        assert fake_llm_allowed({}) is False

    def test_build_refuses_fake_without_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
        monkeypatch.delenv("SKI_ALLOW_FAKE_LLM", raising=False)
        with pytest.raises(BackendConfigError, match="SKI_ALLOW_FAKE_LLM=true"):
            build_backend()

    def test_build_refuses_implicit_default_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_V3_LLM_BACKEND", raising=False)
        monkeypatch.delenv("SKI_INFERENCE_BACKEND", raising=False)
        monkeypatch.setenv("SKI_ALLOW_FAKE_LLM", "false")
        with pytest.raises(BackendConfigError, match="NOT conformant"):
            build_backend()

    def test_build_refuses_conflicting_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The v3.1.x footgun: compose set the alias, code read the canonical.
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
        monkeypatch.setenv("SKI_INFERENCE_BACKEND", "ollama")
        with pytest.raises(BackendConfigError, match="disagree"):
            build_backend()

    def test_build_honours_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_V3_LLM_BACKEND", raising=False)
        monkeypatch.setenv("SKI_INFERENCE_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
        assert isinstance(build_backend(), OllamaV3Backend)

    def test_build_refuses_weight_pin_on_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "fake")
        monkeypatch.setenv("SKI_ALLOW_FAKE_LLM", "true")
        monkeypatch.setenv("SKI_MODEL_FILE_SHA256", "a" * 64)
        with pytest.raises(ModelHashError, match="no weights"):
            build_backend()

    def test_build_refuses_malformed_pin_before_any_io(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "ollama")
        monkeypatch.setenv("SKI_MODEL_FILE_SHA256", "latest")
        with pytest.raises(ModelHashError, match="SHA-256"):
            build_backend()

    def test_build_pin_with_unreachable_ollama_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKI_V3_LLM_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.setenv("SKI_MODEL_FILE_SHA256", "a" * 64)
        with pytest.raises(ModelHashError, match="cannot be verified"):
            build_backend()


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
        with pytest.raises(BackendConfigError, match="not a known v3 backend"):
            build_backend()

    def test_former_anthropic_demo_mode_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # docs/compose once advertised SKI_INFERENCE_BACKEND=anthropic.
        monkeypatch.delenv("SKI_V3_LLM_BACKEND", raising=False)
        monkeypatch.setenv("SKI_INFERENCE_BACKEND", "anthropic")
        with pytest.raises(BackendConfigError, match="not a known v3 backend"):
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
