"""OpenSSF Model Signing at boot: a reference-tool signature verifies; any deviation refuses to start."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ski_model.model_signature import (
    ModelSignatureError,
    key_id,
    load_origins,
    verify_from_env,
    verify_model_signature,
)

FIXTURE = Path(__file__).parent / "data" / "oms"


@pytest.fixture
def model(tmp_path: Path) -> Path:
    """A writable copy of the reference-signed fixture (model/, model.sig, origin.pub)."""
    shutil.copytree(FIXTURE, tmp_path / "oms")
    return tmp_path / "oms"


def _origins(model: Path) -> list:  # type: ignore[type-arg]
    return load_origins((model / "origin.pub").read_bytes())


def test_reference_tool_signature_verifies(model: Path) -> None:
    result = verify_model_signature(
        model / "model.sig",
        model / "model",
        _origins(model),
        pinned_file=model / "model" / "model.safetensors",
    )
    assert result.model_name == "model" and result.files == 3
    assert result.signer_key_id == key_id(_origins(model)[0])
    assert result.attestation()["verified"] is True


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda m: (m / "model" / "model.safetensors").write_bytes(b"swapped weights"),
            "changed=['model.safetensors']",
        ),
        (lambda m: (m / "model" / "config.json").unlink(), "missing=['config.json']"),
        (lambda m: (m / "model" / "backdoor.py").write_text("x"), "extra=['backdoor.py']"),
        (lambda m: (m / "model" / "tokenizer" / "vocab.txt").write_text("other"), "tokenizer/vocab.txt"),
    ],
    ids=["swapped-weights", "missing-file", "extra-file", "nested-file"],
)
def test_a_model_that_differs_from_its_signature_is_refused(
    model: Path, mutate: object, message: str
) -> None:
    mutate(model)  # type: ignore[operator]
    with pytest.raises(ModelSignatureError, match=message.replace("[", r"\[").replace("]", r"\]")):
        verify_model_signature(model / "model.sig", model / "model", _origins(model))


def test_a_model_from_another_origin_is_refused(model: Path) -> None:
    stranger = ec.generate_private_key(ec.SECP256R1()).public_key()
    with pytest.raises(ModelSignatureError, match="permitted origin"):
        verify_model_signature(model / "model.sig", model / "model", [stranger])


def _edit_statement(model: Path, edit: object) -> None:
    bundle = json.loads((model / "model.sig").read_text())
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    edit(statement)  # type: ignore[operator]
    bundle["dsseEnvelope"]["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    (model / "model.sig").write_text(json.dumps(bundle))


def test_an_edited_statement_breaks_the_signature(model: Path) -> None:
    _edit_statement(model, lambda s: s["predicate"]["resources"].pop())
    with pytest.raises(ModelSignatureError, match="permitted origin"):
        verify_model_signature(model / "model.sig", model / "model", _origins(model))


def test_the_pinned_weights_must_be_signed(model: Path) -> None:
    outside = model / "unsigned.safetensors"
    outside.write_bytes(b"w")
    with pytest.raises(ModelSignatureError, match="not one of the signed model files"):
        verify_model_signature(model / "model.sig", model / "model", _origins(model), pinned_file=outside)


def test_origins_accept_ed25519_and_p384_and_reject_rsa() -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    def pem(key: object) -> bytes:
        return key.public_key().public_bytes(  # type: ignore[attr-defined, no-any-return]
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    bundle = pem(Ed25519PrivateKey.generate()) + pem(ec.generate_private_key(ec.SECP384R1()))
    assert len(load_origins(bundle)) == 2
    with pytest.raises(ModelSignatureError, match="only ECDSA"):
        load_origins(pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    with pytest.raises(ModelSignatureError, match="no public key"):
        load_origins(b"not pem")


def test_from_env(model: Path) -> None:
    assert verify_from_env({}) is None
    env = {
        "SKI_MODEL_SIGNATURE": str(model / "model.sig"),
        "SKI_MODEL_FILE_PATH": str(model / "model" / "model.safetensors"),
        "SKI_MODEL_ORIGINS": str(model / "origin.pub"),
    }
    result = verify_from_env(env)
    assert result is not None and result.files == 3
    with pytest.raises(ModelSignatureError, match="SKI_MODEL_ORIGINS"):
        verify_from_env({k: v for k, v in env.items() if k != "SKI_MODEL_ORIGINS"})
