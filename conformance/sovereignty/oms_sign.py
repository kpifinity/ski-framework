"""Sign a model directory as OpenSSF Model Signing (OMS v1.0, ``key`` method) does, for the rigs.

The conformance rigs need a signed model without installing the reference
``model-signing`` tool (and its Sigstore stack). This writes the same
format: a Sigstore bundle (``application/vnd.dev.sigstore.bundle.v0.3+json``)
holding a DSSE envelope of an in-toto ``Statement/v1`` with predicate
``https://model_signing/signature/v1.0``, signed with ECDSA P-256 over the
DSSE pre-authentication encoding. The runtime's verifier is pinned to the
reference tool separately, by a fixture it signed
(``reference-implementation/src/ski_model/v3/tests/data/oms``).
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

_PAYLOAD_TYPE = "application/vnd.in-toto+json"


def sign_model(
    model_dir: Path, key: ec.EllipticCurvePrivateKey, model_name: str = "model"
) -> dict[str, object]:
    """The OMS bundle for every file under ``model_dir``, sorted by path."""
    resources = [
        {
            "name": path.relative_to(model_dir).as_posix(),
            "algorithm": "sha256",
            "digest": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(p for p in model_dir.rglob("*") if p.is_file())
    ]
    root = hashlib.sha256(b"".join(bytes.fromhex(r["digest"]) for r in resources)).hexdigest()
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": model_name, "digest": {"sha256": root}}],
        "predicateType": "https://model_signing/signature/v1.0",
        "predicate": {
            "resources": resources,
            "serialization": {
                "method": "files",
                "hash_type": "sha256",
                "allow_symlinks": False,
                "ignore_paths": [],
            },
        },
    }
    payload = json.dumps(statement).encode("utf-8")
    kind = _PAYLOAD_TYPE.encode("utf-8")
    pae = b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)
    signature = key.sign(pae, ec.ECDSA(hashes.SHA256()))
    return {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {"publicKey": {"hint": ""}, "tlogEntries": []},
        "dsseEnvelope": {
            "payload": base64.b64encode(payload).decode("ascii"),
            "payloadType": _PAYLOAD_TYPE,
            "signatures": [{"sig": base64.b64encode(signature).decode("ascii"), "keyid": ""}],
        },
    }
