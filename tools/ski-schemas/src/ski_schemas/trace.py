"""SKI verdicts as TRACE v0.2 Trust Records (Trust, Runtime Attestation, and Compliance Evidence).

TRACE (CoSAI WS4 / Linux Foundation, v0.2 Developer Preview,
``tag:agentrust-io.com,2026:trace-v0.2``) is a portable record of one AI run:
which model ran, where, under which policy, on which data class, which tools
it called, and where the record is anchored. A SKI verdict maps onto it:

=====================  ==========================================================
TRACE field            SKI source
=====================  ==========================================================
``subject``            ``ski:ledger:<tenant>:<sequence>`` (the ledger entry)
``model``              backend, ``model_id``, runtime version, ``model_weight_hash``
``runtime``            ``platform: "software-only"`` (no TEE measurement); image digest
``policy``             the signed KG: ``bundle_hash`` = ``kg_version_hash``,
                       ``enforcement_mode`` = ``enforce`` in strict sovereignty,
                       ``advisory`` otherwise; ``version`` = KG version
``data_class``         operator-declared (``SKI_DATA_CLASS``, default ``regulated-telemetry``)
``tool_transcript``    the signed LLM transcript: its hash, one model call, its ledger URI
``origin``             ``kind: "self"``: the runtime that produced the verdict
``build_provenance``   commit and image digest (and SLSA level when attested)
``appraisal``          the Symbolic Verifier: AGREED -> ``affirming``,
                       UNVERIFIABLE -> ``warning``, a contradiction or divergence ->
                       ``contraindicated``
``transparency``       the SCITT receipt for the entry (:mod:`ski_schemas.scitt`)
``cnf``                the runtime's Ed25519 key as an OKP JWK
=====================  ==========================================================

The record uses TRACE's embedded-signature profile: ``signature`` is the
base64url (no padding) Ed25519 signature over the RFC 8785 JCS bytes of the
record without ``signature``, made by the key in ``cnf``. A TRACE verifier
checks that binding first (TRACE §3.3 step 1); the hardware-root steps do
not apply to a ``software-only`` record, as TRACE v0.2 itself notes.
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Optional

from .canonical import canonicalize

__all__ = [
    "EAT_PROFILE",
    "appraisal_status",
    "okp_jwk",
    "sign_record",
    "trust_record",
    "verify_record",
]

EAT_PROFILE = "tag:agentrust-io.com,2026:trace-v0.2"

_APPRAISAL = {
    "AGREED": "affirming",
    "UNVERIFIABLE": "warning",
    "LLM_CONTRADICTION": "contraindicated",
    "NEURO_SYMBOLIC_DIVERGENCE": "contraindicated",
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if _b64url(data) != text:
        raise ValueError("signature is not canonical base64url")  # TRACE §3.2.2
    return data


def appraisal_status(verifier_status: Optional[str]) -> str:
    """The EAR appraisal status for a Symbolic Verifier outcome (``none`` when there was none)."""
    return _APPRAISAL.get(verifier_status or "", "none")


def okp_jwk(raw_public_key: bytes) -> dict[str, str]:
    """An Ed25519 public key as an RFC 8037 OKP JWK."""
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw_public_key)}


def trust_record(
    *,
    entry: dict[str, Any],
    provenance: dict[str, Any],
    verifier_status: Optional[str],
    transcript_hash: Optional[str],
    strict: bool,
    kg_version: Optional[str],
    data_class: str,
    image_digest: Optional[str],
    codebase_commit: Optional[str],
    receipt_uri: Optional[str],
    raw_public_key: bytes,
    issued_at: int,
) -> dict[str, Any]:
    """The unsigned TRACE v0.2 claims for one ledger entry (see the module table)."""
    tenant, seq = entry.get("tenant_id") or "default", entry["sequence_number"]
    entry_uri = f"ski:ledger:{tenant}:{seq}"
    return {
        "eat_profile": EAT_PROFILE,
        "iat": issued_at,
        "subject": entry_uri,
        "model": {
            "provider": provenance.get("backend"),
            "model_id": provenance.get("model_id"),
            "version": provenance.get("runtime_version"),
            "weights_digest": provenance.get("model_weight_hash"),
        },
        "runtime": {"platform": "software-only", "measurement": image_digest},
        "policy": {
            "bundle_hash": provenance.get("kg_version_hash"),
            "enforcement_mode": "enforce" if strict else "advisory",
            "version": kg_version,
        },
        "data_class": data_class,
        "tool_transcript": {
            "hash": transcript_hash,
            "call_count": 1 if transcript_hash else 0,
            "transcript_uri": f"{entry_uri}#transcript" if transcript_hash else None,
        },
        "origin": {"kind": "self", "producer": "ski-model"},
        "build_provenance": {"builder": "ski-framework", "digest": image_digest, "commit": codebase_commit},
        "appraisal": {
            "status": appraisal_status(verifier_status),
            "verifier": "ski-symbolic-verifier",
            "policy_ref": provenance.get("kg_version_hash"),
        },
        "transparency": {"receipt_uri": receipt_uri, "entry_hash": entry["entry_hash"]},
        "cnf": {"jwk": okp_jwk(raw_public_key)},
    }


def sign_record(record: dict[str, Any], sign_fn: Callable[[bytes], bytes]) -> dict[str, Any]:
    """``record`` with its embedded ``signature`` (TRACE §3.2.2)."""
    unsigned = {k: v for k, v in record.items() if k != "signature"}
    return {**unsigned, "signature": _b64url(sign_fn(canonicalize(unsigned)))}


def verify_record(record: dict[str, Any], verify_fn: Callable[[bytes, bytes, bytes], bool]) -> bool:
    """Check the embedded signature against ``cnf.jwk``: ``verify_fn(raw_public_key, signature, message)``."""
    try:
        jwk = record["cnf"]["jwk"]
        if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
            return False
        signature = _b64url_decode(str(record["signature"]))
        raw_key = _b64url_decode(str(jwk["x"]))
    except (KeyError, TypeError, ValueError):
        return False
    unsigned = {k: v for k, v in record.items() if k != "signature"}
    return verify_fn(raw_key, signature, canonicalize(unsigned))
