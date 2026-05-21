# Energy Sector Example - SKI Framework

Complete example of SKI Framework deployment for environmental compliance monitoring in oil & gas operations.

## Overview

This example demonstrates how to:
- Extract environmental compliance rules from regulations
- Validate rules with expert review
- Deploy MiLM for continuous monitoring
- Generate verdicts for operational compliance
- Maintain immutable audit trail

## Regulatory Framework

### Primary Regulations
- **Clean Air Act (CAA)** — Emissions limits and monitoring
- **Clean Water Act (CWA)** — Discharge standards and water quality
- **Resource Conservation and Recovery Act (RCRA)** — Hazardous waste management
- **State Environmental Regulations** — Additional jurisdiction-specific rules

### Key Compliance Areas

1. **Air Quality**
   - Sulfur dioxide (SO₂) emissions limits
   - Nitrogen oxide (NOₓ) emissions limits
   - Particulate matter (PM) limits
   - Volatile organic compounds (VOC) limits

2. **Water Quality**
   - Wastewater discharge pH levels
   - Temperature limits
   - Chemical contamination thresholds
   - Oil and grease limits

3. **Reporting Requirements**
   - Monthly compliance reports
   - Quarterly emissions data
   - Annual certifications
   - Incident notifications (24-hour)

4. **Monitoring & Equipment**
   - Continuous emission monitoring systems (CEMS)
   - Calibration requirements
   - Maintenance schedules
   - Data quality assurance

## Knowledge Graph Structure

The energy sector Knowledge Graph includes:
- **50+ compliance rules** organized by topic
- **Explicit mappings** to specific regulations
- **Precedence rules** for handling conflicts
- **Effective dates** and expiration conditions

### Rule Categories

```
Energy Sector Rules
├── Air Quality (15 rules)
├── Water Quality (12 rules)
├── Waste Management (8 rules)
├── Reporting (10 rules)
└── Emergency Response (5 rules)
```

## Example Files

### Knowledge Graph
- **kg-energy-full.json** — Complete Knowledge Graph with all rules
- **kg-energy-sample.json** — Simplified version for testing

### Telemetry
- **sample-air-quality.jsonl** — Sample air monitoring data
- **sample-water-quality.jsonl** — Sample water monitoring data
- **sample-compliance-data.jsonl** — Mixed operational telemetry

### Documentation
- **REGULATIONS.md** — Detailed regulatory background
- **rules-explained.md** — Explanation of each rule

## Quick Start

### 1. Review the Knowledge Graph

```bash
cat knowledge-graphs/kg-energy-sample.json | jq '.rules[0:5]'
```

### 2. Validate the Knowledge Graph

```bash
python3 ../../scripts/test-kg.py knowledge-graphs/kg-energy-full.json
```

### 3. Load into Deployment

```bash
# Option A: Copy to reference implementation
cp knowledge-graphs/kg-energy-full.json ../reference-implementation/examples/knowledge-graphs/kg.json

# Option B: Use milm-deploy
milm-deploy load-kg --kg knowledge-graphs/kg-energy-full.json
```

### 4. Test with Sample Data

```bash
# Test with air quality data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-air-quality.jsonl \
  --output results/air-quality-verdicts.json

# Test with water quality data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-water-quality.jsonl \
  --output results/water-quality-verdicts.json
```

### 5. Review Results

```bash
cat results/air-quality-verdicts.json | jq '.verdict_counts'
```

## Rules Overview

### Air Quality Monitoring

**Rule: SO₂ Emissions Limit**
- Subject: Facility discharge
- Relation: must_not_exceed
- Object: 100 ppm sulfur dioxide
- Source: Clean Air Act § 112(b)(1)
- Status: EXPLICIT

**Rule: Continuous Monitoring Required**
- Subject: SO₂ emissions monitoring
- Relation: must_occur_every
- Object: 15 minutes
- Source: 40 CFR Part 60 Appendix B
- Status: EXPLICIT

### Water Quality Standards

**Rule: Discharge pH**
- Subject: Wastewater discharge
- Relation: must_be_between
- Object: 6.0 and 8.5 pH units
- Source: Clean Water Act § 303(d)
- Status: EXPLICIT

### Reporting Obligations

**Rule: Monthly Report Submission**
- Subject: Compliance documentation
- Relation: must_be_submitted_by
- Object: 15th of following month
- Source: 40 CFR Part 60.7
- Status: EXPLICIT

## Verdict Examples

### CLEAR Verdict
Telemetry: Facility SO₂ discharge 85 ppm
→ Within 100 ppm limit
→ **CLEAR**

### FLAG Verdict
Telemetry: Facility SO₂ discharge 125 ppm
→ Exceeds 100 ppm limit
→ **FLAG** (Breach detected)

### NULL Verdict
Telemetry: Equipment malfunction (no reading)
→ Cannot evaluate without data
→ **NULL** (Data unavailable)

### DISCRETIONARY Verdict
Telemetry: Facility pH 6.2 (ambiguous)
→ Within range but near boundary
→ May require human judgment
→ **DISCRETIONARY** (Expert review needed)

## Customization Guide

### Using Your Own Regulations

1. **Extract rules** from your regulatory documents
   ```bash
   kg-extractor extract --file your-regulation.pdf --sector energy
   ```

2. **Validate extracted rules**
   ```bash
   kg-validator validate --input extracted.json --output validated.json
   ```

3. **Review and approve**
   - Open validated.json in editor
   - Verify against source documents
   - Add your organization's policies

4. **Deploy**
   ```bash
   milm-deploy load-kg --kg your-kg.json
   ```

### Adding Custom Rules

Edit `knowledge-graphs/kg-energy-full.json`:

```json
{
  "id": "rule_custom_001",
  "subject": "Your facility type",
  "relation": "must_comply_with",
  "object": "Your specific requirement",
  "source_document": "Your regulation",
  "source_clause": "Section X.X",
  "confidence": "EXPLICIT",
  "reasoning": "Explain the rule..."
}
```

## Testing Scenarios

### Scenario 1: Normal Operation
All measurements within compliance ranges
→ Expected verdict: Mostly CLEAR

### Scenario 2: Exceeding Limits
Some measurements exceed thresholds
→ Expected verdict: Mix of CLEAR and FLAG

### Scenario 3: Missing Data
Equipment malfunction, no readings
→ Expected verdict: NULL verdicts

### Scenario 4: Edge Cases
Values at or near compliance boundaries
→ Expected verdict: Mix of CLEAR and DISCRETIONARY

## Compliance Reporting

Generate compliance summary:

```bash
python3 ../../scripts/generate-report.py \
  --ledger data/ledger.db \
  --start-date 2026-01-01 \
  --end-date 2026-05-31 \
  --output compliance-report.html
```

Report includes:
- Verdict summary (CLEAR/FLAG/NULL/DISCRETIONARY counts)
- Violations identified
- Remedial actions taken
- Audit trail verification
- Regulatory filing support

## Production Deployment Checklist

- [ ] Review all rules against current regulations
- [ ] Customize rules for your facilities
- [ ] Test with historical operational data
- [ ] Validate verdicts match your compliance team's assessment
- [ ] Set up automated telemetry feeds
- [ ] Configure alert thresholds
- [ ] Enable audit ledger backup
- [ ] Train staff on verdict interpretation
- [ ] Document escalation procedures
- [ ] Schedule quarterly compliance review

## Support & Extensions

### Common Customizations
- Add facility-specific thresholds
- Include industry standard practices
- Integrate with existing compliance systems
- Custom alert escalation logic

### Adding New Regulations
1. Document new requirements
2. Extract rules
3. Validate with experts
4. Add to Knowledge Graph
5. Redeploy and test

### Integration Examples
- Connect to CEMS data feeds
- Integrate with lab management systems
- Link to incident reporting systems
- Connect to compliance dashboards

## References

### Regulatory Documents
- [Clean Air Act (CAA)](https://www.epa.gov/clean-air-act)
- [Clean Water Act (CWA)](https://www.epa.gov/clean-water-act)
- [40 CFR Part 60](https://www.ecfr.gov/current/title-40/part-60/)

### Industry Resources
- [EPA Oil & Gas Sector](https://www.epa.gov/air-research/oil-and-natural-gas-sector)
- [API Environmental Standards](https://www.api.org/)

### SKI Framework Documentation
- [REGULATIONS.md](./REGULATIONS.md) — Detailed regulatory analysis
- [rules-explained.md](./rules-explained.md) — Rule-by-rule explanation

## Questions?

- Review individual rule documentation
- Check regulation citations
- See REGULATIONS.md for detailed analysis
- Open an issue on GitHub

---

**Note:** This example uses simplified, anonymized data for educational purposes. For production use, work with legal and compliance experts to ensure accuracy and completeness.
