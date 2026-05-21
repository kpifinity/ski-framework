# MiLM Deploy

Deploy and configure the MiLM (Micro Language Model) inference engine on-premise.

## What It Does

MiLM Deploy is the deployment toolkit for the SKI Framework's runtime evaluation engine. It handles:

1. **On-Premise Deployment** — Set up MiLM infrastructure with minimal configuration
2. **Knowledge Graph Loading** — Load and verify signed Knowledge Graphs
3. **Inference Configuration** — Configure MiLM for deterministic evaluation (temperature=0)
4. **Data Integration** — Connect operational telemetry sources
5. **Audit Ledger Setup** — Initialize immutable verdict logging
6. **Health Verification** — Validate deployment readiness
7. **Monitoring Setup** — Configure health checks and alerting

## Installation

```bash
# Clone the repository
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework/tools/milm-deploy

# Install dependencies
pip install -r requirements.txt

# Install the tool
pip install -e .
```

## Quick Start

### Deploy locally with Docker

```bash
milm-deploy init --config deployment-config.yaml
milm-deploy start --mode docker
```

### Deploy with validated Knowledge Graph

```bash
milm-deploy load-kg --kg validated-rules.json --verify-signature
milm-deploy start
```

### Test deployment

```bash
milm-deploy test --telemetry sample-data.json
```

## Usage

### Initialize deployment

```bash
milm-deploy init \
  --name "energy-compliance-system" \
  --sector energy \
  --output deployment-config.yaml
```

### Load Knowledge Graph

```bash
# Load and verify signature
milm-deploy load-kg \
  --kg validated-knowledge-graph.json \
  --verify-signature \
  --signing-cert cert.pem
```

### Start MiLM service

```bash
# Docker deployment
milm-deploy start --mode docker

# Kubernetes deployment
milm-deploy start --mode kubernetes --kubeconfig ./config

# Direct installation
milm-deploy start --mode direct --install-path /opt/milm
```

### Verify deployment

```bash
milm-deploy verify --endpoint http://localhost:8000
```

### Test with sample data

```bash
milm-deploy test \
  --endpoint http://localhost:8000 \
  --telemetry sample-telemetry.json \
  --output test-results.json
```

### Configure data integration

```bash
milm-deploy configure-sidecar \
  --telemetry-source kafka \
  --kafka-brokers localhost:9092 \
  --kafka-topic operational-data
```

### Stop deployment

```bash
milm-deploy stop
```

## Configuration

### deployment-config.yaml

```yaml
name: "energy-compliance-system"
sector: "energy"

milm:
  model: "claude-opus-4-6"
  temperature: 0
  max_tokens: 500
  timeout_seconds: 30

knowledge_graph:
  path: "./validated-kg.json"
  verify_signature: true
  signing_cert: "./cert.pem"
  version: "v1.0"

ledger:
  backend: "sqlite"  # sqlite or postgresql
  path: "/data/audit.db"
  hash_algorithm: "sha256"
  retention_days: 2555  # 7 years default

sidecar:
  enabled: true
  telemetry_source: "kafka"  # kafka, http, file
  batch_size: 100
  heartbeat_interval: 60

monitoring:
  enabled: true
  prometheus_port: 9090
  health_check_interval: 30

security:
  api_key_required: true
  tls_enabled: true
  cert_path: "/etc/milm/server.crt"
  key_path: "/etc/milm/server.key"
```

### Environment Variables

```bash
# API
ANTHROPIC_API_KEY=sk-...

# Deployment
MILM_PORT=8000
MILM_LOG_LEVEL=INFO
MILM_WORKERS=4

# Knowledge Graph
KG_PATH=./validated-kg.json
KG_VERIFY_SIGNATURE=true

# Ledger
LEDGER_BACKEND=sqlite
LEDGER_PATH=/data/audit.db

# Security
API_KEY=your-api-key
TLS_ENABLED=true
```

## How It Works

### Phase 1: Initialization

```bash
milm-deploy init creates:
├── deployment-config.yaml
├── docker-compose.yml (if Docker mode)
├── kubernetes/ (if Kubernetes mode)
├── certificates/ (TLS certs)
└── scripts/ (startup/shutdown scripts)
```

### Phase 2: Knowledge Graph Loading

```
Validated Knowledge Graph (JSON)
         ↓
Verify cryptographic signature
         ↓
Validate Knowledge Graph schema
         ↓
Load into MiLM runtime
         ↓
MiLM ready for evaluation
```

### Phase 3: Data Integration

```
Operational Telemetry
         ↓
SKI Sidecar (read-only)
         ↓
Normalize to standard format
         ↓
Pass to MiLM
         ↓
Evaluate against Knowledge Graph
         ↓
Produce verdict (CLEAR|FLAG|NULL|DISCRETIONARY)
         ↓
Write to Audit Ledger (immutable)
```

### Phase 4: Runtime Verification

```bash
milm-deploy verify checks:
├── MiLM service is running
├── Knowledge Graph is loaded
├── Audit ledger is initialized
├── Data integration is connected
├── API is responding
└── Health metrics are available
```

## Deployment Modes

### 1. Docker (Recommended for Development)

```bash
milm-deploy start --mode docker

Creates:
- MiLM inference service
- PostgreSQL (optional)
- Prometheus monitoring
- All in Docker containers
```

**Requirements:**
- Docker & Docker Compose
- 2GB RAM minimum
- Linux/macOS or Windows WSL2

### 2. Kubernetes (Production)

```bash
milm-deploy start --mode kubernetes --kubeconfig ./config

Creates:
- MiLM Deployment
- Service (ClusterIP/LoadBalancer)
- ConfigMap (configuration)
- Persistent Volume (ledger)
- Monitoring ServiceMonitor
```

**Requirements:**
- Kubernetes cluster
- kubectl configured
- Helm (optional)
- 5GB storage minimum

### 3. Direct Installation (On-Premise)

```bash
milm-deploy start --mode direct --install-path /opt/milm

Creates:
- systemd service
- systemd timer (for health checks)
- Log rotation configuration
- Monitoring agent integration
```

**Requirements:**
- Linux server (Ubuntu 20.04+, RHEL 8+)
- Python 3.9+
- Systemd
- 2GB RAM

## Common Tasks

### Deploy with existing Knowledge Graph

```bash
# Step 1: Load validated rules
kg-validator validate --input extracted.json --output validated.json

# Step 2: Initialize deployment
milm-deploy init --sector energy --output config.yaml

# Step 3: Load Knowledge Graph
milm-deploy load-kg --kg validated.json

# Step 4: Start MiLM
milm-deploy start --mode docker

# Step 5: Verify
milm-deploy verify
```

### Test evaluation against sample data

```bash
# Create sample telemetry
cat > sample.json << EOF
{
  "telemetry_id": "tel_001",
  "timestamp": "2026-05-21T10:00:00Z",
  "subject": "Facility discharge",
  "measurement": "85 ppm sulfur dioxide"
}
EOF

# Test
milm-deploy test --telemetry sample.json
```

### Monitor running deployment

```bash
# Check status
milm-deploy status

# View logs
milm-deploy logs --follow

# Get health metrics
curl http://localhost:8000/api/health
```

### Update Knowledge Graph (blue-green deployment)

```bash
# Load new Knowledge Graph version without stopping service
milm-deploy load-kg --kg updated-kg.json --version v2.0 --activate-at 2026-05-22T00:00:00Z

# At scheduled time, MiLM switches to new version
# Previous version remains as fallback
```

## Help & Documentation

```bash
# Get help
milm-deploy --help
milm-deploy init --help

# See examples
milm-deploy examples

# View deployment status
milm-deploy status
```

## API Reference

Once deployed, MiLM provides REST API:

```bash
# Load Knowledge Graph
POST /api/kg/load
  body: { "kg_json": {...} }

# Submit telemetry for evaluation
POST /api/evaluate
  body: { "telemetry": {...} }

# Get verdict result
GET /api/verdicts/{verdict_id}

# Get audit ledger entries
GET /api/ledger?start=0&limit=100

# Health check
GET /api/health

# System status
GET /api/status
```

## Troubleshooting

### "Knowledge Graph signature verification failed"
- Verify signing certificate is correct: `milm-deploy load-kg --verify-signature`
- Check certificate hasn't expired

### "MiLM service won't start"
- Check logs: `milm-deploy logs`
- Verify API key is set: `echo $ANTHROPIC_API_KEY`
- Check port 8000 is available: `lsof -i :8000`

### "Data integration not receiving telemetry"
- Verify sidecar is running: `milm-deploy status`
- Check kafka/http endpoint is accessible
- Review sidecar logs: `milm-deploy logs --service sidecar`

### "Audit ledger not recording verdicts"
- Verify ledger database is accessible
- Check disk space: `df -h /data`
- Verify database permissions

## Roadmap

- **v1.0** — Docker & direct installation deployment
- **v1.1** — Kubernetes support
- **v1.2** — Blue-green Knowledge Graph updates
- **v1.3** — Multi-region federation
- **v1.4** — GraphQL API for query

## License

CC BY 4.0 — See [LICENSE.md](../../LICENSE.md)

---

For more information:
- [KG Validator](../kg-validator/README.md) — Validate rules before deployment
- [Reference Implementation](../../reference-implementation/README.md)
- [SKI Architecture](../../docs/ARCHITECTURE.md)
