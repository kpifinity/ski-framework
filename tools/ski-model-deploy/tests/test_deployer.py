"""Tests for the ski-model-deploy deployer."""

import json
from pathlib import Path
from typing import Tuple

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ski_model_deploy import Deployer
from ski_model_deploy.deployer import UnsignedKGError
from ski_model_deploy.models import DeploymentConfig, DeploymentMode


class TestDeployer:
    def test_initialize_deployment(self) -> None:
        deployer = Deployer()
        config = deployer.initialize(name="test-system", sector="energy", mode="docker")
        assert config.name == "test-system"
        assert config.sector == "energy"
        assert config.mode == DeploymentMode.DOCKER

    def test_deployer_config_persistence(self) -> None:
        deployer = Deployer()
        deployer.initialize(name="test-system", sector="finance")
        assert deployer.config is not None
        assert deployer.config.name == "test-system"


class TestDeploymentConfig:
    def test_config_defaults_are_sovereign(self) -> None:
        config = DeploymentConfig(name="test", sector="energy")
        # Sovereign-by-default: local Ollama backend, temperature=0, mandatory TLS + API key.
        assert config.ski_model.backend == "ollama"
        assert config.ski_model.temperature == 0.0
        assert config.ski_model.model == "qwen2.5:7b-instruct"
        assert config.security.tls_enabled is True
        assert config.security.api_key_required is True
        assert config.monitoring.enabled is True
        assert config.ledger.backend == "postgresql"

    def test_config_sidecar_defaults_to_file_source(self) -> None:
        config = DeploymentConfig(name="test", sector="energy")
        assert config.sidecar.enabled is True
        # Default telemetry source is "file" — Kafka is opt-in via compose profile.
        assert config.sidecar.telemetry_source == "file"


def _write_signed_kg(tmp_path: Path, key: Ed25519PrivateKey) -> Tuple[Path, str]:
    metadata = {"version": "deploy-test-1"}
    rules = [{"id": "r1", "metric": "so2_ppm", "predicate": "must_not_exceed", "value": 100}]
    tags = {"emissions": "r1"}
    canonical = json.dumps(
        {"metadata": metadata, "rules": rules, "tag_registry": tags},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
    kg_path = tmp_path / "kg.json"
    kg_path.write_text(
        json.dumps(
            {
                "metadata": metadata,
                "rules": rules,
                "tag_registry": tags,
                "signature": {
                    "algorithm": "ed25519",
                    "public_key_pem": pem,
                    "value_hex": key.sign(canonical).hex(),
                },
            }
        )
    )
    return kg_path, pem


class TestLoadKnowledgeGraphTrustAnchors:
    """Framework v3.2.0: the deployer verifies against trust anchors like the runtime."""

    @pytest.fixture(autouse=True)
    def _no_env_trust(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_KG_TRUST_ANCHORS", raising=False)
        monkeypatch.delenv("SKI_KG_ALLOW_UNANCHORED", raising=False)

    def test_anchored_kg_is_registered_as_verified(self, tmp_path: Path) -> None:
        key = Ed25519PrivateKey.generate()
        kg_path, pem = _write_signed_kg(tmp_path, key)
        anchors = tmp_path / "anchors.pem"
        anchors.write_text(pem)
        deployer = Deployer()
        deployer.initialize(name="t", sector="energy")
        assert deployer.load_knowledge_graph(str(kg_path), trust_anchors=str(anchors))
        assert deployer.config is not None and deployer.config.knowledge_graph is not None
        assert deployer.config.knowledge_graph.signature_verified is True

    def test_kg_signed_by_non_anchor_is_refused(self, tmp_path: Path) -> None:
        kg_path, _ = _write_signed_kg(tmp_path, Ed25519PrivateKey.generate())
        other = Ed25519PrivateKey.generate().public_key()
        anchors = tmp_path / "anchors.pem"
        anchors.write_bytes(
            other.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )
        deployer = Deployer()
        deployer.initialize(name="t", sector="energy")
        with pytest.raises(UnsignedKGError, match="not a configured trust anchor"):
            deployer.load_knowledge_graph(str(kg_path), trust_anchors=str(anchors))

    def test_no_anchors_configured_is_refused(self, tmp_path: Path) -> None:
        kg_path, _ = _write_signed_kg(tmp_path, Ed25519PrivateKey.generate())
        deployer = Deployer()
        deployer.initialize(name="t", sector="energy")
        with pytest.raises(UnsignedKGError, match="No KG trust anchors configured"):
            deployer.load_knowledge_graph(str(kg_path))


class TestSignKnowledgeGraph:
    """`ski-model-deploy sign` produces a KG the runtime and `load-kg` accept."""

    @pytest.fixture(autouse=True)
    def _no_env_trust(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKI_KG_TRUST_ANCHORS", raising=False)
        monkeypatch.delenv("SKI_KG_ALLOW_UNANCHORED", raising=False)

    def test_signed_demo_graph_round_trips_through_load_kg(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from ski_model_deploy.cli import main

        key = Ed25519PrivateKey.generate()
        key_path = tmp_path / "kg.key"
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        anchors = tmp_path / "anchors.pem"
        anchors.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        demo = Path(__file__).resolve().parents[3] / "examples/energy/knowledge-graphs/kg-energy-v3-demo.json"
        signed = tmp_path / "signed.json"
        config = tmp_path / "deployment.yaml"
        runner = CliRunner()

        result = runner.invoke(main, ["sign", "--kg", str(demo), "--key", str(key_path), "-o", str(signed)])
        assert result.exit_code == 0, result.output
        assert runner.invoke(main, ["init", "-n", "t", "-s", "energy", "-o", str(config)]).exit_code == 0
        result = runner.invoke(
            main, ["load-kg", "-c", str(config), "-k", str(signed), "--trust-anchors", str(anchors)]
        )
        assert result.exit_code == 0, result.output
        assert "signature verified" in result.output

    def test_sign_refuses_a_non_ed25519_key(self, tmp_path: Path) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec
        from ski_model_deploy.deployer import sign_kg

        other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        with pytest.raises(ValueError, match="Ed25519"):
            sign_kg({"metadata": {}, "nodes": {}, "edges": []}, other)

    def test_deployer_finds_the_runtime_loader_without_help(self) -> None:
        # The deployer resolves reference-implementation/src itself (the CLI
        # has no pytest path setup); a wrong path left KnowledgeGraph = None.
        import subprocess
        import sys

        code = (
            "import ski_model_deploy.deployer as d; assert d.KnowledgeGraph is not None and d.signing_bytes"
        )
        subprocess.run([sys.executable, "-I", "-c", code], check=True)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
