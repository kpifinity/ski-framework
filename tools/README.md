# SKI Framework Tools

This directory contains **open-source tooling** for implementing the SKI Framework. These tools help with Knowledge Graph creation, validation, deployment, and management.

## What Goes Here

Tools for:
- **Knowledge Graph extraction** — Extract compliance rules from regulatory documents
- **Knowledge Graph validation** — Validate and test Knowledge Graphs
- **MiLM deployment** — Deploy and configure the inference engine
- **Audit ledger management** — Create, verify, and manage audit ledgers
- **Data integration** — Build MCP connectors and sidecar integrations
- **Utilities** — Helper tools for operators and developers

## Current Tools

*Coming in v1.0-RC1*

- `kg-extractor/` — LLM-assisted Knowledge Graph extraction pipeline
- `kg-validator/` — Human validation framework for extracted rules
- `milm-deploy/` — MiLM deployment toolkit
- `audit-ledger/` — Immutable audit ledger reference implementation

## Development

Each tool is:
- **Self-contained** — Has its own README and requirements
- **Well-documented** — Includes examples and usage guides
- **Tested** — Includes test suite
- **Licensed** — Published under CC BY 4.0

### Structure of a Tool

```
tool-name/
├── README.md           (Usage guide)
├── requirements.txt    (Dependencies)
├── setup.py           (Installation)
├── src/               (Source code)
├── tests/             (Test suite)
└── examples/          (Usage examples)
```

## Using a Tool

```bash
# Install
pip install -r tool-name/requirements.txt

# Use
python -m tool_name [arguments]

# Test
pytest tool-name/tests/
```

## Contributing a Tool

To contribute a new tool:

1. Create a folder in `tools/` with a clear name
2. Follow the structure above
3. Write comprehensive README
4. Include tests
5. Submit pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

## Tool Categories

### Extraction & Validation
- Extract rules from regulatory documents (LLM-assisted)
- Validate extracted rules against source documents
- Manage human review and approval process
- Handle conflicts and precedence

### Deployment & Operations
- Deploy MiLM on-premise infrastructure
- Configure inference engine
- Manage Knowledge Graph versions
- Monitor system health

### Integration & Connectivity
- MCP server implementations
- Data sidecar integration patterns
- Telemetry normalization
- Event streaming

### Analysis & Reporting
- Audit ledger verification
- Verdict analysis and reporting
- Coverage analysis
- Compliance dashboards

## Roadmap

- **v1.0-RC1 (June 2026)**: Knowledge Graph extraction and validation tools
- **v1.0 (July 2026)**: MiLM deployment toolkit
- **v1.1 (August 2026)**: MCP connector ecosystem
- **v1.2 (September 2026)**: Advanced analytics and reporting

## Support

- **Questions?** Open an issue or discussion
- **Bug report?** File an issue with reproduction steps
- **Want to contribute?** See [CONTRIBUTING.md](../CONTRIBUTING.md)

---

For the full SKI Framework specification, see [SKI Framework](https://skiframework.org)
