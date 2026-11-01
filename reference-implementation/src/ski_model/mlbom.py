"""A CycloneDX 1.6 ML-BOM of what this runtime is serving: the model, the KG, the runtime.

``GET /api/mlbom`` returns it. The model is a ``machine-learning-model``
component with its weight digest (and whether the runtime verified it, and
the OpenSSF Model Signing signer when one is configured); the signed
Knowledge Graph is a ``data`` component with its version hash; the runtime
image is the BOM's subject. CycloneDX is the format operators already feed
SBOM tooling and regulators already accept, so the model supply chain lands
in the same pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ski_schemas.canonical import sha256_canonical

# serialNumber is a UUIDv5 of the BOM's content, so the same deployment always has the same one.
_NAMESPACE = uuid.UUID("6f0c9a2e-6c55-4f0b-9f7a-5000a0b00001")


def _sha256(prefixed: Optional[str]) -> list[dict[str, str]]:
    if not prefixed or not str(prefixed).startswith("sha256:"):
        return []
    return [{"alg": "SHA-256", "content": str(prefixed).removeprefix("sha256:")}]


def _properties(values: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": f"ski:{k}", "value": str(v).lower() if isinstance(v, bool) else str(v)}
        for k, v in values.items()
        if v is not None
    ]


def ml_bom(
    *,
    runtime_version: str,
    image_digest: Optional[str],
    codebase_commit: Optional[str],
    backend: dict[str, Any],
    model_signature: Optional[dict[str, Any]],
    kg: Optional[dict[str, Any]],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """The CycloneDX 1.6 JSON document (``backend`` is the runtime's backend provenance)."""
    model: dict[str, Any] = {
        "type": "machine-learning-model",
        "bom-ref": "model",
        "name": str(backend.get("model_id") or "unknown"),
        "hashes": _sha256(backend.get("model_weight_hash")),
        "properties": _properties(
            {
                "backend": backend.get("backend"),
                "model_hash_verified": backend.get("model_hash_verified"),
                "model_hash_source": backend.get("model_hash_source"),
                "model_signature_signer": (model_signature or {}).get("signer_key_id"),
                "model_signature_root_digest": (model_signature or {}).get("root_digest"),
            }
        ),
        "modelCard": {
            "modelParameters": {"task": "text-generation"},
            "considerations": {
                "useCases": ["Regulatory compliance evaluation, checked by the SKI Symbolic Verifier"],
            },
        },
    }
    components = [model]
    depends = ["model"]
    if kg is not None:
        components.append(
            {
                "type": "data",
                "bom-ref": "knowledge-graph",
                "name": str(kg.get("name") or "knowledge-graph"),
                "version": str(kg.get("version") or ""),
                "hashes": _sha256(kg.get("kg_version_hash")),
                "properties": _properties(
                    {"kg_trust": kg.get("kg_trust"), "kg_signer_key_id": kg.get("kg_signer_key_id")}
                ),
                "data": [{"type": "definition", "name": "SKI Knowledge Graph (spec §3)"}],
            }
        )
        depends.append("knowledge-graph")
    runtime: dict[str, Any] = {
        "type": "application",
        "bom-ref": "ski-model",
        "name": "ski-model",
        "version": runtime_version,
        "hashes": _sha256(image_digest),
        "properties": _properties({"codebase_commit": codebase_commit}),
    }
    body: dict[str, Any] = {"runtime": runtime, "components": components}
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(_NAMESPACE, sha256_canonical(body))}",
        "version": 1,
        "metadata": {
            "timestamp": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": runtime,
        },
        "components": components,
        "dependencies": [{"ref": "ski-model", "dependsOn": depends}, *({"ref": d} for d in depends)],
    }
