# SKI Framework Examples

This directory contains **reference implementations and examples** showing how to deploy and use the SKI Framework in specific industries and regulatory contexts.

## What Goes Here

Examples for:
- **Sector-specific deployments** — Energy, Finance, Manufacturing, Defense
- **Regulatory contexts** — Different jurisdictions and requirements
- **Use case scenarios** — Common compliance monitoring patterns
- **Integration examples** — How to connect to operational systems
- **Knowledge Graph examples** — Sample rules and structures

## Current Examples

*Coming in v1.0 (July 2026)*

- `energy/` — Environmental compliance monitoring for oil & gas operations
- `finance/` — Transaction monitoring and AML screening for financial institutions
- `manufacturing/` — Safety and environmental compliance for industrial manufacturing
- `defense/` — Security and procurement compliance for defense contractors

## Example Structure

Each example folder contains:

```
sector-name/
├── README.md                           (Overview and context)
├── REGULATIONS.md                      (Regulatory background)
├── knowledge-graph/
│   ├── kg-v1.json                     (Sample Knowledge Graph)
│   ├── rules.md                       (Rules explanation)
│   └── validation-notes.md            (Validation findings)
├── telemetry/
│   ├── sample-data.json               (Sample operational data)
│   ├── schema.md                      (Telemetry format)
│   └── integration-guide.md           (How to connect)
├── deployment/
│   ├── docker-compose.yml             (Local deployment)
│   ├── infrastructure-notes.md        (Infrastructure requirements)
│   └── deployment-walkthrough.md      (Step-by-step guide)
└── results/
    ├── sample-verdicts.json           (Example verdicts)
    └── audit-ledger-sample.json       (Sample audit entries)
```

## Using an Example

### 1. Read the Overview
Start with `README.md` to understand the context and regulatory background.

### 2. Review the Knowledge Graph
Look at `knowledge-graph/` to see how compliance rules are structured.

### 3. Examine Sample Data
Check `telemetry/` to understand operational data format.

### 4. Deploy Locally
Follow `deployment/` guide to run the example on your computer.

### 5. Review Results
Look at `results/` to see sample verdicts and audit ledger entries.

## Example: Energy Sector

The energy example shows:

**Regulatory Context:**
- Environmental discharge limits (SOX, etc.)
- Emissions reporting requirements
- Production threshold monitoring
- Emergency response triggers

**Knowledge Graph:**
- Rules for volume limits
- Thresholds for different contaminants
- Reporting obligations
- Escalation criteria

**Telemetry:**
- Continuous flow measurements
- Discharge volume data
- Quality monitoring readings
- Event logs

**Verdicts:**
- CLEAR when within limits
- FLAG when violations detected
- NULL when data missing
- DISCRETIONARY when ambiguous

## Contributing an Example

To add a new sector/jurisdiction example:

1. Create a folder in `examples/` with sector name
2. Follow the structure above
3. Include realistic (anonymized) sample data
4. Document regulatory context clearly
5. Provide deployment instructions
6. Include expected results

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

## Example Use Cases

### Compliance Officer
"How do we set up SKI for our environmental monitoring?"
→ Start with the energy example

### System Architect
"How should we integrate with our operational telemetry?"
→ Look at telemetry/ and deployment/ sections

### Auditor
"What does SKI's audit trail look like?"
→ Review the audit-ledger samples

### Developer
"How do I build tools for Knowledge Graph extraction?"
→ Study the knowledge-graph structure and rules

## FAQ

**Q: Can I use these examples in production?**
No, examples are for learning only. They use sample/anonymized data and simplified Knowledge Graphs. For production deployment, work with KpiFinity.

**Q: Where do I start if I'm implementing SKI?**
1. Read the [Getting Started Guide](../docs/GETTING_STARTED.md)
2. Pick the example closest to your industry
3. Review how they structured their Knowledge Graph
4. Follow the deployment walkthrough

**Q: Are the regulations in the examples current?**
Examples are illustrative only. Verify all regulatory requirements with current regulatory documents and legal counsel.

**Q: Can I modify these examples for my organization?**
Yes! The examples are CC BY 4.0 licensed. You can adapt them for your context. Just maintain attribution.

## Roadmap

- **v1.0 (July 2026)**: Energy and Finance examples
- **v1.1 (August 2026)**: Manufacturing example
- **v1.2 (September 2026)**: Defense/Critical Infrastructure example
- **v1.3 (October 2026)**: Additional jurisdictions (EU, APAC, Canada)

## Support

- **Question about an example?** Open an issue
- **Want to add an example?** See [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Need production implementation?** Contact [KpiFinity](https://kpifinity.com)

---

For sector-specific Knowledge Graph libraries and implementation support, see [KpiFinity Services](https://kpifinity.com)
