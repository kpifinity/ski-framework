"""Model weight-hash pinning (``$SKI_MODEL_FILE_SHA256``) and its verification.

What each backend can actually prove about the weights it serves:

  * **Ollama** — ``POST /api/show`` has no ``digest`` field (and
    ``details.parent_model`` is a model *name*, not a hash), but its
    ``modelfile`` text names the weights blob in the first ``FROM`` line:
    ``FROM <models>/blobs/sha256-<hex>``. Ollama content-addresses blobs, so
    ``<hex>`` is the SHA-256 of the GGUF weights file; Ollama checks it when
    the model is pulled or created. ``GET /api/tags`` also exposes a
    ``digest``, but that is the digest of the model *manifest* (weights +
    template + params + licence), not of the weights file, so it is not
    used here. A model ``/api/show`` reports with a ``remote_host`` /
    ``remote_model`` is served by an upstream host: inference would leave
    the sovereign boundary, so the runtime refuses it outright
    (:class:`RemoteModelError`).
  * **vLLM** — the OpenAI-compatible API exposes no digest at all. The
    operator-supplied hash is all there is, unless the weights file is also
    mounted into the runtime (``$SKI_MODEL_FILE_PATH``) so the runtime can
    hash it at boot. A single file only (GGUF or one ``.safetensors``);
    sharded directories need a signed manifest (Phase 2, OpenSSF Model
    Signing).
  * **FakeLLM** has no weights; it is never "verified".

The rules every backend applies (spec §4.6; fail closed):

  * An expected hash that is malformed, that cannot be checked against
    anything the backend can report, or that differs from what the backend
    reports => refuse to start (:class:`ModelHashError`). The one
    exception is vLLM without a mounted weights file: there is nothing to
    compare against, so the operator's value is recorded as
    ``operator-asserted`` and ``model_hash_verified`` stays ``False``.
  * ``model_hash_verified`` is ``True`` only when an operator pin matched a
    digest the runtime obtained independently of that pin.
  * A ``sha256("<backend>:<model name>")`` name commitment is kept only as a
    last-resort placeholder when no pin is configured. It is labelled
    ``name-commitment``, logged as NOT a weight hash, and never verified.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Optional

EXPECTED_HASH_ENV: Final = "SKI_MODEL_FILE_SHA256"
MODEL_FILE_PATH_ENV: Final = "SKI_MODEL_FILE_PATH"

# ``model_hash_source`` values (reported in /api/health and the startup log).
SOURCE_VERIFIED_BACKEND_DIGEST: Final = "verified-backend-digest"
SOURCE_VERIFIED_FILE_DIGEST: Final = "verified-file-digest"
SOURCE_BACKEND_DIGEST: Final = "backend-digest"
SOURCE_FILE_DIGEST: Final = "file-digest"
SOURCE_OPERATOR_ASSERTED: Final = "operator-asserted"
SOURCE_NAME_COMMITMENT: Final = "name-commitment"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Ollama blob file name: ``sha256-<hex>`` (``sha256:<hex>`` on some older builds).
_BLOB_NAME = re.compile(r"^sha256[-:]([0-9a-f]{64})$")
_CHUNK = 1024 * 1024


class ModelHashError(RuntimeError):
    """The configured model hash cannot be honoured; the runtime must not start."""


class ModelHashMismatchError(ModelHashError):
    """The expected model hash differs from the digest the runtime observed."""


class RemoteModelError(ModelHashError):
    """The backend serves the model from a remote host (Ollama ``remote_host``).

    Inference would leave the sovereign boundary and there are no local
    weights to hash, so the runtime must not start.
    """


@dataclass(frozen=True)
class ModelHashResolution:
    """Outcome of resolving a backend's ``model_weight_hash`` at startup."""

    model_weight_hash: str  # "sha256:<64 hex>"
    verified: bool
    source: str


def normalize_sha256(value: str, *, what: str = EXPECTED_HASH_ENV) -> str:
    """Return ``value`` as 64 lowercase hex chars; raise :class:`ModelHashError` otherwise.

    Accepts an optional ``sha256:`` / ``sha256-`` prefix and surrounding
    whitespace (a pasted ``sha256sum`` line is NOT accepted; paste the hex).
    """
    candidate = value.strip().lower()
    for prefix in ("sha256:", "sha256-"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break
    if not _HEX64.match(candidate):
        raise ModelHashError(
            f"{what} must be a SHA-256 digest (64 hex characters, optional 'sha256:' prefix); "
            f"got {value!r}. Refusing to start rather than run with an unusable model pin."
        )
    return candidate


def expected_model_hash(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Read and normalise ``$SKI_MODEL_FILE_SHA256``; ``None`` when unset or empty."""
    source = os.environ if env is None else env
    raw = source.get(EXPECTED_HASH_ENV, "")
    if not raw.strip():
        return None
    return normalize_sha256(raw)


def sha256_file(path: Path) -> str:
    """Stream ``path`` through SHA-256 and return the hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weights_digest_from_modelfile(modelfile: object) -> Optional[str]:
    """Return the weights-blob SHA-256 (hex) named by an Ollama ``/api/show`` modelfile.

    Only the first non-comment ``FROM`` line is considered: Ollama renders
    the model weights layer first (adapters, drafts and projectors follow).
    Returns ``None`` when that line does not name a content-addressed blob,
    for example an MLX model (``FROM <name>``) or a remote model.
    """
    if not isinstance(modelfile, str):
        return None
    for raw_line in modelfile.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, arg = line.partition(" ")
        if keyword.upper() != "FROM":
            continue
        basename = re.split(r"[\\/]", arg.strip())[-1].lower()
        match = _BLOB_NAME.match(basename)
        return match.group(1) if match else None
    return None


def name_commitment(backend: str, model_name: str) -> str:
    """``sha256("<backend>:<model_name>")`` — a placeholder, NOT a weight hash."""
    return "sha256:" + hashlib.sha256(f"{backend}:{model_name}".encode()).hexdigest()


def check_pin(*, expected: str, observed: str, observed_from: str, model_name: str) -> None:
    """Raise :class:`ModelHashMismatchError` unless ``observed == expected`` (both hex)."""
    if observed != expected:
        raise ModelHashMismatchError(
            f"Model weight hash mismatch for {model_name!r}: {EXPECTED_HASH_ENV} pins "
            f"sha256:{expected} but {observed_from} reports sha256:{observed}. "
            "Refusing to start: the served weights are not the pinned weights."
        )


__all__ = [
    "EXPECTED_HASH_ENV",
    "MODEL_FILE_PATH_ENV",
    "SOURCE_BACKEND_DIGEST",
    "SOURCE_FILE_DIGEST",
    "SOURCE_NAME_COMMITMENT",
    "SOURCE_OPERATOR_ASSERTED",
    "SOURCE_VERIFIED_BACKEND_DIGEST",
    "SOURCE_VERIFIED_FILE_DIGEST",
    "ModelHashError",
    "ModelHashMismatchError",
    "ModelHashResolution",
    "RemoteModelError",
    "check_pin",
    "expected_model_hash",
    "name_commitment",
    "normalize_sha256",
    "sha256_file",
    "weights_digest_from_modelfile",
]
