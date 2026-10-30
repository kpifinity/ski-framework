"""vLLM-v3 backend — production-grade local inference over the OpenAI API.

vLLM is the production path for GPU deployments: continuous batching,
guided decoding enforced *in the decoder* (token masking via
xgrammar/outlines), and an OpenAI-compatible server that stays inside
the sovereign boundary exactly like Ollama does. The sovereignty
analysis is identical — the HTTP call goes to a local-network vLLM
instance; weights live on the operator's hardware.

Differences from the Ollama backend, stated honestly:

  * **Structured output** uses vLLM's ``guided_json`` extension, which
    masks logits so the decoder *cannot* emit tokens violating
    :data:`RESPONSE_GRAMMAR` — stronger than post-hoc validation.
  * **Model weight hash**: vLLM does not expose a weights digest over
    the API. The operator SHOULD set ``$SKI_MODEL_FILE_SHA256`` (the
    digest of the served weights). If the weights file is also mounted
    into the runtime (``$SKI_MODEL_FILE_PATH``) it is hashed at boot and
    a mismatch refuses to start (``model_hash_verified=true`` on a
    match); otherwise the pin is recorded as operator-asserted with
    ``model_hash_verified=false``. With neither, a name commitment is
    recorded, labelled as NOT a weight hash. See :mod:`.model_hash`.
  * **Determinism**: ``temperature=0`` and a fixed ``seed`` are sent
    per request. vLLM's batching means bit-determinism is not
    guaranteed across load patterns; the framework's audit story rests
    on verifiable provenance, not bit-identical decoding (spec A2).

Malformed output is mapped to ``DISCRETIONARY`` per spec §5.2 — the
same degradation contract as every other backend; the shared parser
lives in :mod:`.ollama`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..evaluator import PROMPT_TEMPLATE, PROMPT_TEMPLATE_ID, RESPONSE_GRAMMAR
from .model_hash import (
    MODEL_FILE_PATH_ENV,
    SOURCE_FILE_DIGEST,
    SOURCE_NAME_COMMITMENT,
    SOURCE_OPERATOR_ASSERTED,
    SOURCE_VERIFIED_FILE_DIGEST,
    ModelHashError,
    ModelHashResolution,
    check_pin,
    name_commitment,
    normalize_sha256,
    sha256_file,
)
from .ollama import _discretionary_response, _parse_structured_output

logger = logging.getLogger(__name__)


class VLLMV3Backend:
    """Calls a local vLLM OpenAI-compatible server; conforms to ``V3LLMBackend``."""

    name = "vllm-v3"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        seed: int,
        max_tokens: int,
        prompt_template_hash: str,
        structured_grammar_hash: str,
        model_file_sha256: Optional[str] = None,
        model_file_path: Optional[str] = None,
        request_timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._seed = seed
        self._max_tokens = max_tokens
        self._prompt_template_hash = prompt_template_hash
        self._structured_grammar_hash = structured_grammar_hash
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(request_timeout_seconds))
        self._model_hash = self._resolve_model_weight_hash(model_file_sha256, model_file_path)

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
        """Render the canonical prompt and call ``/v1/chat/completions``.

        ``guided_json`` makes the response schema a *decoding constraint*,
        not a request. Malformed output (transport errors, empty choices,
        schema escapes on older vLLM versions) degrades to DISCRETIONARY.
        """
        prompt = self._render_prompt(measurement, kg_snapshot)
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "seed": seed,
            "max_tokens": self._max_tokens,
            "top_p": 1.0,
            "stream": False,
            # vLLM structured-output extension: decoder-level token
            # masking against the framework grammar.
            "guided_json": RESPONSE_GRAMMAR,
        }
        try:
            response = await self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("vLLM request failed: %r", exc)
            return _discretionary_response(f"vLLM backend transport error: {exc.__class__.__name__}: {exc}")

        body = response.json()
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return _discretionary_response("vLLM response contained no choices.")
        message = choices[0].get("message") or {}
        raw_text = message.get("content") or ""
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

    def _resolve_model_weight_hash(
        self, model_file_sha256: Optional[str], model_file_path: Optional[str]
    ) -> ModelHashResolution:
        """Strongest available provenance anchor for the served weights.

          1. Pin + mounted weights file: hash the file; a mismatch raises
             :class:`ModelHashError` (refuse to start), a match is verified.
          2. Pin only: vLLM exposes no digest, so the pin is recorded as
             ``operator-asserted`` with ``model_hash_verified=false``.
          3. File only: its digest is recorded, unverified (nothing to
             compare it with).
          4. Neither: ``sha256("vllm:" + model_name)`` name commitment,
             labelled as NOT a weight hash.

        ``/v1/models`` is consulted only to warn when the configured model
        is not the one being served.
        """
        served = self._list_served_models()
        if served is not None and self._model_name not in served:
            logger.warning(
                "vLLM at %s is not serving %r (served: %r). Provenance will record the "
                "configured name; verify the deployment.",
                self._base_url,
                self._model_name,
                served,
            )
        expected = normalize_sha256(model_file_sha256) if model_file_sha256 else None
        observed: Optional[str] = None
        if model_file_path:
            path = Path(model_file_path)
            try:
                observed = sha256_file(path)
            except OSError as exc:
                raise ModelHashError(
                    f"{MODEL_FILE_PATH_ENV}={model_file_path!r} cannot be read ({exc}). "
                    "Refusing to start rather than record unverifiable weights."
                ) from exc
        if expected is not None and observed is not None:
            check_pin(
                expected=expected,
                observed=observed,
                observed_from=f"the weights file {model_file_path}",
                model_name=self._model_name,
            )
            logger.info("Model weights verified: %s matches the pinned digest.", model_file_path)
            return ModelHashResolution("sha256:" + expected, True, SOURCE_VERIFIED_FILE_DIGEST)
        if expected is not None:
            logger.warning(
                "vLLM exposes no weights digest and %s is not set, so the pinned digest for %s "
                "is recorded as operator-asserted (model_hash_verified=false).",
                MODEL_FILE_PATH_ENV,
                self._model_name,
            )
            return ModelHashResolution("sha256:" + expected, False, SOURCE_OPERATOR_ASSERTED)
        if observed is not None:
            logger.warning(
                "Weights file %s hashes to sha256:%s, but no pin is set to verify it against "
                "(model_hash_verified=false).",
                model_file_path,
                observed,
            )
            return ModelHashResolution("sha256:" + observed, False, SOURCE_FILE_DIGEST)
        logger.warning(
            "No weights digest for vLLM model %s: recording a name commitment, which is NOT a "
            "weight hash (model_hash_verified=false). Set SKI_MODEL_FILE_SHA256.",
            self._model_name,
        )
        return ModelHashResolution(name_commitment("vllm", self._model_name), False, SOURCE_NAME_COMMITMENT)

    def _list_served_models(self) -> Optional[list[str]]:
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                resp = client.get(f"{self._base_url}/v1/models")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Could not query vLLM /v1/models (%s); skipping served-model check.", exc)
            return None
        models = data.get("data") or []
        return [m.get("id", "") for m in models if isinstance(m, dict)]


__all__ = ["VLLMV3Backend"]
