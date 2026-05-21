# SKI Framework

> **Sovereign Knowledge Intelligence** — An open architecture for deterministic AI compliance monitoring in regulated industries.

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![Version](https://img.shields.io/badge/Version-2.1-blue.svg)](https://skiframework.org)
[![Status](https://img.shields.io/badge/Status-Open%20Specification-green.svg)](https://skiframework.org)

## What is SKI?

SKI is an open-source framework that enables **real-time, deterministic, auditable AI compliance monitoring** in environments where regulatory requirements, operational risk, and audit defensibility are non-negotiable.

Unlike general-purpose AI systems, SKI is purpose-built to solve a specific problem: regulated industries (energy, finance, manufacturing, defense) cannot adopt AI in core operational systems because existing solutions don't satisfy four non-negotiable requirements:

1. **Determinism** — Same input always produces the same verdict, every time
2. **Sovereignty** — Operational data never leaves the organization's infrastructure
3. **Auditability** — Every verdict traces directly to a specific regulation
4. **Human Primacy** — AI supports human judgment, never replaces it

SKI solves all four through a two-phase architecture: offline Knowledge Graph compilation (probabilistic) + runtime evaluation (deterministic, deterministic, and air-gap capable).

---

## The Problem SKI Solves

Regulated industries generate continuous operational telemetry: emissions readings, transaction flows, equipment performance, compliance measurements. They're required to verify compliance against complex regulatory obligations **in real-time, continuously, with full audit trails**.

Today, this happens through:
- ❌ Manual review and spreadsheet tracking (incomplete, slow, error-prone)
- ❌ Traditional rules engines (static, require IT updates, can't keep pace with regulation)
- ❌ General-purpose AI (probabilistic, can't send data to cloud, creates audit liability)

**SKI fills this gap**: Real-time compliance monitoring that is deterministic, sovereign, auditable, and legally defensible.

---

## Key Features

✅ **Deterministic verdicts** — Identical inputs produce identical verdicts; no probabilistic scoring  
✅ **Data sovereignty** — All evaluation occurs on-premise; operational data never leaves your infrastructure  
✅ **Full auditability** — Every verdict traces to a specific Knowledge Graph rule and a specific regulatory clause  
✅ **Passive monitoring** — Sidecar architecture; doesn't modify operational systems  
✅ **Automated compliance** — Real-time evaluation against regulatory obligations  
✅ **Regulatory defensibility** — Immutable audit ledger with full chain of custody  

---

## Architecture at a Glance

SKI operates in two phases, separated by a security boundary:

### Phase 1: Offline Compilation (Outside sovereign boundary)
- Regulatory documents → Knowledge Graph (LLM-assisted extraction + human validation)
- Produces signed, versioned Knowledge Graph

### Phase 2: Runtime Evaluation (Inside sovereign boundary)
- Operational telemetry → MiLM inference against Knowledge Graph
- Produces categorical verdicts (CLEAR, FLAG, NULL, DISCRETIONARY)
- All verdicts written to immutable audit ledger

**Result**: Real-time compliance intelligence with full regulatory defensibility.

See the [full framework specification](https://skiframework.org) for detailed architecture, axioms, pillars, and implementation requirements.

---

## Quick Start

### Prerequisites
- Linux/macOS or Windows with Docker
- Python 3.9+
- Basic understanding of your regulatory obligations

### Installation

```bash
# Clone the repository
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework

# Install dependencies
pip install -r requirements.txt

# Run the SKI reference implementation
docker-compose up -d
```

*(Reference implementation coming in v1.0-RC1; for now, see the [Getting Started Guide](https://skiframework.org/implementation) on skiframework.org)*

---

## Documentation

### Framework Specification
**→ [Read the full SKI Framework specification](https://skiframework.org)**

This is the authoritative source for:
- Three axioms and three pillars
- Knowledge Graph requirements
- MiLM selection and configuration
- Data integration requirements
- System integrity and audit ledger specifications
- Implementation phases and validation requirements
- Governance and conformance levels

### Implementation Guide
**→ [SKI Implementation Documentation](https://skiframework.org/implementation)**

- Phase-by-phase deployment playbooks
- Knowledge Graph extraction and validation
- MiLM deployment and configuration
- Infrastructure setup and hardening
- Shadow validation and governance setup

### For Professional Support
**→ [KpiFinity Implementation Services](https://kpifinity.com)**

- Tier 1 Foundational: Single-domain SKI deployments
- Tier 2 Managed: Multi-domain expansion and governance
- Tier 3 Assured: Enterprise deployment with third-party audit

---

## Verdicts

SKI produces exactly four verdict types. No scores, no confidence intervals, no probabilistic ranges.

| Verdict | Meaning | Action |
|---------|---------|--------|
| **CLEAR** | All applicable rules evaluated; no compliance issue detected | Normal operation; logged to audit ledger |
| **FLAG** | A compliance rule has been breached | Escalate to designated human reviewer; create incident |
| **NULL** | Insufficient data to evaluate; coverage gap logged | Human review required; documented in Coverage Register |
| **DISCRETIONARY** | Rule applies but requires qualified human judgment to resolve | Route to compliance expert for decision |

---

## Components

### Framework (Open Source)
- ✅ Two-phase architecture specification
- ✅ Knowledge Graph schema and requirements
- ✅ MiLM configuration and constraints
- ✅ Data integration and sidecar patterns
- ✅ Audit ledger specification
- ✅ Governance and conformance requirements

### Tools (Open Source)
- 🔄 Knowledge Graph extraction pipeline *(in development)*
- 🔄 Human validation framework *(in development)*
- 🔄 MiLM deployment toolkit *(in development)*
- 🔄 Audit ledger backend *(in development)*
- 🔄 MCP integration framework *(in development)*

### Knowledge Graph Libraries (Proprietary)
- 📚 Energy sector (environmental discharge, emissions, production thresholds)
- 📚 Institutional Finance (transaction monitoring, AML, capital adequacy)
- 📚 Manufacturing (safety, environmental, equipment compliance)
- 📚 Defense & Critical Infrastructure (specialized compliance domains)

*(Contact KpiFinity for library licensing and professional services)*

---

## Implementation Maturity Levels

SKI defines three conformance levels that support progressive adoption:

### Level 1: Foundational
Single regulatory domain, essential governance. Typical deployment: 8-12 weeks, 1-2 person compliance team.

### Level 2: Managed
Multi-domain deployment, formal governance processes, quarterly reviews. Typical: 16-24 weeks, larger compliance teams.

### Level 3: Assured
Enterprise-wide deployment, third-party audit preparation, strategic advisory. Typical: 24-40 weeks, full governance infrastructure.

**→ [Learn more about maturity levels](https://skiframework.org/conformance)**

---

## The Business Model

**SKI is an open-source framework** published under CC BY 4.0. You're free to read, implement, and adapt it.

**KpiFinity provides three layers on top of the framework:**

1. **Pre-built Knowledge Graph libraries** — Sector-specific rule sets (energy, finance, manufacturing, defense) validated by domain experts
2. **Certified MCP connectors** — Pre-built integrations to operational data sources (Maximo, PI System, SAP, etc.)
3. **Implementation methodology** — Professional services to deploy SKI, train your team, and establish governance

→ [Learn more about KpiFinity services](https://kpifinity.com)

---

## Contributing

We welcome contributions to the SKI Framework reference implementation, tooling, and documentation.

### Ways to Contribute
- Report issues or suggest improvements via [GitHub Issues](https://github.com/kpifinity/ski-framework/issues)
- Submit documentation improvements or examples
- Develop MCP connectors for new data sources
- Participate in the [SKI Framework community discussions](https://github.com/kpifinity/ski-framework/discussions)

### Development Setup
```bash
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework
pip install -r requirements-dev.txt
python -m pytest
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines.

---

## License

The SKI Framework specification and all open-source components are published under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.

You are free to:
- ✅ Use, share, and adapt the framework
- ✅ Use it for commercial purposes
- ✅ Modify it for your needs

Provided you:
- ✅ Give attribution to KpiFinity Inc. and skiframework.org

→ [Read the full license](https://creativecommons.org/licenses/by/4.0/)

---

## Support & Community

- **Framework questions**: [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions)
- **Bug reports**: [GitHub Issues](https://github.com/kpifinity/ski-framework/issues)
- **Full specification**: [skiframework.org](https://skiframework.org)
- **Professional implementation**: [kpifinity.com](https://kpifinity.com)
- **Contact**: hello@kpifinity.com

---

## Roadmap

### v2.1 (Current — May 2026)
- ✅ Framework specification complete and published
- ✅ Architecture documentation with sector examples
- ✅ Reference implementation (coming June 2026)
- 🔄 Knowledge Graph extraction tools (June 2026)
- 🔄 Human validation framework (July 2026)

### v2.2 (Q3 2026)
- 🔄 Regulatory crosswalks (energy, finance, manufacturing, defense)
- 🔄 MCP connector ecosystem launch
- 🔄 Audit ledger reference implementation
- 🔄 Deployment automation (Terraform, Docker)

### v3.0 (2027)
- 🔄 Advanced analytics and intelligence features
- 🔄 Multi-jurisdictional compliance mapping
- 🔄 Managed service offering (optional)

---

## Citation

If you use or reference the SKI Framework in academic or professional work, please cite:

```
KpiFinity Inc. (2026). SKI Framework: Sovereign Knowledge Intelligence.
Retrieved from https://skiframework.org
Published under Creative Commons Attribution 4.0 International License.
```

---

## About KpiFinity

KpiFinity Inc. is a Calgary-based technology and consulting firm specializing in AI governance and compliance automation for regulated industries.

We work with energy, financial services, manufacturing, and defense organizations to build compliance intelligence systems that are deterministic, sovereign, and audit-defensible.

→ [Learn more about KpiFinity](https://kpifinity.com)

---

**Questions?** Start with the [SKI Framework specification](https://skiframework.org) or reach out to hello@kpifinity.com.

