"""Tests for the ski-model-deploy deployer."""

import pytest

from ski_model_deploy import Deployer
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


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
