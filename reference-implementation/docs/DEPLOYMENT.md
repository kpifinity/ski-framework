# SKI Framework Reference Implementation - Deployment Guide

## Quick Start (5 minutes)

### Prerequisites
- Docker & Docker Compose (v1.29+)
- 4GB RAM minimum
- 10GB disk space
- Anthropic API key

### Step 1: Clone and Setup

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd reference-implementation

# Copy environment template
cp .env.example .env

# Edit .env and add your API key
export ANTHROPIC_API_KEY=sk-your-key-here
```

### Step 2: Load Knowledge Graph

```bash
# MiLM will automatically load from examples/knowledge-graphs/sample-energy-kg.json
# Or copy your own validated Knowledge Graph:
cp /path/to/validated-kg.json examples/knowledge-graphs/kg.json
```

### Step 3: Start the Stack

```bash
# Start all services
docker-compose up -d

# Wait for services to initialize (~30 seconds)
docker-compose ps

# Should see all containers in "Up" state
```

### Step 4: Verify Deployment

```bash
# Health check
curl http://localhost:8000/api/health

# Load Knowledge Graph (if not auto-loaded)
curl -X POST http://localhost:8000/api/kg/load \
  -H "Content-Type: application/json" \
  -d @examples/knowledge-graphs/sample-energy-kg.json

# Submit sample telemetry
curl -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "telemetry_id": "tel_001",
    "timestamp": "2026-05-21T10:00:00Z",
    "subject": "Facility discharge",
    "measurement": "85 ppm sulfur dioxide"
  }'

# Expected response: Verdict with CLEAR, FLAG, NULL, or DISCRETIONARY
```

### Step 5: View Dashboard

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **pgAdmin**: http://localhost:5050 (admin@example.com/admin)

---

## Deployment Modes

### Mode 1: Local Docker (Recommended)

**Best for:** Development, testing, proof-of-concept

```bash
docker-compose up -d
```

Services in this mode:
- ✅ MiLM (CPU only, works on any machine)
- ✅ PostgreSQL (local audit ledger)
- ✅ Kafka (telemetry source)
- ✅ Prometheus + Grafana (monitoring)

**Advantages:**
- Single command to start
- Full featured
- Easy to modify and experiment
- Self-contained

**Limitations:**
- Single node
- Shared resources
- No high availability

### Mode 2: Production on Kubernetes (Future)

See [KUBERNETES.md](./KUBERNETES.md) for Kubernetes deployment.

---

## Configuration

### Environment Variables

Edit `.env` before running `docker-compose up`:

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-your-api-key

# MiLM configuration
MILM_MODEL=claude-opus-4-6
MILM_TEMPERATURE=0
MILM_MAX_TOKENS=500

# Database
POSTGRES_PASSWORD=change-me

# Data source
TELEMETRY_SOURCE=kafka  # or http, file

# Monitoring
GRAFANA_PASSWORD=change-me
```

### Custom Configuration

To use your own Knowledge Graph:

```bash
# Copy your validated Knowledge Graph
cp /path/to/validated-kg.json examples/knowledge-graphs/kg.json

# Or change the path in docker-compose.yml:
# volumes:
#   - ./examples/knowledge-graphs/your-kg.json:/app/kg.json:ro
```

---

## Data Sources

### Kafka (Default)

Telemetry flows: Your System → Kafka → Sidecar → MiLM

```bash
# Send test message to Kafka
docker exec ski-kafka kafka-console-producer.sh \
  --broker-list localhost:9092 \
  --topic operational-data

# Paste JSON and press Enter:
{"id": "tel_001", "timestamp": "2026-05-21T10:00:00Z", "subject": "Facility discharge", "measurement": "85 ppm"}
```

### HTTP (Alternative)

```bash
# Configure in .env:
TELEMETRY_SOURCE=http

# Send telemetry via HTTP:
curl -X POST http://localhost:8001/api/telemetry \
  -H "Content-Type: application/json" \
  -d '{"id": "tel_001", "subject": "...", "measurement": "..."}'
```

### File (Development)

```bash
# Configure in .env:
TELEMETRY_SOURCE=file

# Edit examples/telemetry/sample-data.jsonl
# Sidecar will process line-by-line
```

---

## Monitoring & Observability

### Prometheus Metrics

Available at: http://localhost:9090

Key metrics:
- `milm_verdicts_total` — Total verdicts produced
- `milm_evaluation_duration_ms` — Evaluation latency
- `sidecar_telemetry_received_total` — Telemetry received
- `ledger_entries_total` — Audit ledger size

### Grafana Dashboards

Available at: http://localhost:3000

Pre-configured dashboards:
- SKI System Overview
- MiLM Performance
- Audit Ledger
- Data Integration

### Logs

```bash
# View logs for MiLM
docker logs milm-service -f

# View logs for sidecar
docker logs ski-sidecar -f

# View database logs
docker logs ski-ledger-db -f
```

---

## Operations

### Stop Deployment

```bash
docker-compose down
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart milm
```

### View Database

```bash
# Connect to PostgreSQL
docker exec -it ski-ledger-db psql -U ski -d ski_ledger

# Query audit ledger
SELECT * FROM ledger_entries ORDER BY timestamp DESC LIMIT 10;

# Check integrity
SELECT * FROM ledger_integrity WHERE chain_valid = false;
```

### Backup Ledger

```bash
# Backup database
docker exec ski-ledger-db pg_dump -U ski ski_ledger > ledger-backup.sql

# Backup volume
docker run --rm \
  -v ski-reference-implementation_milm-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/milm-data-backup.tar.gz /data
```

### Health Checks

```bash
# Quick health check
curl http://localhost:8000/api/health

# Detailed status
curl http://localhost:8000/api/status

# Database health
docker exec ski-ledger-db pg_isready -U ski
```

---

## Troubleshooting

### "Port already in use"

```bash
# Find what's using port 8000
lsof -i :8000

# Use different ports:
# Edit docker-compose.yml and change port mappings
```

### "Connection refused" when calling API

```bash
# Wait for services to start
docker-compose logs -f milm

# Check service is running
docker-compose ps

# Verify MiLM health
curl http://localhost:8000/api/health
```

### "Knowledge Graph not loaded"

```bash
# Check if file exists
ls -la examples/knowledge-graphs/kg.json

# Load manually
curl -X POST http://localhost:8000/api/kg/load \
  -H "Content-Type: application/json" \
  -d @examples/knowledge-graphs/sample-energy-kg.json

# Check logs
docker logs milm-service | grep -i "knowledge"
```

### "Sidecar not receiving telemetry"

```bash
# Check Kafka connectivity
docker exec ski-kafka kafka-broker-api-versions.sh --bootstrap-server localhost:9092

# Check topic exists
docker exec ski-kafka kafka-topics.sh \
  --list --bootstrap-server localhost:9092

# Create topic if missing
docker exec ski-kafka kafka-topics.sh \
  --create --topic operational-data \
  --bootstrap-server localhost:9092 \
  --partitions 1 --replication-factor 1
```

### "Database connection error"

```bash
# Check PostgreSQL is running
docker-compose logs postgres

# Reset database
docker-compose down
docker volume rm reference-implementation_postgres-data
docker-compose up -d postgres
```

---

## Next Steps

1. **Load your Knowledge Graph** — Replace sample-energy-kg.json with your validated rules
2. **Connect your data source** — Configure Kafka/HTTP/file telemetry source
3. **Monitor verdicts** — Check http://localhost:3000 for real-time dashboard
4. **Review audit ledger** — Access PostgreSQL via pgAdmin at http://localhost:5050
5. **Scale for production** — See KUBERNETES.md for production deployment

---

## Support

- **Issues?** Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **Customization?** See [CUSTOMIZATION.md](./CUSTOMIZATION.md)
- **Questions?** Open an issue on GitHub
