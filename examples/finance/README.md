# Finance Sector Example - SKI Framework

Complete example of SKI Framework deployment for Anti-Money Laundering (AML) and transaction monitoring in financial institutions.

## Overview

This example demonstrates how to:
- Extract AML compliance rules from regulations
- Validate rules with expert review
- Deploy MiLM for continuous transaction monitoring
- Generate verdicts for AML compliance
- Maintain immutable audit trail for regulatory examination

## Regulatory Framework

### Primary Regulations
- **Bank Secrecy Act (BSA)** — Transaction reporting and record-keeping requirements
- **Anti-Money Laundering Regulations (AML)** — Customer identification and suspicious activity reporting
- **FinCEN Guidance** — Financial Crimes Enforcement Network interpretations
- **Office of Foreign Assets Control (OFAC)** — Sanctions enforcement

### Key Compliance Areas

1. **Customer Identification Program (CIP)**
   - Verify customer identity before account opening
   - Obtain and maintain documentation
   - 30-day completion requirement
   - Beneficial ownership information

2. **Know Your Customer (KYC)**
   - Understand customer's normal transaction patterns
   - Identify customer's business and occupation
   - Enhanced Due Diligence (EDD) for high-risk customers
   - Politically Exposed Persons (PEP) screening

3. **Transaction Monitoring**
   - Suspicious Activity Reports (SAR) filing
   - Large transaction reporting (CTR - Currency Transaction Report)
   - Wire transfer documentation
   - Threshold-based alerting

4. **Sanctions Compliance**
   - OFAC SDN (Specially Designated Nationals) list screening
   - Blocked funds handling
   - Ongoing transaction monitoring for sanctions

## Knowledge Graph Structure

The finance sector Knowledge Graph includes:
- **30+ compliance rules** organized by topic
- **Explicit mappings** to regulatory citations
- **Risk-based thresholds** for transaction monitoring
- **Escalation procedures** for suspicious activities

### Rule Categories

```
Finance Sector Rules
├── Customer Identification (8 rules)
├── KYC & Enhanced Due Diligence (6 rules)
├── Transaction Monitoring (10 rules)
├── Reporting Obligations (8 rules)
└── Sanctions Compliance (6 rules)
```

## Example Files

### Knowledge Graph
- **kg-finance-full.json** — Complete Knowledge Graph with all rules
- **kg-finance-sample.json** — Simplified version for testing

### Telemetry
- **sample-aml-alerts.jsonl** — Sample AML alert data
- **sample-transactions.jsonl** — Sample transaction monitoring data
- **sample-customer-data.jsonl** — Sample customer risk assessment data

### Documentation
- **rules-explained.md** — Explanation of each rule

## Quick Start

### 1. Review the Knowledge Graph

```bash
cat knowledge-graphs/kg-finance-sample.json | jq '.rules[0:5]'
```

### 2. Validate the Knowledge Graph

```bash
python3 ../../scripts/test-kg.py knowledge-graphs/kg-finance-full.json
```

### 3. Load into Deployment

```bash
# Copy to reference implementation
cp knowledge-graphs/kg-finance-full.json ../reference-implementation/examples/knowledge-graphs/kg-finance.json

# Or use milm-deploy
milm-deploy load-kg --kg knowledge-graphs/kg-finance-full.json
```

### 4. Test with Sample Data

```bash
# Test with AML alert data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-aml-alerts.jsonl \
  --output results/aml-verdicts.json

# Test with transaction monitoring data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-transactions.jsonl \
  --output results/transaction-verdicts.json
```

### 5. Review Results

```bash
cat results/aml-verdicts.json | jq '.verdict_counts'
```

## Rules Overview

### Customer Identification

**Rule: CIP Verification Timeline**
- Subject: Customer identification verification
- Relation: must_be_completed_within
- Object: 30 days of account opening
- Source: 31 CFR 1022.210
- Status: EXPLICIT

**Rule: PEP Enhanced Due Diligence**
- Subject: Politically Exposed Person account
- Relation: must_apply_enhanced_due_diligence_to
- Object: All PEP accounts
- Source: OFAC Guidance
- Status: EXPLICIT

### Transaction Monitoring

**Rule: Suspicious Activity Threshold**
- Subject: Transaction amount
- Relation: must_trigger_SAR_if_exceeds
- Object: $10,000 without clear business purpose
- Source: 31 CFR 1020.320
- Status: EXPLICIT

**Rule: SAR Filing Deadline**
- Subject: Suspicious activity detection
- Relation: must_be_reported_within
- Object: 30 days of detection
- Source: 31 CFR 1020.320(b)
- Status: EXPLICIT

**Rule: Wire Transfer Information**
- Subject: Wire transfer over $3,000
- Relation: must_include
- Object: Full originator and beneficiary information
- Source: 31 CFR 1010.410
- Status: EXPLICIT

## Verdict Examples

### CLEAR Verdict
Telemetry: Customer transaction $5,000 with documented business purpose
→ Below $10,000 SAR threshold
→ **CLEAR**

### FLAG Verdict
Telemetry: Customer transaction $15,000 with unclear business purpose
→ Exceeds $10,000 threshold without clear purpose
→ **FLAG** (SAR required)

### NULL Verdict
Telemetry: Transaction with missing customer information
→ Cannot evaluate CIP compliance without data
→ **NULL** (Data unavailable)

### DISCRETIONARY Verdict
Telemetry: Customer transaction $9,500, pattern suggests structuring
→ Below threshold but suspicious pattern
→ May require enhanced review
→ **DISCRETIONARY** (Human judgment needed)

## Customization Guide

### Using Your Own AML Policies

1. **Extract rules** from your compliance manual
   ```bash
   kg-extractor extract --file your-aml-policy.pdf --sector finance
   ```

2. **Validate extracted rules**
   ```bash
   kg-validator validate --input extracted.json --output validated.json
   ```

3. **Review and approve**
   - Open validated.json in editor
   - Verify against regulatory source documents
   - Add your organization's risk appetite

4. **Deploy**
   ```bash
   milm-deploy load-kg --kg your-kg.json
   ```

### Adding Custom Rules

Edit `knowledge-graphs/kg-finance-full.json`:

```json
{
  "id": "custom_f001",
  "subject": "Your customer type",
  "relation": "must_comply_with",
  "object": "Your specific requirement",
  "source_document": "Your regulatory source",
  "source_clause": "Section X.X",
  "confidence": "EXPLICIT",
  "reasoning": "Explain why this rule matters for your organization..."
}
```

## Testing Scenarios

### Scenario 1: Normal Customer Activity
- Transactions within expected patterns
- Clear business purpose documented
- CIP verification completed
→ Expected verdict: Mostly CLEAR

### Scenario 2: Suspicious Transaction Pattern
- Multiple transactions near threshold
- Unusual velocity for customer type
- Missing documentation
→ Expected verdict: Mix of FLAG and DISCRETIONARY

### Scenario 3: High-Risk Customer
- PEP designation
- Sanctions list match
- Complex beneficial ownership
→ Expected verdict: FLAG (Enhanced review required)

### Scenario 4: Missing Information
- Incomplete customer records
- No business purpose documentation
- CIP verification pending
→ Expected verdict: NULL verdicts

## Compliance Reporting

Generate AML compliance summary:

```bash
python3 ../../scripts/generate-report.py \
  --ledger data/ledger.db \
  --start-date 2026-01-01 \
  --end-date 2026-05-31 \
  --output aml-compliance-report.html
```

Report includes:
- SAR filing summary (count, dates, amounts)
- Customer risk profile distributions
- Transaction monitoring metrics
- CIP completion status
- Audit trail verification
- Regulatory filing support

## Production Deployment Checklist

- [ ] Review all rules against current AML regulations
- [ ] Customize rules for your customer base
- [ ] Integrate with your customer database
- [ ] Set up transaction monitoring data feeds
- [ ] Configure SAR workflow integration
- [ ] Test with historical suspicious transactions
- [ ] Validate verdicts match compliance team's assessment
- [ ] Enable audit ledger backup
- [ ] Train compliance staff on verdict interpretation
- [ ] Document SAR escalation procedures
- [ ] Schedule quarterly AML policy review

## Support & Extensions

### Common Customizations
- Add customer risk tiers (standard, enhanced, high-risk)
- Include geographic risk factors
- Integrate with sanctions screening systems
- Connect to transaction amount thresholds
- Customize PEP verification procedures

### Integration Examples
- Connect to core banking system for customer data
- Integrate with transaction settlement systems
- Link to OFAC screening tools
- Connect to SAR filing systems
- Link to compliance dashboards

## References

### Regulatory Documents
- [Bank Secrecy Act](https://www.fincen.gov/about/what-we-do)
- [31 CFR 1020 - BSA Regulations](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1020/)
- [31 CFR 1022 - CIP Rule](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1022/)

### Regulatory Guidance
- [FinCEN Guidance](https://www.fincen.gov/)
- [OFAC Compliance](https://home.treasury.gov/faq/sanctions-faqs-general)

### Industry Resources
- [ABA AML Compliance Resources](https://www.aba.com/)
- [Wolfsberg Group Guidance](https://www.wolfsberggroup.org/)

## Questions?

- Review individual rule documentation
- Check regulation citations
- Contact your compliance officer for policy questions
- Open an issue on GitHub

---

**Note:** This example uses simplified, anonymized data for educational purposes. For production use, work with compliance experts and legal counsel to ensure accuracy and regulatory alignment.
