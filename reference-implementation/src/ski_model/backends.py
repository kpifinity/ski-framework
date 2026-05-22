"""Inference backend abstraction.

The SKI Framework v2.1 specification permits any inference runtime so long
as the determinism, sovereignty, and structured-output requirements are met.
This module provides a thin abstraction so the rest of the codebase never
depends on a specific vendor.

  ollama     — Local LLM runtime (default). Conformant.
  anthropic  — Cloud API. NON-CONFORMANT DEMO MODE ONLY. Logs a warning on
               every call. Disqualifies the deployment from all conformance
               levels.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import httpx

from .verdicts import Verdict

logger = logging.getLogger(__name__)


@dataclass
class BackendDecision:
    verdict: Verdict
    reasoning: str


class InferenceBackend(Protocol):
    name: str

    async def evaluate(self, rule: dict[str, Any], telemetry: dict[str, Any]) -> BackendDecision: ...

    async def canary_eval(self, fixed_input: dict[str, Any]) -> dict[str, Any]: ...


# ----------------------------------------------------------------------------
# Ollama backend
# ----------------------------------------------------------------------------


class OllamaBackend:
    name = "ollama"

    def __init__(self, base_url: str, model: str, seed: int, max_tokens: int):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._seed = seed
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    async def evaluate(self, rule: dict[str, Any], telemetry: dict[str, Any]) -> BackendDecision:
        prompt = self._build_prompt(rule, telemetry)
        response = await self._call(prompt)
        return self._parse(response)

    async def canary_eval(self, fixed_input: dict[str, Any]) -> dict[str, Any]:
        prompt = json.dumps(fixed_input, sort_keys=True)
        raw = await self._call(prompt)
        return {"raw": raw}

    async def _call(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "seed": self._seed,
                "num_predict": self._max_tokens,
                "top_p": 1.0,
                "top_k": 1,
            },
        }
        resp = await self._client.post(f"{self._base_url}/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _build_prompt(self, rule: dict[str, Any], telemetry: dict[str, Any]) -> str:
        return (
            "You are evaluating a single regulatory rule against a single telemetry record.\n"
            "Respond with STRICT JSON ONLY, matching this schema:\n"
            '  {"verdict": "CLEAR"|"FLAG"|"DISCRETIONARY", "reasoning": "..."}\n'
            "Do not include any other keys, prose, or formatting.\n"
            "\n"
            f"Rule: {json.dumps(rule, sort_keys=True)}\n"
            f"Telemetry: {json.dumps(telemetry, sort_keys=True)}\n"
        )

    def _parse(self, raw: str) -> BackendDecision:
        try:
            obj = json.loads(raw)
            v_raw = obj.get("verdict", "")
            if v_raw not in {"CLEAR", "FLAG", "DISCRETIONARY"}:
                raise ValueError(f"Verdict {v_raw!r} not in permitted Track 2 set.")
            return BackendDecision(
                verdict=Verdict(v_raw),
                reasoning=str(obj.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("Backend output did not parse: %s; raw=%r", exc, raw)
            # Per spec: a non-conforming output must NOT be guessed.
            return BackendDecision(
                verdict=Verdict.DISCRETIONARY,
                reasoning=f"Backend produced non-conforming output: {exc}",
            )


# ----------------------------------------------------------------------------
# Anthropic backend — DEMO MODE ONLY
# ----------------------------------------------------------------------------


class AnthropicDemoBackend:
    """Calls the Anthropic API. Disqualifies the deployment from conformance.

    Provided so a user evaluating the architecture before standing up a
    local inference runtime can still exercise the end-to-end flow. The
    backend logs a loud warning on every initialisation and every call.
    """

    name = "anthropic-demo"

    def __init__(self, api_key: str, model: str, max_tokens: int):
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic demo backend requires `pip install anthropic`. "
                "Or — preferably — switch SKI_INFERENCE_BACKEND=ollama."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        logger.warning(
            "ANTHROPIC DEMO BACKEND ACTIVE. This makes outbound calls to a US-based "
            "cloud API and DISQUALIFIES this deployment from all SKI conformance "
            "levels. Use only for local evaluation; never with real regulated data."
        )

    async def evaluate(self, rule: dict[str, Any], telemetry: dict[str, Any]) -> BackendDecision:
        logger.warning("Anthropic demo call (rule=%s)", rule.get("id"))
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Evaluate the rule against the telemetry. Reply with JSON only: "
                        '{"verdict": "CLEAR"|"FLAG"|"DISCRETIONARY", "reasoning": "..."}\n\n'
                        f"Rule: {json.dumps(rule, sort_keys=True)}\n"
                        f"Telemetry: {json.dumps(telemetry, sort_keys=True)}"
                    ),
                }
            ],
        )
        text = msg.content[0].text if msg.content else ""
        try:
            obj = json.loads(text)
            v_raw = obj.get("verdict")
            if v_raw not in {"CLEAR", "FLAG", "DISCRETIONARY"}:
                raise ValueError(f"Verdict {v_raw!r} not in permitted set.")
            return BackendDecision(verdict=Verdict(v_raw), reasoning=str(obj.get("reasoning", "")))
        except Exception as exc:
            return BackendDecision(verdict=Verdict.DISCRETIONARY, reasoning=f"Demo backend output not parseable: {exc}")

    async def canary_eval(self, fixed_input: dict[str, Any]) -> dict[str, Any]:
        return {"raw": "anthropic-demo backend cannot be canary-verified for determinism."}


# ----------------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------------


def build_backend() -> InferenceBackend:
    name = os.getenv("SKI_INFERENCE_BACKEND", "ollama").lower()
    if name == "ollama":
        return OllamaBackend(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            model=os.getenv("SKI_MODEL_NAME", "qwen2.5:7b-instruct"),
            seed=int(os.getenv("SKI_MODEL_SEED", "42")),
            max_tokens=int(os.getenv("SKI_MODEL_MAX_TOKENS", "512")),
        )
    if name == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "SKI_INFERENCE_BACKEND=anthropic requires ANTHROPIC_API_KEY. "
                "But you almost certainly want SKI_INFERENCE_BACKEND=ollama — "
                "the Anthropic backend is non-conformant demo mode only."
            )
        return AnthropicDemoBackend(
            api_key=api_key,
            model=os.getenv("SKI_MODEL_NAME", "claude-haiku-4-5-20251001"),
            max_tokens=int(os.getenv("SKI_MODEL_MAX_TOKENS", "512")),
        )
    raise RuntimeError(f"Unknown SKI_INFERENCE_BACKEND={name!r}")
