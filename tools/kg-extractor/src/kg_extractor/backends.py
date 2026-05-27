"""LLM backend abstraction for kg-extractor.

Phase 1 (compilation) is permitted to use cloud LLMs because the output
is signed and validated before the boundary crossing. The extractor
defaults to a local backend, but `anthropic` and `openai` are also
available for compilation-phase use.

NONE of these backends are conformant when used at the SKI Model runtime.
The extractor refuses to talk to runtime endpoints.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class ExtractionCallResult:
    text: str
    backend: str
    model: str
    seed: Optional[int]
    temperature: float
    prompt_sha256: str


class ExtractorBackend(Protocol):
    name: str
    model: str

    def extract_json(self, prompt: str, max_tokens: int) -> ExtractionCallResult: ...


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Local Ollama (default, preferred for reproducibility)
# ---------------------------------------------------------------------------


class OllamaBackend:
    name = "ollama"

    def __init__(self, *, model: str, base_url: str, seed: int = 42, temperature: float = 0.0):
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._seed = seed
        self._temperature = temperature

    def extract_json(self, prompt: str, max_tokens: int) -> ExtractionCallResult:
        import httpx

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._temperature,
                "seed": self._seed,
                "num_predict": max_tokens,
                "top_p": 1.0,
                "top_k": 1,
            },
        }
        resp = httpx.post(f"{self._base_url}/api/generate", json=payload, timeout=120.0)
        resp.raise_for_status()
        return ExtractionCallResult(
            text=resp.json().get("response", ""),
            backend=self.name,
            model=self.model,
            seed=self._seed,
            temperature=self._temperature,
            prompt_sha256=_hash_prompt(prompt),
        )


# ---------------------------------------------------------------------------
# Anthropic (compilation-phase only)
# ---------------------------------------------------------------------------


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, *, model: str, api_key: str, temperature: float = 0.0, seed: Optional[int] = None):
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic backend requires `pip install anthropic`. "
                "Or — preferably — use the ollama backend."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self._temperature = temperature
        self._seed = seed  # Anthropic API does not currently honour `seed`; recorded for audit only.

    def extract_json(self, prompt: str, max_tokens: int) -> ExtractionCallResult:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else ""
        return ExtractionCallResult(
            text=text,
            backend=self.name,
            model=self.model,
            seed=self._seed,
            temperature=self._temperature,
            prompt_sha256=_hash_prompt(prompt),
        )


# ---------------------------------------------------------------------------
# OpenAI (compilation-phase only)
# ---------------------------------------------------------------------------


class OpenAIBackend:
    name = "openai"

    def __init__(self, *, model: str, api_key: str, temperature: float = 0.0, seed: Optional[int] = 42):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai backend requires `pip install openai`. Or — preferably — use the ollama backend."
            ) from exc
        self._client = OpenAI(api_key=api_key)
        self.model = model
        self._temperature = temperature
        self._seed = seed

    def extract_json(self, prompt: str, max_tokens: int) -> ExtractionCallResult:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            seed=self._seed,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content or ""
        return ExtractionCallResult(
            text=text,
            backend=self.name,
            model=self.model,
            seed=self._seed,
            temperature=self._temperature,
            prompt_sha256=_hash_prompt(prompt),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_backend(name: Optional[str] = None) -> ExtractorBackend:
    name = (name or os.getenv("KG_EXTRACTOR_LLM_BACKEND", "ollama")).lower()
    if name == "ollama":
        return OllamaBackend(
            model=os.getenv("KG_EXTRACTOR_MODEL", "qwen2.5:7b-instruct"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            seed=int(os.getenv("KG_EXTRACTOR_SEED", "42")),
            temperature=float(os.getenv("KG_EXTRACTOR_TEMPERATURE", "0")),
        )
    if name == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for the anthropic backend.")
        return AnthropicBackend(
            model=os.getenv("KG_EXTRACTOR_MODEL", "claude-haiku-4-5-20251001"),
            api_key=api_key,
            temperature=float(os.getenv("KG_EXTRACTOR_TEMPERATURE", "0")),
        )
    if name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY required for the openai backend.")
        return OpenAIBackend(
            model=os.getenv("KG_EXTRACTOR_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            temperature=float(os.getenv("KG_EXTRACTOR_TEMPERATURE", "0")),
            seed=int(os.getenv("KG_EXTRACTOR_SEED", "42")),
        )
    raise RuntimeError(f"Unknown KG_EXTRACTOR_LLM_BACKEND: {name!r}")
