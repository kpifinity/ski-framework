"""Utility functions for ski-model-deploy."""

from __future__ import annotations

import json
import os

import yaml
from jinja2 import Template

from .models import DeploymentConfig


def load_config(config_path: str) -> DeploymentConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration not found: {config_path}")

    with open(config_path, "r") as f:
        if config_path.endswith((".yaml", ".yml")):
            config_data = yaml.safe_load(f)
        else:
            config_data = json.load(f)

    return DeploymentConfig(**config_data)


def save_config(config: DeploymentConfig, output_path: str) -> None:
    data = config.model_dump()
    if output_path.endswith((".yaml", ".yml")):
        with open(output_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=True)
    else:
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Docker compose template
# ---------------------------------------------------------------------------
#
# Sovereign-by-default: no ANTHROPIC_API_KEY anywhere. Ollama is the
# inference backend. Operators who want the non-conformant demo backend
# can override SKI_INFERENCE_BACKEND=anthropic and supply the key out of
# band, with the caveat that doing so disqualifies the deployment.

DOCKER_COMPOSE_TEMPLATE = """version: '3.8'

services:
  ollama:
    image: ollama/ollama:0.3.12
    container_name: ollama-{{ name }}
    volumes:
      - ollama-models:/root/.ollama
    networks:
      - ski-network
    restart: unless-stopped

  ski-model:
    image: kpifinity/ski-model:0.1.0-alpha
    container_name: ski-model-{{ name }}
    ports:
      - "8000:8000"
    environment:
      SKI_INFERENCE_BACKEND: {{ ski_model.backend }}
      SKI_MODEL_NAME: {{ ski_model.model }}
      SKI_MODEL_TEMPERATURE: "{{ ski_model.temperature }}"
      SKI_MODEL_SEED: "{{ ski_model.seed }}"
      SKI_MODEL_MAX_TOKENS: "{{ ski_model.max_tokens }}"
      KG_PATH: /app/kg/kg.json
      KG_REQUIRE_SIGNATURE: "true"
      TLS_ENABLED: "{{ security.tls_enabled | string | lower }}"
      API_KEY_REQUIRED: "{{ security.api_key_required | string | lower }}"
      OLLAMA_BASE_URL: http://ollama:11434
    volumes:
      - ./kg.json:/app/kg/kg.json:ro
      - ski-model-data:/data
    networks:
      - ski-network
    depends_on:
      - ollama
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fkS", "https://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  {% if sidecar.enabled %}
  sidecar:
    image: kpifinity/ski-sidecar:0.1.0-alpha
    container_name: sidecar-{{ name }}
    environment:
      SKI_MODEL_ENDPOINT: https://ski-model:8000
      TELEMETRY_SOURCE: {{ sidecar.telemetry_source }}
      TELEMETRY_BATCH_SIZE: "{{ sidecar.batch_size }}"
      HEARTBEAT_INTERVAL: "{{ sidecar.heartbeat_interval }}"
      {% if sidecar.kafka_brokers %}KAFKA_BROKERS: {{ sidecar.kafka_brokers }}
      KAFKA_TOPIC: {{ sidecar.kafka_topic }}{% endif %}
    networks:
      - ski-network
    depends_on:
      - ski-model
    restart: unless-stopped
  {% endif %}

  {% if monitoring.enabled %}
  prometheus:
    image: prom/prometheus:v2.50.1
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
  ollama-models:
  ski-model-data:
  {% if monitoring.enabled %}prometheus-data:{% endif %}

networks:
  ski-network:
    driver: bridge
"""


def generate_docker_compose(config: DeploymentConfig) -> str:
    template = Template(DOCKER_COMPOSE_TEMPLATE)
    return template.render(
        name=config.name,
        ski_model=config.ski_model.model_dump(),
        sidecar=config.sidecar.model_dump(),
        monitoring=config.monitoring.model_dump(),
        security=config.security.model_dump(),
    )


SYSTEMD_TEMPLATE = """[Unit]
Description=SKI Model inference engine — {{ name }}
After=network.target

[Service]
Type=simple
User=ski-model
WorkingDirectory={{ install_path }}
ExecStart=/usr/bin/python3 -m ski_model.server
EnvironmentFile={{ install_path }}/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def generate_systemd_service(config: DeploymentConfig) -> str:
    return Template(SYSTEMD_TEMPLATE).render(name=config.name, install_path=config.install_path)


def generate_k8s_manifest(config: DeploymentConfig) -> str:
    """Planned for v0.2 — see reference-implementation/docs/KUBERNETES.md."""
    return ""
