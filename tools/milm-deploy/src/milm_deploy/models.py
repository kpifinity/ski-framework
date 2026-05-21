"""
Data models for MiLM Deploy
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum


class DeploymentMode(str, Enum):
    """Deployment mode"""
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    DIRECT = "direct"


class DeploymentStatus(str, Enum):
    """Status of deployment"""
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class MiLMConfig(BaseModel):
    """MiLM inference engine configuration"""
    model: str = "claude-opus-4-6"
    temperature: float = Field(0.0, ge=0, le=0)  # Must be 0 for deterministic
    max_tokens: int = 500
    timeout_seconds: int = 30
    max_retries: int = 3


class KnowledgeGraphConfig(BaseModel):
    """Knowledge Graph configuration"""
    path: str
    version: str = "v1.0"
    verify_signature: bool = True
    signing_cert: Optional[str] = None
    auto_reload: bool = False
    reload_interval_seconds: Optional[int] = None


class LedgerConfig(BaseModel):
    """Audit ledger configuration"""
    backend: str = "sqlite"  # sqlite or postgresql
    path: str = "/data/audit.db"
    hash_algorithm: str = "sha256"
    retention_days: int = 2555  # 7 years default
    backup_enabled: bool = True
    backup_interval_days: int = 7


class SidecarConfig(BaseModel):
    """Data integration sidecar configuration"""
    enabled: bool = True
    telemetry_source: str = "kafka"  # kafka, http, file
    batch_size: int = 100
    heartbeat_interval: int = 60
    kafka_brokers: Optional[str] = None
    kafka_topic: Optional[str] = None
    http_endpoint: Optional[str] = None
    file_path: Optional[str] = None


class MonitoringConfig(BaseModel):
    """Monitoring and observability configuration"""
    enabled: bool = True
    prometheus_port: int = 9090
    health_check_interval: int = 30
    log_level: str = "INFO"
    log_format: str = "json"


class SecurityConfig(BaseModel):
    """Security configuration"""
    api_key_required: bool = True
    tls_enabled: bool = False
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    api_key: Optional[str] = None


class DeploymentConfig(BaseModel):
    """Complete deployment configuration"""
    name: str
    sector: str
    mode: DeploymentMode = DeploymentMode.DOCKER
    install_path: str = "/opt/milm"

    milm: MiLMConfig = MiLMConfig()
    knowledge_graph: Optional[KnowledgeGraphConfig] = None
    ledger: LedgerConfig = LedgerConfig()
    sidecar: SidecarConfig = SidecarConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    security: SecurityConfig = SecurityConfig()

    class Config:
        use_enum_values = False


class DeploymentStatus(BaseModel):
    """Status of running deployment"""
    status: DeploymentStatus
    mode: DeploymentMode
    uptime_seconds: int
    knowledge_graph_loaded: bool
    knowledge_graph_version: Optional[str] = None
    ledger_entries: int
    api_healthy: bool
    sidecar_connected: bool
    telemetry_received: int
    verdicts_produced: int
    last_verdict_timestamp: Optional[str] = None

    class Config:
        use_enum_values = True


class HealthCheck(BaseModel):
    """Health check result"""
    service: str
    status: str  # healthy, degraded, unhealthy
    response_time_ms: float
    details: Dict[str, Any] = {}
