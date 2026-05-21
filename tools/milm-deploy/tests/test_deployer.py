"""
Tests for MiLM Deployer
"""

import pytest
from milm_deploy import Deployer
from milm_deploy.models import DeploymentConfig, DeploymentMode


class TestDeployer:
    """Test deployer functionality"""

    def test_initialize_deployment(self):
        """Should initialize a new deployment"""
        deployer = Deployer()
        config = deployer.initialize(
            name="test-system",
            sector="energy",
            mode="docker",
        )

        assert config.name == "test-system"
        assert config.sector == "energy"
        assert config.mode == DeploymentMode.DOCKER

    def test_deployer_config_persistence(self):
        """Configuration should persist when initialized"""
        deployer = Deployer()
        config = deployer.initialize(
            name="test-system",
            sector="finance",
        )

        assert deployer.config is not None
        assert deployer.config.name == "test-system"


class TestDeploymentConfig:
    """Test deployment configuration"""

    def test_config_defaults(self):
        """Configuration should have sensible defaults"""
        config = DeploymentConfig(
            name="test",
            sector="energy",
        )

        assert config.milm.temperature == 0.0
        assert config.milm.model == "claude-opus-4-6"
        assert config.monitoring.enabled is True
        assert config.ledger.backend == "sqlite"

    def test_config_with_sidecar(self):
        """Configuration should support sidecar settings"""
        config = DeploymentConfig(
            name="test",
            sector="energy",
        )

        assert config.sidecar.enabled is True
        assert config.sidecar.telemetry_source == "kafka"


if __name__ == "__main__":
    pytest.main([__file__])
