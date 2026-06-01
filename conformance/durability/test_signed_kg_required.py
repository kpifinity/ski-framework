"""SKI Framework v3.0 §3 — Signed KG is mandatory.

Durability of provenance begins with the KG itself. The SKI Model must
refuse to load an unsigned Knowledge Graph. The configuration knob
``KG_REQUIRE_SIGNATURE`` may default to ``true`` only; implementations
that default to ``false`` are non-conformant.

``ski-model-deploy`` must not expose any ``verify_signature=False``
flag — there is no escape hatch from signature verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.durability
def test_kg_loader_default_requires_signature(repo_root: Path) -> None:
    loader = (repo_root / "reference-implementation" / "src" / "ski_model" / "kg_loader.py").read_text()
    assert "require_signature" in loader, "kg_loader.py must accept a require_signature parameter."
    server = (repo_root / "reference-implementation" / "src" / "ski_model" / "server.py").read_text()
    assert 'KG_REQUIRE_SIGNATURE", "true"' in server, (
        "Server default for KG_REQUIRE_SIGNATURE must be 'true'."
    )


@pytest.mark.durability
def test_ski_model_deploy_has_no_verify_signature_flag(repo_root: Path) -> None:
    deployer = (
        repo_root / "tools" / "ski-model-deploy" / "src" / "ski_model_deploy" / "deployer.py"
    ).read_text()
    cli = (repo_root / "tools" / "ski-model-deploy" / "src" / "ski_model_deploy" / "cli.py").read_text()
    assert "verify_signature: bool" not in deployer, (
        "ski-model-deploy still exposes verify_signature as a parameter — "
        "signature verification must be mandatory (no escape hatch)."
    )
    assert "--verify-signature" not in cli, "CLI must not expose --verify-signature."
    assert "UnsignedKGError" in deployer
