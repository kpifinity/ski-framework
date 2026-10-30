"""Ollama-v3 backend — local KG-grounded LLM inference.

Ollama is the reference local-weights backend because it satisfies the
**Sovereign** part of "Sovereign Knowledge Intelligence":

  * Weights live on the operator's hardware. The :attr:`model_weight_hash`
    field of :class:`ModelProvenance` is the SHA-256 of the weights blob
    named in Ollama's ``/api/show`` modelfile, checked against
    ``$SKI_MODEL_FILE_SHA256`` when the operator pins it (mismatch =>
    refuse to start; see :mod:`.model_hash`).
  * No data leaves the deployment perimeter. The HTTP call goes to a
    local-network Ollama instance.
  * Determinism: ``temperature=0``, fixed ``seed``, ``top_p=1.0``,
    ``top_k=1``, ``num_predict`` bounded. Same input → same output
    bit-for-bit (per Ollama's documented determinism guarantees).
  * Structured output: ``format`` carries the :data:`RESPONSE_GRAMMAR`
    JSON schema (schema-constrained decoding, Ollama >= 0.5.0; 0.3.x/0.4.x
    accept only the string ``"json"`` and reject the request). Malformed
    output is mapped to ``DISCRETIONARY`` rather than guessed at.

The backend renders the canonical prompt itself from the measurement +
KG snapshot (matching what :class:`V3Evaluator` records in the
transcript). Real production prompts may be richer (system messages,
few-shot examples) but the transcript records the framework-canonical
form, which is what an auditor replays.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from ..evaluator import PROMPT_TEMPLATE, PROMPT_TEMPLATE_ID, RESPONSE_GRAMMAR
from .model_hash import (
    EXPECTED_HASH_ENV,
    SOURCE_BACKEND_DIGEST,
    SOURCE_NAME_COMMITMENT,
    SOURCE_VERIFIED_BACKEND_DIGEST,
    ModelHashError,
    ModelHashResolution,
    RemoteModelError,
    check_pin,
    name_commitment,
    weights_digest_from_modelfile,
)

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
        expected_model_hash: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._seed = seed
        self._max_tokens = max_tokens
        self._prompt_template_hash = prompt_template_hash
        self._structured_grammar_hash = structured_grammar_hash
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(request_timeout_seconds))
        self._model_hash = self._resolve_model_hash(expected_model_hash)

    # ---- V3LLMBackend protocol -------------------------------------------------

    @property
    def model_weight_hash(self) -> str:
        return self._model_hash.model_weight_hash

    # ---- Provenance extras (read via getattr; not part of the protocol) --------

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def model_hash_verified(self) -> bool:
        return self._model_hash.verified

    @property
    def model_hash_source(self) -> str:
        return self._model_hash.source

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

    def _resolve_model_hash(self, expected: Optional[str]) -> ModelHashResolution:
        """Resolve ``model_weight_hash`` from the weights blob named by ``/api/show``.

        With ``expected`` (``$SKI_MODEL_FILE_SHA256``, normalised hex) set,
        anything short of a matching blob digest raises
        :class:`ModelHashError`: Ollama unreachable, no blob digest, or a
        different digest. Without it, the observed blob digest is recorded
        unverified, and the ``sha256("ollama:<name>")`` name commitment is
        used only when Ollama cannot be queried or exposes no blob.
        A remote model always raises :class:`RemoteModelError`.
        """
        url = f"{self._base_url}/api/show"
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                resp = client.post(url, json={"model": self._model_name})
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            if expected is not None:
                raise ModelHashError(
                    f"Could not query Ollama /api/show for {self._model_name!r} ({exc}), so "
                    f"{EXPECTED_HASH_ENV} cannot be verified. Refusing to start."
                ) from exc
            logger.warning(
                "Could not query Ollama /api/show for %s (%s). Recording a name commitment, "
                "which is NOT a weight hash (model_hash_verified=false).",
                self._model_name,
                exc,
            )
            return ModelHashResolution(
                name_commitment("ollama", self._model_name), False, SOURCE_NAME_COMMITMENT
            )

        show = data if isinstance(data, dict) else {}
        remote = show.get("remote_host") or show.get("remote_model")
        if remote:
            raise RemoteModelError(
                f"Ollama serves {self._model_name!r} from a remote host ({remote!r}). Inference "
                "would leave the sovereign boundary and there are no local weights to verify. "
                "Refusing to start: pull the model weights locally."
            )

        observed = weights_digest_from_modelfile(show.get("modelfile"))
        if expected is not None:
            if observed is None:
                raise ModelHashError(
                    f"Ollama /api/show for {self._model_name!r} names no content-addressed "
                    f"weights blob, so {EXPECTED_HASH_ENV} cannot be verified. Refusing to start."
                )
            check_pin(
                expected=expected,
                observed=observed,
                observed_from="the Ollama weights blob (/api/show modelfile)",
                model_name=self._model_name,
            )
            logger.info(
                "Model weights verified: %s blob sha256:%s matches %s.",
                self._model_name,
                observed,
                EXPECTED_HASH_ENV,
            )
            return ModelHashResolution("sha256:" + observed, True, SOURCE_VERIFIED_BACKEND_DIGEST)

        if observed is not None:
            logger.warning(
                "Model weights for %s are sha256:%s per Ollama, but no %s pin is set, so they "
                "are NOT verified (model_hash_verified=false). Pin the digest to verify it.",
                self._model_name,
                observed,
                EXPECTED_HASH_ENV,
            )
            return ModelHashResolution("sha256:" + observed, False, SOURCE_BACKEND_DIGEST)

        logger.warning(
            "Ollama /api/show for %s names no weights blob. Recording a name commitment, which "
            "is NOT a weight hash (model_hash_verified=false).",
            self._model_name,
        )
        return ModelHashResolution(name_commitment("ollama", self._model_name), False, SOURCE_NAME_COMMITMENT)


# ---- Helpers ------------------------------------------------------------------


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
