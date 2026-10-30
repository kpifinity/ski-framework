"""v3 LLM backend implementations.

The framework is LLM-agnostic: ``V3LLMBackend`` (in ``v3/evaluator.py``)
is the protocol every backend implements. This subpackage groups the
concrete implementations and the factory.

  * :class:`FakeLLM` — deterministic pattern-matcher for tests + CI.
    Lives in :mod:`ski_model.v3.evaluator` for historical reasons; the
    factory re-exposes it for symmetry. NOT conformant: the factory
    refuses to build it unless ``SKI_ALLOW_FAKE_LLM=true``.
  * :class:`OllamaV3Backend` — calls a local Ollama runtime over HTTP
    with deterministic options (temperature=0, fixed seed, JSON-only
    output). The model weights stay on the operator's hardware, which
    satisfies the "Sovereign" property of the framework.
  * :class:`VLLMV3Backend` — local vLLM over the OpenAI-compatible API.

Constants:

  * :data:`PROMPT_TEMPLATE_HASH`, :data:`STRUCTURED_GRAMMAR_HASH` —
    sha256 of the canonical framework prompt and structured-output
    grammar. Every conformant backend records these in
    :class:`ModelProvenance` so an auditor can confirm the backend was
    bound to the framework's contract.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Final, Mapping, Optional

from .hashes import PROMPT_TEMPLATE_HASH, STRUCTURED_GRAMMAR_HASH
from .model_hash import EXPECTED_HASH_ENV, MODEL_FILE_PATH_ENV, ModelHashError, expected_model_hash
from .ollama import OllamaV3Backend
from .vllm import VLLMV3Backend

if TYPE_CHECKING:
    from ..evaluator import V3LLMBackend

logger = logging.getLogger(__name__)

BACKEND_ENV: Final = "SKI_V3_LLM_BACKEND"
"""Canonical backend selector."""

BACKEND_ALIAS_ENV: Final = "SKI_INFERENCE_BACKEND"
"""Accepted alias (the name docker-compose and ``.env.example`` used up to v3.1.x)."""

ALLOW_FAKE_ENV: Final = "SKI_ALLOW_FAKE_LLM"
"""Must be exactly ``true`` (any case) for the runtime to start with ``fake``."""

DEFAULT_BACKEND: Final = "fake"
KNOWN_BACKENDS: Final = ("fake", "ollama", "vllm")


class BackendConfigError(RuntimeError):
    """The backend configuration is ambiguous or unsafe; the runtime must not start."""


def resolve_backend_name(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the configured backend name (lower-cased).

    ``SKI_V3_LLM_BACKEND`` is canonical; ``SKI_INFERENCE_BACKEND`` is an
    alias. If both are set to different values the deployment is
    ambiguous (v3.1.x silently ignored the alias and ran FakeLLM), so
    this raises :class:`BackendConfigError` instead of picking one.
    Neither set => :data:`DEFAULT_BACKEND` (``fake``), which
    :func:`build_backend` then refuses unless ``SKI_ALLOW_FAKE_LLM=true``.
    """
    source = os.environ if env is None else env
    canonical = source.get(BACKEND_ENV, "").strip().lower()
    alias = source.get(BACKEND_ALIAS_ENV, "").strip().lower()
    if canonical and alias and canonical != alias:
        raise BackendConfigError(
            f"{BACKEND_ENV}={canonical!r} and {BACKEND_ALIAS_ENV}={alias!r} disagree. "
            f"Refusing to start: set only {BACKEND_ENV} ({BACKEND_ALIAS_ENV} is a "
            "deprecated alias)."
        )
    if alias and not canonical:
        logger.warning("%s is a deprecated alias; set %s=%s instead.", BACKEND_ALIAS_ENV, BACKEND_ENV, alias)
    return canonical or alias or DEFAULT_BACKEND


def fake_llm_allowed(env: Optional[Mapping[str, str]] = None) -> bool:
    """``True`` only when ``SKI_ALLOW_FAKE_LLM`` is explicitly ``true``."""
    source = os.environ if env is None else env
    return source.get(ALLOW_FAKE_ENV, "").strip().lower() == "true"


def build_backend() -> V3LLMBackend:
    """Construct the backend named by ``$SKI_V3_LLM_BACKEND`` (alias ``$SKI_INFERENCE_BACKEND``).

    Recognised values:

      * ``"fake"`` (default when unset) — :class:`FakeLLM`. No I/O, fully
        deterministic, NOT conformant. Refused unless
        ``SKI_ALLOW_FAKE_LLM=true`` (demo stack, CI, tests), so a
        deployment that forgot to select a backend cannot silently serve
        pattern-matched verdicts.
      * ``"ollama"`` — :class:`OllamaV3Backend`. Reads ``$OLLAMA_BASE_URL``
        (default ``http://ollama:11434``), ``$SKI_MODEL_NAME`` (default
        ``qwen2.5:7b-instruct``), ``$SKI_MODEL_SEED`` (default 42),
        ``$SKI_MODEL_MAX_TOKENS`` (default 512), ``$SKI_OLLAMA_TIMEOUT_S``.
      * ``"vllm"`` — :class:`VLLMV3Backend`. Reads ``$VLLM_BASE_URL``
        (default ``http://vllm:8000``), ``$SKI_MODEL_NAME`` (default
        ``Qwen/Qwen2.5-7B-Instruct``), ``$SKI_MODEL_SEED``,
        ``$SKI_MODEL_MAX_TOKENS``, ``$SKI_VLLM_TIMEOUT_S`` (default 120),
        and ``$SKI_MODEL_FILE_PATH`` (optional weights file to hash).

    ``$SKI_MODEL_FILE_SHA256`` pins the expected weights digest for every
    real backend; see :mod:`.model_hash` for what each backend can verify.
    A malformed or unverifiable pin, or a mismatch, raises
    :class:`~.model_hash.ModelHashError`.

    Unknown values raise :class:`BackendConfigError` early so a
    misconfigured deployment cannot silently fall through to a default.
    """
    name = resolve_backend_name()
    expected = expected_model_hash()
    if name == "fake":
        if not fake_llm_allowed():
            raise BackendConfigError(
                f"{BACKEND_ENV} resolves to 'fake' (the default when unset), the "
                "pattern-matching FakeLLM, which is NOT conformant. Refusing to start. "
                f"Set {BACKEND_ENV}=ollama or vllm, or set {ALLOW_FAKE_ENV}=true for "
                "demos, CI and tests only."
            )
        if expected is not None:
            raise ModelHashError(
                f"{EXPECTED_HASH_ENV} pins model weights but the backend is 'fake', which "
                "has no weights to verify. Refusing to start."
            )
        # Imported lazily to avoid a circular import at module load.
        from ..evaluator import FakeLLM

        logger.warning(
            "Inference backend is FakeLLM (%s=true). Verdicts are pattern-matched, "
            "NOT model-evaluated; this deployment is not conformant.",
            ALLOW_FAKE_ENV,
        )
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
            expected_model_hash=expected,
        )
    if name == "vllm":
        return VLLMV3Backend(
            base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000"),
            model_name=os.getenv("SKI_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct"),
            seed=int(os.getenv("SKI_MODEL_SEED", "42")),
            max_tokens=int(os.getenv("SKI_MODEL_MAX_TOKENS", "1536")),
            request_timeout_seconds=float(os.getenv("SKI_VLLM_TIMEOUT_S", "120")),
            model_file_sha256=expected,
            model_file_path=os.getenv(MODEL_FILE_PATH_ENV) or None,
            prompt_template_hash=PROMPT_TEMPLATE_HASH,
            structured_grammar_hash=STRUCTURED_GRAMMAR_HASH,
        )
    raise BackendConfigError(
        f"{BACKEND_ENV}={name!r} is not a known v3 backend. Expected one of: 'fake', 'ollama', 'vllm'."
    )


__all__ = [
    "ALLOW_FAKE_ENV",
    "BACKEND_ALIAS_ENV",
    "BACKEND_ENV",
    "DEFAULT_BACKEND",
    "KNOWN_BACKENDS",
    "PROMPT_TEMPLATE_HASH",
    "STRUCTURED_GRAMMAR_HASH",
    "BackendConfigError",
    "ModelHashError",
    "OllamaV3Backend",
    "VLLMV3Backend",
    "build_backend",
    "fake_llm_allowed",
    "resolve_backend_name",
]
