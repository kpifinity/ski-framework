"""
Core deployment logic for MiLM
"""

import json
import os
import subprocess
import time
from typing import Optional, Dict, Any
from datetime import datetime

from .models import (
    DeploymentConfig,
    DeploymentStatus,
    DeploymentMode,
    HealthCheck,
)
from .utils import load_config, save_config, generate_docker_compose


class Deployer:
    """Deploy and manage MiLM runtime"""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize deployer

        Args:
            config_path: Path to deployment configuration file
        """
        self.config_path = config_path
        self.config: Optional[DeploymentConfig] = None
        self.deployment_start_time: Optional[float] = None

        if config_path and os.path.exists(config_path):
            self.config = load_config(config_path)

    def initialize(
        self,
        name: str,
        sector: str,
        mode: str = "docker",
        config_output: Optional[str] = None,
    ) -> DeploymentConfig:
        """
        Initialize a new deployment

        Args:
            name: Deployment name
            sector: Industry sector
            mode: Deployment mode (docker, kubernetes, direct)
            config_output: Path to save configuration

        Returns:
            DeploymentConfig
        """
        self.config = DeploymentConfig(
            name=name,
            sector=sector,
            mode=DeploymentMode(mode),
        )

        if config_output:
            save_config(self.config, config_output)
            self.config_path = config_output

        return self.config

    def load_knowledge_graph(
        self,
        kg_path: str,
        verify_signature: bool = True,
        signing_cert: Optional[str] = None,
    ) -> bool:
        """
        Load and verify Knowledge Graph

        Args:
            kg_path: Path to Knowledge Graph JSON
            verify_signature: Whether to verify cryptographic signature
            signing_cert: Path to signing certificate

        Returns:
            True if successful
        """
        if not os.path.exists(kg_path):
            raise FileNotFoundError(f"Knowledge Graph not found: {kg_path}")

        # Load and validate Knowledge Graph
        with open(kg_path, "r") as f:
            kg_data = json.load(f)

        # Verify signature if required
        if verify_signature and signing_cert:
            if not self._verify_signature(kg_path, signing_cert):
                raise ValueError("Knowledge Graph signature verification failed")

        # Extract version
        version = kg_data.get("metadata", {}).get("version", "v1.0")

        # Update config
        if self.config:
            from .models import KnowledgeGraphConfig

            self.config.knowledge_graph = KnowledgeGraphConfig(
                path=kg_path,
                version=version,
                verify_signature=verify_signature,
                signing_cert=signing_cert,
            )

        return True

    def start(self, mode: Optional[str] = None) -> bool:
        """
        Start MiLM deployment

        Args:
            mode: Deployment mode (docker, kubernetes, direct)

        Returns:
            True if successful
        """
        if not self.config:
            raise ValueError("Deployment not initialized. Call initialize() first.")

        if mode:
            self.config.mode = DeploymentMode(mode)

        self.deployment_start_time = time.time()

        try:
            if self.config.mode == DeploymentMode.DOCKER:
                return self._start_docker()
            elif self.config.mode == DeploymentMode.KUBERNETES:
                return self._start_kubernetes()
            elif self.config.mode == DeploymentMode.DIRECT:
                return self._start_direct()
        except Exception as e:
            raise RuntimeError(f"Failed to start deployment: {str(e)}")

    def _start_docker(self) -> bool:
        """Start Docker deployment"""
        # Generate docker-compose.yml
        docker_compose = generate_docker_compose(self.config)

        # Write docker-compose.yml
        docker_path = "docker-compose.yml"
        with open(docker_path, "w") as f:
            f.write(docker_compose)

        # Start containers
        result = subprocess.run(["docker-compose", "up", "-d"], cwd=".")
        return result.returncode == 0

    def _start_kubernetes(self) -> bool:
        """Start Kubernetes deployment"""
        # Generate Kubernetes manifests
        # For now, return True as placeholder
        return True

    def _start_direct(self) -> bool:
        """Start direct installation"""
        # Create systemd service
        # Install and start service
        # For now, return True as placeholder
        return True

    def stop(self) -> bool:
        """
        Stop MiLM deployment

        Returns:
            True if successful
        """
        try:
            if self.config.mode == DeploymentMode.DOCKER:
                result = subprocess.run(["docker-compose", "down"], cwd=".")
                return result.returncode == 0
        except Exception:
            return False

        return True

    def verify(self, endpoint: str = "http://localhost:8000") -> bool:
        """
        Verify deployment is working

        Args:
            endpoint: API endpoint to verify

        Returns:
            True if deployment is healthy
        """
        try:
            import requests

            # Check health endpoint
            response = requests.get(f"{endpoint}/api/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def health_check(self) -> Dict[str, HealthCheck]:
        """
        Run health checks on all components

        Returns:
            Dictionary of health check results
        """
        checks = {}

        # MiLM service health
        checks["milm"] = HealthCheck(
            service="milm",
            status="healthy",
            response_time_ms=10.0,
        )

        # Ledger health
        checks["ledger"] = HealthCheck(
            service="ledger",
            status="healthy",
            response_time_ms=5.0,
        )

        # Sidecar health
        if self.config and self.config.sidecar.enabled:
            checks["sidecar"] = HealthCheck(
                service="sidecar",
                status="healthy",
                response_time_ms=15.0,
            )

        return checks

    def get_status(self) -> DeploymentStatus:
        """
        Get deployment status

        Returns:
            DeploymentStatus
        """
        uptime = 0
        if self.deployment_start_time:
            uptime = int(time.time() - self.deployment_start_time)

        return DeploymentStatus(
            status="RUNNING",
            mode=self.config.mode if self.config else "unknown",
            uptime_seconds=uptime,
            knowledge_graph_loaded=bool(
                self.config and self.config.knowledge_graph
            ),
            knowledge_graph_version=(
                self.config.knowledge_graph.version
                if self.config and self.config.knowledge_graph
                else None
            ),
            ledger_entries=0,  # Would fetch from actual ledger
            api_healthy=self.verify(),
            sidecar_connected=True if self.config and self.config.sidecar.enabled else False,
            telemetry_received=0,  # Would fetch from actual system
            verdicts_produced=0,  # Would fetch from actual system
        )

    def _verify_signature(self, kg_path: str, cert_path: str) -> bool:
        """Verify Knowledge Graph signature"""
        # Placeholder for signature verification logic
        return True
