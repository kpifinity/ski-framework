# SKI Framework Reference Implementation

This directory contains a **complete, working reference implementation** of the SKI Framework. It demonstrates how all components work together in a real deployment.

## What Goes Here

A full SKI deployment including:
- **MiLM inference engine** — The runtime evaluation component
- **Data integration layer** — Connecting to operational telemetry
- **Immutable audit ledger** — Tamper-evident verdict logging
- **Configuration & orchestration** — Deployment and management
- **Monitoring & observability** — Health checks and alerting
- **Documentation** — How to customize and extend

## Architecture

```
Reference Implementation
├── docker-compose.yml        (Full stack deployment)
├── .env.example             (Configuration template)
├── src/
│   ├── milm/               (Inference engine)
│   ├── sidecar/            (Data integration)
│   ├── ledger/             (Audit ledger)
│   ├── config/             (Configuration)
│   └── monitoring/         (Health & observability)
├── tests/                  (Test suite)
├── docs/
│   ├── DEPLOYMENT.md       (How to deploy)
│   ├── CUSTOMIZATION.md    (How to customize)
│   └── TROUBLESHOOTING.md  (Common issues)
└── examples/
    ├── knowledge-graphs/   (Sample Knowledge Graphs)
    └── telemetry/         (Sample telemetry data)
```

## Quick Start

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.9+
- 2GB RAM, 10GB disk space
- Linux/macOS (or Windows with WSL2)

### 2. Deploy Locally

```bash
# Clone and navigate
git clone https://github.com/kpifinity/ski-framework.git
cd reference-implementation

# Copy configuration
cp .env.example .env

# Start the full stack
docker-compose up -d

# Verify it's running
docker-compose ps
```

### 3. Test with Sample Data

```bash
# Load sample Knowledge Graph
python scripts/load-kg.py examples/knowledge-graphs/energy-sample.json

# Send sample telemetry
python scripts/send-telemetry.py examples/telemetry/sample-data.json

# Check verdicts
python scripts/check-verdicts.py

# Verify audit ledger
python scripts/verify-ledger.py
```

### 4. View Results

```bash
# Check audit ledger
curl http://localhost:8000/api/ledger

# View verdicts
curl http://localhost:8000/api/verdicts

# Check system status
curl http://localhost:8000/api/health
```

## Key Components

### MiLM Service
**What it does**: Evaluates telemetry against Knowledge Graph
- Temperature = 0 (deterministic)
- Structured output validation
- No external API calls
- Runs on-premise only

**Configuration**: `src/milm/config.yaml`

### Data Sidecar
**What it does**: Integrates with operational telemetry
- Read-only connection to data sources
- Normalizes telemetry format
- Heartbeat for gap detection
- No modification of primary systems

**Configuration**: `src/sidecar/config.yaml`

### Audit Ledger
**What it does**: Records all verdicts immutably
- Hash-chained entries
- Tamper detection
- Verifiable without proprietary tools
- Cryptographically signed

**Storage**: SQLite (default) or PostgreSQL (production)

### Monitoring
**What it does**: Tracks system health
- MiLM performance metrics
- Data integration heartbeat
- Ledger integrity checks
- Resource utilization

**Dashboard**: Available at `http://localhost:8080`

## Configuration

### Environment Variables (.env)

```bash
# Inference
MILM_TEMPERATURE=0
MILM_MODEL=claude-3-haiku
MILM_MAX_TOKENS=500

# Data Integration
TELEMETRY_SOURCE=kafka        # kafka, http, file, etc.
TELEMETRY_BATCH_SIZE=100
HEARTBEAT_INTERVAL=60

# Ledger
LEDGER_BACKEND=sqlite         # sqlite, postgresql
LEDGER_PATH=/data/ledger.db
LEDGER_HASH_ALGORITHM=sha256

# Monitoring
PROMETHEUS_PORT=9090
LOG_LEVEL=INFO
```

See `.env.example` for all options.

## Customization

### Use Your Own Knowledge Graph

```bash
# Export your Knowledge Graph to JSON
python scripts/export-kg.py your-kg.json

# Load into reference implementation
python scripts/load-kg.py your-kg.json

# Verify it loaded
python scripts/validate-kg.py
```

### Connect Your Data Source

1. **Update telemetry source** in `.env`
2. **Configure data mapping** in `src/sidecar/telemetry_schema.yaml`
3. **Test connection** with `python scripts/test-connection.py`
4. **Monitor integration** in dashboard

See [CUSTOMIZATION.md](docs/CUSTOMIZATION.md) for details.

### Extend the System

The reference implementation is a starting point. You can:
- Add custom MCP connectors
- Implement alternative ledger backends
- Build custom monitoring dashboards
- Add additional evaluation logic

All code is modular and extensible.

## Testing

```bash
# Run full test suite
pytest tests/

# Test specific components
pytest tests/unit/test_milm.py
pytest tests/integration/test_sidecar.py
pytest tests/integration/test_ledger.py

# Test with coverage
pytest --cov=src tests/

# Performance testing
pytest tests/performance/
```

## Production Deployment

The reference implementation is suitable for:
- ✅ Learning and development
- ✅ Proof of concepts
- ✅ Small-scale deployments (<10K verdicts/day)

For production at scale:
- 🔧 Use a managed database (PostgreSQL)
- 🔧 Deploy with Kubernetes
- 🔧 Implement backup/redundancy
- 🔧 Set up proper monitoring
- 🔧 Work with KpiFinity for optimization

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for production guidance.

## Troubleshooting

Common issues and solutions are in [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md):
- Container startup failures
- Data integration issues
- Ledger verification errors
- Performance problems
- Configuration issues

## API Reference

```bash
# Load Knowledge Graph
POST /api/kg/load
  body: Knowledge Graph JSON

# Submit telemetry
POST /api/telemetry
  body: Telemetry record

# Get verdicts
GET /api/verdicts?limit=100

# Get audit ledger
GET /api/ledger?start=0&limit=100

# Verify ledger integrity
GET /api/ledger/verify

# System health
GET /api/health
```

See [docs/API.md](docs/API.md) for full reference.

## Roadmap

- **v1.0 (July 2026)**: Basic reference implementation
- **v1.1 (August 2026)**: Kubernetes deployment
- **v1.2 (September 2026)**: Advanced monitoring
- **v1.3 (October 2026)**: Multi-node federation

## Contributing

To improve the reference implementation:
1. Fork and create a branch
2. Make your changes
3. Add tests
4. Submit a pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

## Support

- **Questions?** Open an issue
- **Found a bug?** Report it with reproduction steps
- **Need production help?** Contact [KpiFinity](https://kpifinity.com)

---

For more details, see the full [SKI Framework specification](https://skiframework.org)
