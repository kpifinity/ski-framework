"""
Utility functions for MiLM Deploy
"""

import json
import yaml
import os
from typing import Optional
from jinja2 import Template

from .models import DeploymentConfig


def load_config(config_path: str) -> DeploymentConfig:
    """
    Load deployment configuration from file

    Args:
        config_path: Path to YAML or JSON config file

    Returns:
        DeploymentConfig object
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration not found: {config_path}")

    with open(config_path, "r") as f:
        if config_path.endswith(".yaml") or config_path.endswith(".yml"):
            config_data = yaml.safe_load(f)
        else:
            config_data = json.load(f)

    return DeploymentConfig(**config_data)


def save_config(config: DeploymentConfig, output_path: str) -> None:
    """
    Save deployment configuration to file

    Args:
        config: DeploymentConfig object
        output_path: Path to save (YAML or JSON)
    """
    config_dict = config.dict()

    if output_path.endswith(".yaml") or output_path.endswith(".yml"):
        with open(output_path, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
    else:
        with open(output_path, "w") as f:
            json.dump(config_dict, f, indent=2)


DOCKER_COMPOSE_TEMPLATE = """version: '3.8'

services:
  milm:
    image: kpifinity/milm:latest
    container_name: milm-{{ name }}
    ports:
      - "8000:8000"
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      MILM_MODEL: {{ milm.model }}
      MILM_TEMPERATURE: {{ milm.temperature }}
      MILM_MAX_TOKENS: {{ milm.max_tokens }}
      KG_PATH: /app/kg.json
    volumes:
      - ./kg.json:/app/kg.json:ro
      - milm-ledger:/data
    networks:
      - ski-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  {% if sidecar.enabled %}
  sidecar:
    image: kpifinity/sidecar:latest
    container_name: sidecar-{{ name }}
    environment:
      MILM_ENDPOINT: http://milm:8000
      TELEMETRY_SOURCE: {{ sidecar.telemetry_source }}
      BATCH_SIZE: {{ sidecar.batch_size }}
      HEARTBEAT_INTERVAL: {{ sidecar.heartbeat_interval }}
    {% if sidecar.kafka_brokers %}
      KAFKA_BROKERS: {{ sidecar.kafka_brokers }}
      KAFKA_TOPIC: {{ sidecar.kafka_topic }}
    {% endif %}
    networks:
      - ski-network
    depends_on:
      - milm
    restart: unless-stopped
  {% endif %}

  {% if monitoring.enabled %}
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus-{{ name }}
    ports:
      - "{{ monitoring.prometheus_port }}:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    networks:
      - ski-network
    restart: unless-stopped
  {% endif %}

volumes:
  milm-ledger:
  {% if monitoring.enabled %}
  prometheus-data:
  {% endif %}

networks:
  ski-network:
    driver: bridge
"""


def generate_docker_compose(config: DeploymentConfig) -> str:
    """
    Generate docker-compose.yml from configuration

    Args:
        config: DeploymentConfig object

    Returns:
        Docker Compose YAML as string
    """
    template = Template(DOCKER_COMPOSE_TEMPLATE)
    return template.render(
        name=config.name,
        milm=config.milm.dict(),
        sidecar=config.sidecar.dict(),
        monitoring=config.monitoring.dict(),
    )


def generate_k8s_manifest(config: DeploymentConfig) -> str:
    """
    Generate Kubernetes manifests from configuration

    Args:
        config: DeploymentConfig object

    Returns:
        Kubernetes YAML as string
    """
    # Placeholder for Kubernetes manifest generation
    return ""


def generate_systemd_service(config: DeploymentConfig) -> str:
    """
    Generate systemd service file from configuration

    Args:
        config: DeploymentConfig object

    Returns:
        Systemd service file content
    """
    service_template = """[Unit]
Description=SKI Framework MiLM Inference Engine - {{ name }}
After=network.target

[Service]
Type=simple
User=milm
WorkingDirectory={{ install_path }}
ExecStart=/usr/bin/python3 -m milm.server
Environment="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
Environment="MILM_CONFIG={{ install_path }}/config.yaml"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    template = Template(service_template)
    return template.render(
        name=config.name,
        install_path=config.install_path,
    )
