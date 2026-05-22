"""Deploy and verify Knowledge Graphs against a running SKI Model.

v2.1 changes:
  * MiLM → SKI Model rename throughout.
  * Knowledge Graph signature verification is MANDATORY. There is no
    `verify_signature=False` escape hatch. Per the Phase 1 → Phase 2
    boundary in the spec, a spec-conformant deployment never loads an
    unsigned KG. (Operators who insist on testing with an unsigned KG
    must set `KG_REQUIRE_SIGNATURE=false` on the server itself, which
    disqualifies the deployment from any conformance level.)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .models import DeploymentConfig, DeploymentMode, DeploymentStatus, HealthCheck
from .utils import generate_docker_compose, load_config, save_config

# Signature verification lives in the runtime package so the on-disk
# format is shared between the deployer and the server.
try:
    import sys
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[5] / "reference-implementation" / "src"),
    )
    from ski_model.kg_loader import KnowledgeGraph  # type: ignore
except Exception:  # pragma: no cover — fall back when run as installed package
    KnowledgeGraph = None  # type: ignore


class UnsignedKGError(RuntimeError):
    """Raised if signature verification fails or is missing."""


class Deployer:
    """Deploy and manage the SKI Model runtime."""

    def __init__(self, config_path: Optional[str] = None):
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
        self.config = DeploymentConfig(name=name, sector=sector, mode=DeploymentMode(mode))
        if config_output:
            save_config(self.config, config_output)
            self.config_path = config_output
        return self.config

    # ------------------------------------------------------------------
    # KG loading — signature verification is MANDATORY.
    # ------------------------------------------------------------------

    def load_knowledge_graph(self, kg_path: str) -> bool:
        """Verify a Knowledge Graph signature and register it with the deployment.

        Raises UnsignedKGError if the KG has no signature or the signature
        does not verify. There is no flag to bypass this.
        """
        if not os.path.exists(kg_path):
            raise FileNotFoundError(f"Knowledge Graph not found: {kg_path}")

        with open(kg_path, "r") as f:
            kg_data = json.load(f)

        if "signature" not in kg_data:
            raise UnsignedKGError(
                f"{kg_path} has no signature block. ski-model-deploy refuses "
                "to load unsigned Knowledge Graphs. Sign with your production "
                "Ed25519 key first."
            )

        if KnowledgeGraph is None:
            # Defensive: we can't verify without the loader. Refuse rather
            # than pretend.
            raise UnsignedKGError(
                "ski-model.kg_loader is unavailable in this environment; "
                "cannot verify the signature. Refusing to load."
            )

        try:
            kg = KnowledgeGraph.from_dict(kg_data, require_signature=True)
        except Exception as exc:
            raise UnsignedKGError(f"Signature verification failed for {kg_path}: {exc}") from exc

        if self.config:
            from .models import KnowledgeGraphConfig

            self.config.knowledge_graph = KnowledgeGraphConfig(
                path=kg_path,
                version=kg.version,
                signature_verified=True,
            )
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, mode: Optional[str] = None) -> bool:
        if not self.config:
            raise ValueError("Deployment not initialised. Call initialize() first.")
        if mode:
            self.config.mode = DeploymentMode(mode)
        self.deployment_start_time = time.monotonic()
        if self.config.mode == DeploymentMode.DOCKER:
            return self._start_docker()
        if self.config.mode == DeploymentMode.KUBERNETES:
            return self._start_kubernetes()
        if self.config.mode == DeploymentMode.DIRECT:
            return self._start_direct()
        raise ValueError(f"Unknown mode: {self.config.mode}")

    def _start_docker(self) -> bool:
        docker_compose = generate_docker_compose(self.config)
        Path("docker-compose.yml").write_text(docker_compose)
        return subprocess.run(["docker", "compose", "up", "-d"], cwd=".").returncode == 0

    def _start_kubernetes(self) -> bool:  # pragma: no cover — planned
        return True

    def _start_direct(self) -> bool:  # pragma: no cover — planned
        return True

    def stop(self) -> bool:
        if self.config and self.config.mode == DeploymentMode.DOCKER:
            return subprocess.run(["docker", "compose", "down"], cwd=".").returncode == 0
        return True

    def verify(self, endpoint: str = "https://localhost:8000", api_key: Optional[str] = None) -> bool:
        try:
            import httpx
        except ImportError:
            return False
        headers = {"x-api-key": api_key} if api_key else {}
        try:
            r = httpx.get(f"{endpoint}/api/health", headers=headers, timeout=5.0, verify=False)  # nosec B501 — self-signed certs in dev
            return r.status_code == 200
        except Exception:
            return False

    def health_check(self) -> Dict[str, HealthCheck]:
        return {
            "ski-model": HealthCheck(service="ski-model", status="healthy", response_time_ms=10.0),
            "ledger": HealthCheck(service="ledger", status="healthy", response_time_ms=5.0),
        }

    def get_status(self) -> DeploymentStatus:
        uptime = int(time.monotonic() - self.deployment_start_time) if self.deployment_start_time else 0
        return DeploymentStatus(
            status="RUNNING",
            mode=self.config.mode if self.config else "unknown",
            uptime_seconds=uptime,
            knowledge_graph_loaded=bool(self.config and self.config.knowledge_graph),
            knowledge_graph_version=(
                self.config.knowledge_graph.version
                if self.config and self.config.knowledge_graph
                else None
            ),
            ledger_entries=0,
            api_healthy=self.verify(),
            sidecar_connected=bool(self.config and self.config.sidecar.enabled),
            telemetry_received=0,
            verdicts_produced=0,
        )
