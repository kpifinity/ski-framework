# SKI Framework Reference Implementation - Quick Start

Get SKI Framework running in 5 minutes.

## Step 1: Prerequisites

```bash
# Verify you have Docker and Docker Compose
docker --version
docker-compose --version

# You need:
- Docker & Docker Compose
- 4GB RAM available
- Anthropic API key (get one at https://console.anthropic.com)
```

## Step 2: Clone and Configure

```bash
git clone https://github.com/kpifinity/ski-framework.git
cd reference-implementation

cp .env.example .env

# Edit .env and add your API key:
# ANTHROPIC_API_KEY=sk-...
nano .env  # or use your editor
```

## Step 3: Start Services

```bash
docker-compose up -d

# Wait 30 seconds for services to initialize
sleep 30

# Verify all services are running
docker-compose ps
```

## Step 4: Test the System

```bash
# 1. Check health
curl http://localhost:8000/api/health

# 2. Load sample Knowledge Graph
curl -X POST http://localhost:8000/api/kg/load \
  -H "Content-Type: application/json" \
  -d @examples/knowledge-graphs/sample-energy-kg.json

# 3. Submit sample telemetry
curl -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "telemetry_id": "tel_001",
    "timestamp": "2026-05-21T10:00:00Z",
    "subject": "Facility discharge",
    "measurement": "85 ppm sulfur dioxide"
  }'

# 4. Get verdict
curl http://localhost:8000/api/verdicts
```

## Step 5: View Dashboards

Open in your browser:
- **Grafana** (dashboards): http://localhost:3000
  - Username: admin
  - Password: admin

- **Prometheus** (metrics): http://localhost:9090

- **pgAdmin** (database): http://localhost:5050
  - Email: admin@example.com
  - Password: admin

---

## What You Have Running

| Service | Purpose | Port | Status |
|---------|---------|------|--------|
| MiLM | Inference engine | 8000 | http://localhost:8000/api/health |
| Sidecar | Data integration | 8001 | http://localhost:8001/health |
| PostgreSQL | Audit ledger | 5432 | Internal only |
| Kafka | Telemetry broker | 9092 | Internal only |
| Prometheus | Metrics | 9090 | http://localhost:9090 |
| Grafana | Dashboards | 3000 | http://localhost:3000 |

---

## Common Commands

```bash
# View logs
docker-compose logs -f milm

# Check database
docker exec -it ski-ledger-db psql -U ski -d ski_ledger

# Query verdicts
SELECT * FROM ledger_entries ORDER BY timestamp DESC LIMIT 10;

# Stop everything
docker-compose down

# Restart services
docker-compose restart
```

---

## Next Steps

1. **Use your own Knowledge Graph**
   ```bash
   cp /path/to/validated-kg.json examples/knowledge-graphs/kg.json
   docker-compose restart milm
   ```

2. **Connect your data source**
   - Edit `.env` to change `TELEMETRY_SOURCE`
   - Configure Kafka, HTTP, or file input

3. **Monitor verdicts**
   - Check Grafana dashboard at http://localhost:3000

4. **Review audit ledger**
   - Connect to PostgreSQL via pgAdmin

5. **For production deployment**
   - See [DEPLOYMENT.md](./docs/DEPLOYMENT.md) for detailed guidance

---

## Troubleshooting

**Services won't start?**
```bash
docker-compose down
docker-compose up -d
docker-compose logs
```

**Port already in use?**
```bash
# Change ports in docker-compose.yml and restart
```

**MiLM won't respond?**
```bash
# Check API key is set
echo $ANTHROPIC_API_KEY

# Check logs
docker logs milm-service
```

---

For detailed documentation, see:
- [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) — Full deployment guide
- [docs/CUSTOMIZATION.md](./docs/CUSTOMIZATION.md) — How to customize
- [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) — Common issues
- [README.md](../reference-implementation/README.md) — Architecture overview
