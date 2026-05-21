# Getting Started with SKI Framework

Welcome to the SKI Framework! This guide will help you understand the core concepts and get started with your first implementation.

## What is SKI?

SKI (Sovereign Knowledge Intelligence) is an open-source framework for **deterministic AI compliance monitoring** in regulated industries.

Key concepts:
- **Deterministic**: Same input always produces the same verdict
- **Sovereign**: Your data stays on your infrastructure
- **Auditable**: Every verdict traces back to a specific regulation
- **Open**: Published under CC BY 4.0; free to implement

## Before You Start

To implement SKI, you should have:

1. **Understanding of your regulatory obligations**
   - What regulations apply to your organization?
   - What compliance requirements must you monitor?
   - What operational telemetry do you generate?

2. **Infrastructure requirements**
   - On-premise compute (Linux/macOS recommended)
   - Access to operational data streams
   - Ability to deploy containers (Docker/Kubernetes)

3. **Team composition**
   - **Compliance expert**: Understands regulations and requirements
   - **Infrastructure engineer**: Manages deployment and monitoring
   - **Operations lead**: Ensures governance and escalation processes

## The SKI Implementation Journey

SKI implementations follow four phases:

### Phase 1: Discovery & Compilation (4-6 weeks)
- Identify regulatory obligations to monitor
- Extract compliance rules into Knowledge Graph
- Validate extracted rules with domain experts
- Establish Coverage Register (what's covered, what's not)

### Phase 2: Infrastructure & Integration (3-4 weeks)
- Deploy MiLM (inference engine) on-premise
- Connect to operational data sources (read-only sidecar)
- Set up immutable audit ledger
- Validate security and sovereignty

### Phase 3: Shadow Validation (8-12 weeks)
- Run SKI in parallel with existing compliance processes
- Compare SKI verdicts to manual reviews
- Identify and resolve DISCRETIONARY verdicts
- Build confidence in system accuracy

### Phase 4: Active Governance (ongoing)
- Activate SKI verdicts in formal compliance processes
- Establish escalation procedures for FLAGS and DISCRETIONARY verdicts
- Perform quarterly reviews
- Manage regulatory changes

## Key Concepts

### Knowledge Graph
A structured representation of your compliance obligations:
- **Extracted from**: Regulatory documents, internal SOPs
- **Validated by**: Compliance experts
- **Used for**: Evaluating operational telemetry
- **Owned by**: Your organization

### MiLM (Micro Language Model)
The inference engine that runs on your infrastructure:
- Operates at temperature zero (deterministic)
- Evaluates telemetry against Knowledge Graph
- Produces categorical verdicts (CLEAR, FLAG, NULL, DISCRETIONARY)
- Never sends data outside your boundary

### Verdicts
SKI produces exactly four verdict types:

| Verdict | Meaning | Example |
|---------|---------|---------|
| **CLEAR** | Compliant; no issue detected | Emissions within regulatory limit |
| **FLAG** | Non-compliant; breach detected | Emissions exceed limit |
| **NULL** | No data to evaluate | Data stream offline |
| **DISCRETIONARY** | Ambiguous; requires human judgment | Gray area in regulation |

### Audit Ledger
An immutable record of all verdicts:
- Hash-chained (tamper-evident)
- Includes: timestamp, verdict, rule, telemetry reference
- Retained for regulatory period
- Produces audit-grade evidence

## Next Steps

### For Framework Understanding
Read the [full SKI Framework specification](https://skiframework.org)

### For Implementation Planning
1. Identify your regulatory obligations
2. Define your scope (which regulations, which processes)
3. Assess your current compliance processes
4. Plan your team and timeline

### For Technical Setup
See [ARCHITECTURE.md](./ARCHITECTURE.md) for technical architecture details

### For Professional Support
[KpiFinity provides three tiers of implementation support](https://kpifinity.com):
- **Tier 1 Foundational**: Single regulatory domain, 8-12 weeks
- **Tier 2 Managed**: Multi-domain expansion, 16-24 weeks  
- **Tier 3 Assured**: Enterprise deployment with audit, 24-40 weeks

## Common Questions

**Q: Do we need to move to the cloud?**
No. SKI is designed to run entirely on-premise. Data never leaves your infrastructure.

**Q: How long does implementation take?**
4-6 months typically (all four phases). This includes time for regulatory experts to validate rules.

**Q: Can we start with just one regulatory domain?**
Yes! Start narrow, prove success, then expand. This is the recommended approach.

**Q: What if our regulation is ambiguous?**
SKI produces DISCRETIONARY verdicts for ambiguous cases. These escalate to human experts for decision.

**Q: Who owns the Knowledge Graph?**
Your organization owns and maintains the Knowledge Graph. It lives on your infrastructure.

## Getting Help

- **Framework questions**: [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions)
- **Bug reports**: [GitHub Issues](https://github.com/kpifinity/ski-framework/issues)
- **Implementation help**: [KpiFinity](https://kpifinity.com)
- **Technical details**: [Full SKI Framework specification](https://skiframework.org)

---

Ready? Start with the [ARCHITECTURE.md](./ARCHITECTURE.md) guide or contact KpiFinity for implementation support.
