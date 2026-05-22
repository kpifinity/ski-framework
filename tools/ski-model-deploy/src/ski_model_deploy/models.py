"""Data models for ski-model-deploy.

v2.1 changes:
  * MiLM → SKI Model renames.
  * `KnowledgeGraphConfig.verify_signature` removed — verification is
    mandatory at the deployer level, not a knob.
  * `SecurityConfig.tls_enabled` defaults to True.
  * `MiLMConfig` renamed to `SkiModelConfig`. The default model is no
    longer a Claude SKU; the local Ollama model is the default.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DeploymentMode(str, Enum):
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    DIRECT = "direct"


class DeploymentStatusEnum(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class SkiModelConfig(BaseModel):
    """SKI Model service configuration."""

    backend: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = Field(0.0, ge=0, le=0)  # must be 0 for determinism
    seed: int = 42
    max_tokens: int = 512
    model_file_sha256: Optional[str] = None
    timeout_seconds: int = 60
    max_retries: int = 3


class KnowledgeGraphConfig(BaseModel):
    """Knowledge Graph configuration as known to the deployer."""

    path: str
    version: str = "v0.1"
    signature_verified: bool = True  # set by the deployer after verification
    auto_reload: bool = False
    reload_interval_seconds: Optional[int] = None


class LedgerConfig(BaseModel):
    backend: str = "postgresql"
    dsn_env: str = "LEDGER_DSN"
    hash_algorithm: str = "sha256"
    # Retention is operator policy. Sensible regulated-industry defaults
    # are 5–10 years; we don't impose a default here so cleanup scripts
    # cannot quietly destroy required evidence.
    retention_days: Optional[int] = None
    backup_enabled: bool = True
    backup_interval_days: int = 7


class SidecarConfig(BaseModel):
    enabled: bool = True
    telemetry_source: str = "file"  # file | http | kafka
    batch_size: int = 100
    heartbeat_interval: int = 60
    kafka_brokers: Optional[str] = None
    kafka_topic: Optional[str] = None
    http_endpoint: Optional[str] = None
    file_path: Optional[str] = None


class MonitoringConfig(BaseModel):
    enabled: bool = True
    prometheus_port: int = 9090
    health_check_interval: int = 30
    log_level: str = "INFO"
    log_format: str = "json"


class SecurityConfig(BaseModel):
    api_key_required: bool = True
    tls_enabled: bool = True
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    api_key: Optional[str] = None


class DeploymentConfig(BaseModel):
    name: str
    sector: str
    mode: DeploymentMode = DeploymentMode.DOCKER
    install_path: str = "/opt/ski-model"

    ski_model: SkiModelConfig = SkiModelConfig()
    knowledge_graph: Optional[KnowledgeGraphConfig] = None
    ledger: LedgerConfig = LedgerConfig()
    sidecar: SidecarConfig = SidecarConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    security: SecurityConfig = SecurityConfig()


class DeploymentStatus(BaseModel):
    status: DeploymentStatusEnum = DeploymentStatusEnum.UNINITIALIZED
    mode: DeploymentMode = DeploymentMode.DOCKER
    uptime_seconds: int = 0
    knowledge_graph_loaded: bool = False
    knowledge_graph_version: Optional[str] = None
    ledger_entries: int = 0
    api_healthy: bool = False
    sidecar_connected: bool = False
    telemetry_received: int = 0
    verdicts_produced: int = 0
    last_verdict_timestamp: Optional[str] = None


class HealthCheck(BaseModel):
    service: str
    status: str
    response_time_ms: float
    details: Dict[str, Any] = {}
