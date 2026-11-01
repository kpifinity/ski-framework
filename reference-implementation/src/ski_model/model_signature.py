"""OpenSSF Model Signing (OMS) verification at boot, against an allowlist of model origins.

A weight-hash pin proves the served file is the one the operator pinned; an
OMS signature proves who produced the model. ``SKI_MODEL_SIGNATURE`` names
an OMS signature file (``model_signing sign key ...``) for the model directory
``SKI_MODEL_DIR`` (default: the directory of ``SKI_MODEL_FILE_PATH``), and
``SKI_MODEL_ORIGINS`` a PEM bundle of the public keys whose models this
deployment accepts. With a signature configured the runtime refuses to start
unless:

* the file is a Sigstore bundle (``application/vnd.dev.sigstore.bundle...``)
  holding a DSSE envelope of an in-toto ``Statement/v1`` with predicate
  ``https://model_signing/signature/v1.0``;
* the DSSE signature (over the DSSE pre-authentication encoding) verifies
  with one of the origin keys: ECDSA P-256/P-384 or Ed25519. This is the OMS
  ``key`` method, which works offline; certificate chains and Sigstore's
  public log are out of scope for an air-gapped boot;
* the subject digest is the SHA-256 of the listed resource digests, in order;
* the model directory holds exactly the listed files (``method: files``,
  SHA-256, ``ignore_paths`` honoured, no symlinks unless allowed), each with
  its listed digest;
* the pinned weights file, when ``SKI_MODEL_FILE_PATH`` is set, is one of them,
  so the signature covers the hash the runtime already verifies.

The verified signer and model are attested at ``/api/sovereignty``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.x509 import load_pem_x509_certificates

SIGNATURE_ENV = "SKI_MODEL_SIGNATURE"
MODEL_DIR_ENV = "SKI_MODEL_DIR"
ORIGINS_ENV = "SKI_MODEL_ORIGINS"

PREDICATE_TYPE = "https://model_signing/signature/v1.0"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"

OriginKey = Union[ec.EllipticCurvePublicKey, Ed25519PublicKey]


class ModelSignatureError(RuntimeError):
    """The model's OMS signature is missing, invalid, or not from a permitted origin."""


@dataclass(frozen=True)
class ModelSignature:
    model_name: str
    root_digest: str
    signer_key_id: str
    files: int

    def attestation(self) -> dict[str, Any]:
        return {
            "format": "openssf-model-signing/v1.0",
            "verified": True,
            "model_name": self.model_name,
            "root_digest": "sha256:" + self.root_digest,
            "signer_key_id": self.signer_key_id,
            "files": self.files,
        }


def key_id(key: OriginKey) -> str:
    """``sha256:`` + hex SHA-256 of the key's DER SubjectPublicKeyInfo."""
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return "sha256:" + hashlib.sha256(der).hexdigest()


_PEM_BLOCK = re.compile(rb"-----BEGIN ([A-Z0-9 ]+)-----.*?-----END \1-----", re.DOTALL)


def load_origins(pem: bytes) -> list[OriginKey]:
    """Every public key (or certificate's key) in a PEM bundle; ECDSA P-256/P-384 or Ed25519 only."""
    keys: list[OriginKey] = []
    for match in _PEM_BLOCK.finditer(pem):
        block = match.group(0)
        candidates: list[Any]
        try:
            if match.group(1) == b"CERTIFICATE":
                candidates = [c.public_key() for c in load_pem_x509_certificates(block)]
            else:
                candidates = [serialization.load_pem_public_key(block)]
        except ValueError as exc:
            raise ModelSignatureError(f"{ORIGINS_ENV} holds an unreadable PEM block: {exc}") from exc
        for key in candidates:
            if isinstance(key, Ed25519PublicKey) or (
                isinstance(key, ec.EllipticCurvePublicKey)
                and isinstance(key.curve, (ec.SECP256R1, ec.SECP384R1))
            ):
                keys.append(key)
            else:
                raise ModelSignatureError(
                    f"{ORIGINS_ENV}: only ECDSA P-256/P-384 and Ed25519 keys are supported."
                )
    if not keys:
        raise ModelSignatureError(f"{ORIGINS_ENV} holds no public key.")
    return keys


def _pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE v1 pre-authentication encoding."""
    kind = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)


def _verifies(key: OriginKey, signature: bytes, message: bytes) -> bool:
    try:
        if isinstance(key, Ed25519PublicKey):
            key.verify(signature, message)
        else:
            digest = hashes.SHA384() if isinstance(key.curve, ec.SECP384R1) else hashes.SHA256()
            key.verify(signature, message, ec.ECDSA(digest))
    except InvalidSignature:
        return False
    return True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ignored(relative: str, ignore_paths: list[str]) -> bool:
    return any(relative == p or relative.startswith(p.rstrip("/") + "/") for p in ignore_paths)


def _model_files(
    model_dir: Path, *, ignore_paths: list[str], allow_symlinks: bool, exclude: set[Path]
) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(model_dir.rglob("*")):
        relative = path.relative_to(model_dir).as_posix()
        if _ignored(relative, ignore_paths) or path.resolve() in exclude:
            continue
        if path.is_symlink() and not allow_symlinks:
            raise ModelSignatureError(f"{relative} is a symlink and the signature does not allow symlinks.")
        if path.is_file():
            files[relative] = _sha256_file(path)
    return files


def verify_model_signature(
    signature_path: Path, model_dir: Path, origins: list[OriginKey], *, pinned_file: Optional[Path] = None
) -> ModelSignature:
    """Verify an OMS ``key``-method signature for ``model_dir``; raise :class:`ModelSignatureError` otherwise."""
    try:
        bundle = json.loads(signature_path.read_text(encoding="utf-8"))
        envelope = bundle["dsseEnvelope"]
        payload = base64.b64decode(envelope["payload"], validate=True)
        signatures = [base64.b64decode(s["sig"], validate=True) for s in envelope["signatures"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelSignatureError(f"{signature_path} is not an OMS signature bundle: {exc!r}") from exc
    if not str(bundle.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle"):
        raise ModelSignatureError(f"{signature_path} is not a Sigstore bundle.")
    if envelope.get("payloadType") != PAYLOAD_TYPE:
        raise ModelSignatureError(f"DSSE payloadType is {envelope.get('payloadType')!r}, not {PAYLOAD_TYPE}.")

    message = _pae(PAYLOAD_TYPE, payload)
    signer = next((k for k in origins for sig in signatures if _verifies(k, sig, message)), None)
    if signer is None:
        raise ModelSignatureError(
            f"The model signature in {signature_path} does not verify with any permitted origin key ({ORIGINS_ENV})."
        )

    statement = json.loads(payload)
    if statement.get("_type") != STATEMENT_TYPE or statement.get("predicateType") != PREDICATE_TYPE:
        raise ModelSignatureError(
            f"Not an OMS v1.0 statement (predicateType {statement.get('predicateType')!r})."
        )
    subjects = statement.get("subject") or []
    predicate = statement.get("predicate") or {}
    resources = predicate.get("resources") or []
    serialization_info = predicate.get("serialization") or {}
    if len(subjects) != 1 or not resources:
        raise ModelSignatureError("An OMS statement names exactly one model and lists its resources.")
    if serialization_info.get("method") != "files" or serialization_info.get("hash_type") != "sha256":
        raise ModelSignatureError(
            f"Unsupported OMS serialization {serialization_info!r}: only method=files with sha256."
        )
    if any(r.get("algorithm") != "sha256" for r in resources):
        raise ModelSignatureError("Every OMS resource must use sha256.")
    root = hashlib.sha256(b"".join(bytes.fromhex(str(r["digest"])) for r in resources)).hexdigest()
    if root != (subjects[0].get("digest") or {}).get("sha256"):
        raise ModelSignatureError(
            "The OMS subject digest does not match its resources (inconsistent manifest)."
        )

    signed = {str(r["name"]): str(r["digest"]) for r in resources}
    actual = _model_files(
        model_dir,
        ignore_paths=[str(p) for p in serialization_info.get("ignore_paths") or []],
        allow_symlinks=bool(serialization_info.get("allow_symlinks")),
        exclude={signature_path.resolve()},
    )
    if actual != signed:
        missing = sorted(set(signed) - set(actual))
        extra = sorted(set(actual) - set(signed))
        changed = sorted(n for n in set(signed) & set(actual) if signed[n] != actual[n])
        raise ModelSignatureError(
            f"{model_dir} does not match its signature: missing={missing} extra={extra} changed={changed}."
        )
    if pinned_file is not None:
        pinned, root_dir = pinned_file.resolve(), model_dir.resolve()
        if not pinned.is_relative_to(root_dir) or pinned.relative_to(root_dir).as_posix() not in signed:
            raise ModelSignatureError(
                f"The pinned weights file {pinned_file} is not one of the signed model files."
            )
    return ModelSignature(
        model_name=str(subjects[0].get("name")),
        root_digest=root,
        signer_key_id=key_id(signer),
        files=len(signed),
    )


def verify_from_env(env: Mapping[str, str]) -> Optional[ModelSignature]:
    """Verify the configured signature; ``None`` when ``SKI_MODEL_SIGNATURE`` is not set."""
    signature = env.get(SIGNATURE_ENV, "").strip()
    if not signature:
        return None
    pinned = env.get("SKI_MODEL_FILE_PATH", "").strip()
    model_dir = env.get(MODEL_DIR_ENV, "").strip() or (str(Path(pinned).parent) if pinned else "")
    origins = env.get(ORIGINS_ENV, "").strip()
    if not model_dir or not origins:
        raise ModelSignatureError(
            f"{SIGNATURE_ENV} is set: also set {MODEL_DIR_ENV} (or SKI_MODEL_FILE_PATH) and {ORIGINS_ENV}."
        )
    try:
        keys = load_origins(Path(origins).read_bytes())
    except OSError as exc:
        raise ModelSignatureError(f"{ORIGINS_ENV}={origins!r} cannot be read: {exc}") from exc
    return verify_model_signature(
        Path(signature), Path(model_dir), keys, pinned_file=Path(pinned) if pinned else None
    )


__all__ = [
    "ModelSignature",
    "ModelSignatureError",
    "key_id",
    "load_origins",
    "verify_from_env",
    "verify_model_signature",
]
