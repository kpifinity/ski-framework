# Defense Sector Example - SKI Framework

Complete example of SKI Framework deployment for defense contracting compliance, security requirements, and controlled information protection.

## Overview

This example demonstrates how to:
- Extract defense contractor compliance rules from regulations
- Validate rules with security expert review
- Deploy MiLM for continuous security monitoring
- Generate verdicts for DFARS/CMMC compliance
- Maintain immutable audit trail for government audits

## Regulatory Framework

### Primary Regulations
- **Defense Federal Acquisition Regulation Supplement (DFARS)** — Department of Defense contracting requirements
- **Cybersecurity Maturity Model Certification (CMMC)** — Cybersecurity standards for contractors
- **NIST Special Publication 800-171** — Security controls for Controlled Unclassified Information (CUI)
- **NIST Special Publication 800-172** — Enhanced security requirements for high-risk CUI

### Key Compliance Areas

1. **Controlled Unclassified Information (CUI) Protection**
   - CUI identification and marking
   - Access control and accountability
   - Encryption requirements (data at rest and in transit)
   - Incident response and reporting (72-hour requirement)

2. **Cybersecurity Maturity (CMMC)**
   - CMMC Level 1: Basic cyber hygiene (foundational practices)
   - CMMC Level 2: Intermediate security (documented processes)
   - CMMC Level 3: Advanced/Expert security (proactive threat detection)
   - Assessment and certification requirements

3. **Access Control & User Management**
   - User identification and authentication
   - Annual access control reviews
   - Privileged access management
   - Account management documentation

4. **Incident Response & Reporting**
   - Security incident identification
   - 72-hour reporting to government
   - Incident documentation
   - Root cause analysis

## Knowledge Graph Structure

The defense sector Knowledge Graph includes:
- **40+ compliance rules** organized by topic
- **Explicit mappings** to DFARS clauses and NIST controls
- **Government reporting requirements**
- **Assessment and certification procedures**

### Rule Categories

```
Defense Sector Rules
├── CUI Protection (10 rules)
├── Access Control (8 rules)
├── Cybersecurity Maturity (10 rules)
├── Incident Response (8 rules)
└── Assessment & Certification (6 rules)
```

## Example Files

### Knowledge Graph
- **kg-defense-full.json** — Complete Knowledge Graph with all rules
- **kg-defense-sample.json** — Simplified version for testing

### Telemetry
- **sample-access-logs.jsonl** — Sample access control data
- **sample-security-incidents.jsonl** — Sample incident data
- **sample-cmmc-assessment.jsonl** — Sample assessment results

### Documentation
- **rules-explained.md** — Explanation of each rule

## Quick Start

### 1. Review the Knowledge Graph

```bash
cat knowledge-graphs/kg-defense-sample.json | jq '.rules[0:5]'
```

### 2. Validate the Knowledge Graph

```bash
python3 ../../scripts/test-kg.py knowledge-graphs/kg-defense-full.json
```

### 3. Load into Deployment

```bash
# Copy to reference implementation
cp knowledge-graphs/kg-defense-full.json ../reference-implementation/examples/knowledge-graphs/kg-defense.json

# Or use milm-deploy
milm-deploy load-kg --kg knowledge-graphs/kg-defense-full.json
```

### 4. Test with Sample Data

```bash
# Test with access control data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-access-logs.jsonl \
  --output results/access-verdicts.json

# Test with security incident data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-security-incidents.jsonl \
  --output results/incident-verdicts.json
```

### 5. Review Results

```bash
cat results/access-verdicts.json | jq '.verdict_counts'
```

## Rules Overview

### CUI Protection

**Rule: CUI Compliance with NIST 800-171**
- Subject: Controlled unclassified information
- Relation: must_comply_with
- Object: NIST SP 800-171 security controls
- Source: DFARS Clause 252.204-7012
- Status: EXPLICIT

**Rule: Incident Reporting Timeline**
- Subject: Security incident involving CUI
- Relation: must_be_reported_within
- Object: 72 hours of discovery
- Source: DFARS Clause 252.204-7012
- Status: EXPLICIT

### Access Control

**Rule: Annual Access Control Review**
- Subject: System access by users
- Relation: must_be_reviewed_annually
- Object: At least once per calendar year
- Source: NIST SP 800-171 (AC-2)
- Status: EXPLICIT

### Cybersecurity Maturity

**Rule: CMMC Certification Level**
- Subject: Defense contractor
- Relation: must_achieve_minimum
- Object: CMMC Level required by contract
- Source: DFARS Rule 2019-4 (Updated)
- Status: EXPLICIT

## Verdict Examples

### CLEAR Verdict
Telemetry: CUI properly marked and encrypted, user access audited annually
→ Complies with NIST 800-171 and CMMC requirements
→ **CLEAR**

### FLAG Verdict
Telemetry: Security incident discovered, 5 days without government notification
→ Violates 72-hour reporting requirement
→ **FLAG** (Immediate escalation to government required)

### NULL Verdict
Telemetry: CUI access log missing
→ Cannot verify access control compliance
→ **NULL** (Data unavailable)

### DISCRETIONARY Verdict
Telemetry: Access control review completed 14 months after prior review
→ Technically late but within reasonable tolerance
→ May require management review
→ **DISCRETIONARY** (Chief Information Security Officer judgment)

## Customization Guide

### Using Your Own Security Policies

1. **Extract rules** from your security documentation
   ```bash
   kg-extractor extract --file your-security-policy.pdf --sector defense
   ```

2. **Validate extracted rules**
   ```bash
   kg-validator validate --input extracted.json --output validated.json
   ```

3. **Review and approve**
   - Open validated.json in editor
   - Verify against DFARS and NIST requirements
   - Add your organization's enhanced controls

4. **Deploy**
   ```bash
   milm-deploy load-kg --kg your-kg.json
   ```

### Adding Custom Rules

Edit `knowledge-graphs/kg-defense-full.json`:

```json
{
  "id": "custom_d001",
  "subject": "Your system or process",
  "relation": "must_comply_with",
  "object": "Your specific security requirement",
  "source_document": "Your policy or standard",
  "source_clause": "Section X.X",
  "confidence": "EXPLICIT",
  "reasoning": "Explain the compliance requirement..."
}
```

## Testing Scenarios

### Scenario 1: Compliant Contractor
- All CUI properly protected
- Access controls documented and reviewed
- Incidents reported on time
- CMMC certification current
→ Expected verdict: Mostly CLEAR

### Scenario 2: Security Incident
- CUI exposure detected
- Incident not reported within 72 hours
- Root cause analysis incomplete
→ Expected verdict: FLAG

### Scenario 3: Compliance Gap
- Missing access control documentation
- Overdue annual review
- Encryption not implemented
→ Expected verdict: Mix of FLAG and DISCRETIONARY

### Scenario 4: Audit Preparation
- Some systems lack full documentation
- Recent security improvements made
- Assessment in progress
→ Expected verdict: Mix of CLEAR and DISCRETIONARY

## Compliance Reporting

Generate defense contractor compliance summary:

```bash
python3 ../../scripts/generate-report.py \
  --ledger data/ledger.db \
  --start-date 2026-01-01 \
  --end-date 2026-05-31 \
  --output defense-compliance-report.html
```

Report includes:
- CMMC readiness assessment
- CUI protection compliance
- Access control audit status
- Incident response metrics
- NIST 800-171 control compliance
- Government reporting verification
- Audit trail for government audits

## Production Deployment Checklist

- [ ] Review all rules against DFARS and NIST standards
- [ ] Customize rules for your contract requirements
- [ ] Integrate with your security monitoring systems
- [ ] Set up access control monitoring
- [ ] Configure incident detection and alerting
- [ ] Test with historical incident scenarios
- [ ] Validate verdicts match your security team's assessment
- [ ] Enable audit ledger backup for government audits
- [ ] Train security staff on verdict interpretation
- [ ] Document incident escalation procedures
- [ ] Schedule quarterly CMMC readiness assessment
- [ ] Coordinate with government security representative

## Support & Extensions

### Common Customizations
- Add contract-specific CMMC levels
- Include facility security requirements
- Integrate with facility access control systems
- Connect to network security monitoring
- Custom incident severity classifications

### Integration Examples
- Connect to identity and access management (IAM) systems
- Integrate with security information and event management (SIEM)
- Link to CUI management systems
- Connect to incident response platforms
- Link to compliance dashboards

## References

### Regulatory Documents
- [DFARS - Defense Acquisition Regulations](https://www.acquisition.gov/dfars)
- [DFARS Clause 252.204-7012 - Safeguarding CUI](https://www.acquisition.gov/dfars/252-204-7012-safeguarding-controlled-unclassified-information)
- [CMMC Model](https://dodcio.defense.gov/cmmc/)

### Standards & Guidance
- [NIST SP 800-171 - Security Requirements](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r3.pdf)
- [NIST SP 800-172 - Enhanced Security Requirements](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-172.pdf)

### Resources
- [CMMC Certification](https://dodcio.defense.gov/cmmc-certification-bodies/)
- [CUI Registry](https://www.archives.gov/cui)

## Questions?

- Review individual rule documentation
- Check DFARS and NIST regulatory sources
- Contact your Contracting Officer for policy questions
- Consult with your CMMC C3PAO for assessment guidance
- Open an issue on GitHub

---

**Note:** This example uses simplified data for educational purposes. For production use, work with your security team, legal counsel, and government representatives to ensure full compliance with all applicable regulations and contract requirements.
