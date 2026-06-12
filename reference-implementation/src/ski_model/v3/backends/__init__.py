"""v3 LLM backend implementations.

The framework is LLM-agnostic: ``V3LLMBackend`` (in ``v3/evaluator.py``)
is the protocol every backend implements. This subpackage groups the
concrete implementations and the factory.

  * :class:`FakeLLM` — deterministic pattern-matcher for tests + CI.
    Lives in :mod:`ski_model.v3.evaluator` for historical reasons; the
    factory re-exposes it for symmetry.
  * :class:`OllamaV3Backend` — calls a local Ollama runtime over HTTP
    with deterministic options (temperature=0, fixed seed, JSON-only
    output). The model weights stay on the operator's hardware, which
    satisfies the "Sovereign" property of the framework.

Constants:

  * :data:`PROMPT_TEMPLATE_HASH`, :data:`STRUCTURED_GRAMMAR_HASH` —
    sha256 of the canonical framework prompt and structured-output
    grammar. Every conformant backend records these in
    :class:`ModelProvenance` so an auditor can confirm the backend was
    bound to the framework's contract.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .hashes import PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH
from .ollama import OllamaV3Backend
from .vllm import VLLMV3Backend

if TYPE_CHECKING:
    from ..evaluator import V3LLMBackend


def build_backend() -> V3LLMBackend:
    """Construct the backend named by ``$SKI_V3_LLM_BACKEND``.

    Recognised values:

      * ``"fake"`` (default) — :class:`FakeLLM`. No I/O, fully
        deterministic, used by CI.
      * ``"ollama"`` — :class:`OllamaV3Backend`. Reads ``$OLLAMA_BASE_URL``
        (default ``http://ollama:11434``), ``$SKI_MODEL_NAME`` (default
        ``qwen2.5:7b-instruct``), ``$SKI_MODEL_SEED`` (default 42),
        ``$SKI_MODEL_MAX_TOKENS`` (default 512).
      * ``"vllm"`` — :class:`VLLMV3Backend`. Reads ``$VLLM_BASE_URL``
        (default ``http://vllm:8000``), ``$SKI_MODEL_NAME`` (default
        ``Qwen/Qwen2.5-7B-Instruct``), ``$SKI_MODEL_SEED``,
        ``$SKI_MODEL_MAX_TOKENS``, ``$SKI_VLLM_TIMEOUT_S`` (default 120),
        and ``$SKI_MODEL_FILE_SHA256`` (the served-weights digest — set
        it; the fallback vendor commitment is a weaker provenance
        signal).

    Unknown values raise ``RuntimeError`` early so a misconfigured
    deployment cannot silently fall through to a default.
    """
    name = os.getenv("SKI_V3_LLM_BACKEND", "fake").lower()
    if name == "fake":
        # Imported lazily to avoid a circular import at module load.
        from ..evaluator import FakeLLM

        return FakeLLM(
            prompt_template_hash=PROMPT_TEMPLATE_HASH,
            structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        )
    if name == "ollama":
        return OllamaV3Backend(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            model_name=os.getenv("SKI_MODEL_NAME", "qwen2.5:7b-instruct"),
            seed=int(os.getenv("SKI_MODEL_SEED", "42")),
            max_tokens=int(os.getenv("SKI_MODEL_MAX_TOKENS", "512")),
            request_timeout_seconds=float(os.getenv("SKI_OLLAMA_TIMEOUT_S", "60")),
            prompt_template_hash=PROMPT_TEMPLATE_HASH,
            structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        )
    if name == "vllm":
        return VLLMV3Backend(
            base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000"),
            model_name=os.getenv("SKI_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct"),
            seed=int(os.getenv("SKI_MODEL_SEED", "42")),
            max_tokens=int(os.getenv("SKI_MODEL_MAX_TOKENS", "1536")),
            request_timeout_seconds=float(os.getenv("SKI_VLLM_TIMEOUT_S", "120")),
            model_file_sha256=os.getenv("SKI_MODEL_FILE_SHA256") or None,
            prompt_template_hash=PROMPT_TEMPLATE_HASH,
            structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        )
    raise RuntimeError(
        f"SKI_V3_LLM_BACKEND={name!r} is not a known v3 backend. Expected one of: 'fake', 'ollama', 'vllm'."
    )


__all__ = [
    "PROMPT_TEMPLATE_HASH",
    "STRUCTURED_GRAMMAR_HASH",
    "OllamaV3Backend",
    "VLLMV3Backend",
    "build_backend",
]
