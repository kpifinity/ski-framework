# SKI Framework Scripts

This directory contains **utility scripts** for deploying, testing, managing, and maintaining SKI Framework installations.

## What Goes Here

Helper scripts for:
- **Deployment** — Initial setup and configuration
- **Testing** — Validate Knowledge Graphs and system behavior
- **Operations** — Manage Knowledge Graphs and audit ledgers
- **Maintenance** — Backup, verification, and cleanup
- **Development** — Code generation and utilities for developers

## Script Categories

### Deployment Scripts

**`setup.sh`** — Initial deployment setup
```bash
./scripts/setup.sh --env prod --region us-east-1
```
Creates: Docker containers, database, configuration, SSL certificates

**`deploy.sh`** — Deploy to infrastructure
```bash
./scripts/deploy.sh --stack reference-implementation
```
Deploys: Reference implementation to specified environment

**`configure.sh`** — Initial configuration
```bash
./scripts/configure.sh --kg knowledge-graph.json
```
Sets up: Knowledge Graph, data sources, policies

### Testing Scripts

**`test-kg.py`** — Validate Knowledge Graph
```bash
python scripts/test-kg.py knowledge-graph.json
```
Checks: Schema compliance, rule validity, conflicts, completeness

**`test-telemetry.py`** — Validate telemetry format
```bash
python scripts/test-telemetry.py sample-telemetry.json
```
Checks: Schema validation, data quality, completeness

**`test-verdict.py`** — Test specific verdict scenarios
```bash
python scripts/test-verdict.py --kg kg.json --telemetry data.json
```
Runs: Knowledge Graph rules against test data, compares results

**`test-ledger.py`** — Verify audit ledger
```bash
python scripts/test-ledger.py ledger.db
```
Checks: Hash chain integrity, completeness, format compliance

### Operations Scripts

**`load-kg.py`** — Load Knowledge Graph
```bash
python scripts/load-kg.py knowledge-graph.json --endpoint http://localhost:8000
```
Loads: Knowledge Graph into running system

**`export-kg.py`** — Export Knowledge Graph
```bash
python scripts/export-kg.py --endpoint http://localhost:8000 > kg-backup.json
```
Exports: Current Knowledge Graph from running system

**`verify-ledger.py`** — Verify ledger integrity
```bash
python scripts/verify-ledger.py ledger.db
```
Verifies: Hash chain, entries are complete, no tampering

**`backup-ledger.sh`** — Backup audit ledger
```bash
./scripts/backup-ledger.sh --destination /backups/ledger-2026-05-21.db
```
Backs up: Immutable ledger with verification

### Maintenance Scripts

**`cleanup.sh`** — Clean up temporary files
```bash
./scripts/cleanup.sh --older-than 30 --remove
```
Removes: Old logs, temporary files, test data (with confirmation)

**`migrate.py`** — Migrate Knowledge Graph versions
```bash
python scripts/migrate.py old-kg.json new-kg.json
```
Migrates: Knowledge Graph between versions with validation

**`rotate-keys.sh`** — Rotate cryptographic keys
```bash
./scripts/rotate-keys.sh --new-key-path /path/to/new.key
```
Rotates: Signing keys with audit trail

### Development Scripts

**`generate-test-data.py`** — Generate sample telemetry
```bash
python scripts/generate-test-data.py --sector energy --count 1000
```
Generates: Realistic sample telemetry for testing

**`generate-kg.py`** — Generate sample Knowledge Graph
```bash
python scripts/generate-kg.py --sector finance --rules 50
```
Generates: Sample Knowledge Graph for learning

**`generate-schema.py`** — Generate schemas from examples
```bash
python scripts/generate-schema.py telemetry-example.json
```
Generates: JSON schemas from example data

## Usage Guide

### Prerequisites
- Python 3.9+
- Bash shell (Linux/macOS) or PowerShell (Windows)
- Required Python packages: `pip install -r scripts/requirements.txt`

### Running Scripts

```bash
# Make scripts executable (Linux/macOS)
chmod +x scripts/*.sh

# Run a script
./scripts/setup.sh

# Or with Python
python scripts/test-kg.py knowledge-graph.json
```

### Help & Documentation

```bash
# Get help for any script
./scripts/setup.sh --help
python scripts/test-kg.py --help
```

Each script includes detailed help with examples.

## Common Tasks

### Deploy SKI Locally
```bash
./scripts/setup.sh --env local
./scripts/deploy.sh --stack reference-implementation
python scripts/load-kg.py sample-kg.json
```

### Validate a Knowledge Graph
```bash
python scripts/test-kg.py my-kg.json
python scripts/test-verdict.py --kg my-kg.json --telemetry sample-data.json
```

### Backup Your System
```bash
./scripts/backup-ledger.sh --destination /backups/
./scripts/export-kg.py > kg-backup.json
```

### Test Telemetry Integration
```bash
python scripts/test-telemetry.py sample-telemetry.json
python scripts/test-verdict.py --kg kg.json --telemetry test-data.json
```

## Creating New Scripts

To contribute a new script:

1. **Create in `scripts/` folder** with descriptive name
2. **Add shebang** (`#!/bin/bash` or `#!/usr/bin/env python`)
3. **Include help** (`--help` flag)
4. **Write documentation** in docstring/comments
5. **Add to this README** in appropriate category
6. **Test thoroughly** before submitting

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

## Script Library

### Available Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `setup.sh` | Initial deployment | `./setup.sh --env [env]` |
| `deploy.sh` | Deploy stack | `./deploy.sh --stack [stack]` |
| `test-kg.py` | Validate Knowledge Graph | `python test-kg.py kg.json` |
| `test-verdict.py` | Test verdicts | `python test-verdict.py --kg kg.json --telemetry data.json` |
| `test-ledger.py` | Verify ledger | `python test-ledger.py ledger.db` |
| `load-kg.py` | Load Knowledge Graph | `python load-kg.py kg.json` |
| `export-kg.py` | Export Knowledge Graph | `python export-kg.py > backup.json` |
| `backup-ledger.sh` | Backup ledger | `./backup-ledger.sh --destination /path` |
| `verify-ledger.py` | Verify ledger integrity | `python verify-ledger.py ledger.db` |

### Planned Scripts

- `migrate.py` — Migrate between KG versions
- `rotate-keys.sh` — Rotate signing keys
- `generate-test-data.py` — Generate sample data
- `compliance-report.py` — Generate compliance reports
- `performance-test.py` — Performance benchmarking

## Troubleshooting

### Script won't run
- **Linux/macOS**: Make executable with `chmod +x script.sh`
- **Windows**: Run PowerShell as Administrator
- Check Python version: `python --version`

### Permission denied
```bash
# Make script executable
chmod +x scripts/script-name.sh
```

### Python module not found
```bash
# Install requirements
pip install -r scripts/requirements.txt
```

### Need help with a script
```bash
# Get detailed help
./scripts/script-name.sh --help
# or
python scripts/script-name.py --help
```

## Support

- **Bug in a script?** Open an issue with reproduction steps
- **Want to add a script?** See [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Need help?** Check the script's `--help` or ask in issues

---

For more information, see:
- [Getting Started Guide](../docs/GETTING_STARTED.md)
- [Reference Implementation](../reference-implementation/README.md)
- [Full SKI Framework](https://skiframework.org)
