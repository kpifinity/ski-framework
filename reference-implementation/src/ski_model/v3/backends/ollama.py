"""Ollama-v3 backend — local KG-grounded LLM inference.

Ollama is the reference local-weights backend because it satisfies the
**Sovereign** part of "Sovereign Knowledge Intelligence":

  * Weights live on the operator's hardware. The :attr:`model_weight_hash`
    field of :class:`ModelProvenance` is the actual model digest reported
    by Ollama's ``/api/show`` endpoint — auditors can independently
    verify the exact weights that produced any historical verdict.
  * No data leaves the deployment perimeter. The HTTP call goes to a
    local-network Ollama instance.
  * Determinism: ``temperature=0``, fixed ``seed``, ``top_p=1.0``,
    ``top_k=1``, ``num_predict`` bounded. Same input → same output
    bit-for-bit (per Ollama's documented determinism guarantees).
  * Structured output: ``format="json"`` plus the framework prompt
    explicitly demands the :data:`RESPONSE_GRAMMAR` shape. Malformed
    output is mapped to ``DISCRETIONARY`` rather than guessed at.

The backend renders the canonical prompt itself from the measurement +
KG snapshot (matching what :class:`V3Evaluator` records in the
transcript). Real production prompts may be richer (system messages,
few-shot examples) but the transcript records the framework-canonical
form, which is what an auditor replays.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional

import httpx

from ..evaluator import PROMPT_TEMPLATE, PROMPT_TEMPLATE_ID, RESPONSE_GRAMMAR

logger = logging.getLogger(__name__)


class OllamaV3Backend:
    """Calls a local Ollama runtime; conforms to :class:`V3LLMBackend`."""

    name = "ollama-v3"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        seed: int,
        max_tokens: int,
        prompt_template_hash: str,
        structured_grammar_hash: str,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._seed = seed
        self._max_tokens = max_tokens
        self._prompt_template_hash = prompt_template_hash
        self._structured_grammar_hash = structured_grammar_hash
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(request_timeout_seconds))
        self._model_weight_hash = self._discover_model_weight_hash()

    # ---- V3LLMBackend protocol -------------------------------------------------

    @property
    def model_weight_hash(self) -> str:
        return self._model_weight_hash

    @property
    def prompt_template_id(self) -> str:
        return PROMPT_TEMPLATE_ID

    @property
    def prompt_template_hash(self) -> str:
        return self._prompt_template_hash

    @property
    def structured_grammar_hash(self) -> str:
        return self._structured_grammar_hash

    async def evaluate(
        self,
        *,
        measurement: Dict[str, Any],
        kg_snapshot: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        """Render the canonical prompt and call Ollama's ``/api/generate``.

        Returns the parsed structured-output dict matching
        :data:`ski_model.v3.evaluator.RESPONSE_GRAMMAR`. Malformed output
        is mapped to ``DISCRETIONARY`` per spec §5.2 — non-conforming
        output is never guessed at.
        """
        prompt = self._render_prompt(measurement, kg_snapshot)
        payload = {
            "model": self._model_name,
            "prompt": prompt,
            "stream": False,
            "format": RESPONSE_GRAMMAR,  # JSON-schema-constrained decoding (Ollama >= 0.5)
            "options": {
                "temperature": 0,
                "seed": seed,
                "num_predict": self._max_tokens,
                "top_p": 1.0,
                "top_k": 1,
            },
        }
        try:
            response = await self._client.post(f"{self._base_url}/api/generate", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %r", exc)
            return _discretionary_response(f"Ollama backend transport error: {exc.__class__.__name__}: {exc}")

        body = response.json()
        raw_text: str = body.get("response", "")
        return _parse_structured_output(raw_text)

    # ---- Internals -------------------------------------------------------------

    def _render_prompt(self, measurement: Dict[str, Any], kg_snapshot: Dict[str, Any]) -> str:
        valid_ids = sorted(
            {
                n["id"]
                for key in ("obligations", "definitions")
                for n in kg_snapshot.get(key, [])
                if isinstance(n, dict) and "id" in n
            }
        )
        return PROMPT_TEMPLATE.format(
            valid_node_ids=json.dumps(valid_ids, ensure_ascii=False),
            measurement_json=json.dumps(
                measurement, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
            kg_snapshot_json=json.dumps(
                kg_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        )

    def _discover_model_weight_hash(self) -> str:
        """Resolve the model weight hash from Ollama's ``/api/show`` digest.

        Falls back to ``sha256("ollama:" + model_name)`` if Ollama is not
        reachable or doesn't expose a digest. The fallback is a vendor
        commitment string — auditors should treat it as a weaker
        provenance signal than the actual digest.
        """
        url = f"{self._base_url}/api/show"
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                resp = client.post(url, json={"name": self._model_name})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Could not query Ollama /api/show for %s (%s); falling back to vendor commitment.",
                self._model_name,
                exc,
            )
            return _vendor_commitment(self._model_name)

        digest = _extract_digest(data)
        if digest is None:
            logger.warning(
                "Ollama /api/show for %s did not expose a digest; falling back to vendor commitment.",
                self._model_name,
            )
            return _vendor_commitment(self._model_name)
        return "sha256:" + digest.lower().removeprefix("sha256:")


# ---- Helpers ------------------------------------------------------------------


def _vendor_commitment(model_name: str) -> str:
    """sha256 over the ``ollama:<model_name>`` commitment string."""
    return "sha256:" + hashlib.sha256(f"ollama:{model_name}".encode()).hexdigest()


def _extract_digest(show_response: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of the model digest from /api/show.

    Ollama's response shape has shifted across versions; we look in the
    documented locations and fall back to None.
    """
    details = show_response.get("details") or {}
    for key in ("digest", "parent_model"):
        value = details.get(key)
        if isinstance(value, str) and value:
            return value
    direct = show_response.get("digest")
    if isinstance(direct, str) and direct:
        return direct
    return None


_REQUIRED_RESPONSE_KEYS = {"verdict", "reasoning", "kg_citations", "formalizable_assertions"}
_PERMITTED_VERDICTS = {"CLEAR", "FLAG", "NULL_UNMAPPED", "NULL_STALE", "DISCRETIONARY"}


def _parse_structured_output(raw_text: str) -> Dict[str, Any]:
    """Parse Ollama's structured-output payload; map failures to DISCRETIONARY.

    Per spec §5.2: malformed model output MUST NOT be guessed. We return a
    DISCRETIONARY envelope with an explanatory ``reasoning`` and an empty
    citation / assertion set so the verifier produces ``UNVERIFIABLE``.
    """
    try:
        obj = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return _discretionary_response(
            f"Backend output was not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}."
        )
    if not isinstance(obj, dict):
        return _discretionary_response("Backend output JSON was not an object at top level.")
    missing = _REQUIRED_RESPONSE_KEYS - set(obj.keys())
    if missing:
        return _discretionary_response(f"Backend output missing required keys: {sorted(missing)!r}.")
    if obj["verdict"] not in _PERMITTED_VERDICTS:
        return _discretionary_response(
            f"Backend verdict {obj['verdict']!r} is not in the five-verdict taxonomy."
        )
    return obj


def _discretionary_response(reason: str) -> Dict[str, Any]:
    return {
        "verdict": "DISCRETIONARY",
        "reasoning": reason,
        "kg_citations": [],
        "formalizable_assertions": [],
    }


__all__ = ["OllamaV3Backend"]
