# Manufacturing Sector Example - SKI Framework

Complete example of SKI Framework deployment for workplace safety and environmental compliance in manufacturing facilities.

## Overview

This example demonstrates how to:
- Extract OSHA and EPA compliance rules from regulations
- Validate rules with safety expert review
- Deploy MiLM for continuous facility monitoring
- Generate verdicts for workplace safety and environmental compliance
- Maintain immutable audit trail for regulatory inspection readiness

## Regulatory Framework

### Primary Regulations
- **Occupational Safety and Health Act (OSHA)** — Workplace safety and injury reporting
- **Environmental Protection Agency (EPA)** — Environmental standards and emissions
- **Code of Federal Regulations (CFR)** — 29 CFR (OSHA), 40 CFR (EPA)
- **State-Specific Safety Standards** — Additional jurisdiction requirements

### Key Compliance Areas

1. **Workplace Safety**
   - Injury and illness recording (OSHA 300 Log)
   - Serious injury reporting (24-hour requirement)
   - Hazard communication (chemical labeling, SDS)
   - Personal protective equipment (PPE) requirements
   - Machine guarding and equipment safety

2. **Environmental Compliance**
   - Air quality monitoring (permit compliance)
   - Wastewater discharge standards
   - Hazardous waste management
   - Spill prevention and response
   - Emission monitoring

3. **Equipment & Maintenance**
   - Preventive maintenance programs
   - Equipment inspection schedules
   - Calibration of monitoring equipment
   - Maintenance documentation requirements

4. **Exposure Monitoring**
   - Occupational exposure limits (PEL)
   - Air sampling and analysis
   - Exposure records retention
   - Medical surveillance programs

## Knowledge Graph Structure

The manufacturing sector Knowledge Graph includes:
- **40+ compliance rules** organized by topic
- **Explicit mappings** to OSHA and EPA standards
- **Facility-specific thresholds** for measurements
- **Incident escalation procedures**

### Rule Categories

```
Manufacturing Sector Rules
├── Workplace Safety (12 rules)
├── Environmental Compliance (10 rules)
├── Equipment Maintenance (8 rules)
├── Exposure Monitoring (8 rules)
└── Reporting & Documentation (6 rules)
```

## Example Files

### Knowledge Graph
- **kg-manufacturing-full.json** — Complete Knowledge Graph with all rules
- **kg-manufacturing-sample.json** — Simplified version for testing

### Telemetry
- **sample-safety-incidents.jsonl** — Sample workplace safety data
- **sample-emissions-data.jsonl** — Sample environmental monitoring data
- **sample-equipment-maintenance.jsonl** — Sample maintenance records

### Documentation
- **rules-explained.md** — Explanation of each rule

## Quick Start

### 1. Review the Knowledge Graph

```bash
cat knowledge-graphs/kg-manufacturing-sample.json | jq '.rules[0:5]'
```

### 2. Validate the Knowledge Graph

```bash
python3 ../../scripts/test-kg.py knowledge-graphs/kg-manufacturing-full.json
```

### 3. Load into Deployment

```bash
# Copy to reference implementation
cp knowledge-graphs/kg-manufacturing-full.json ../reference-implementation/examples/knowledge-graphs/kg-manufacturing.json

# Or use milm-deploy
milm-deploy load-kg --kg knowledge-graphs/kg-manufacturing-full.json
```

### 4. Test with Sample Data

```bash
# Test with safety incident data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-safety-incidents.jsonl \
  --output results/safety-verdicts.json

# Test with emissions monitoring data
python3 ../../scripts/test-verdict.py \
  --telemetry telemetry/sample-emissions-data.jsonl \
  --output results/emissions-verdicts.json
```

### 5. Review Results

```bash
cat results/safety-verdicts.json | jq '.verdict_counts'
```

## Rules Overview

### Workplace Safety

**Rule: Serious Injury Reporting**
- Subject: Workplace injury with hospitalization
- Relation: must_be_reported_within
- Object: 24 hours if hospitalization required
- Source: 29 CFR 1904.39
- Status: EXPLICIT

**Rule: Chemical Hazard Communication**
- Subject: Chemical storage area
- Relation: must_be_properly_labeled_with
- Object: GHS labels and Safety Data Sheets (SDS)
- Source: 29 CFR 1200
- Status: EXPLICIT

### Equipment & Maintenance

**Rule: Equipment Maintenance Schedule**
- Subject: Production equipment
- Relation: must_include_documented
- Object: Preventive maintenance schedule
- Source: 29 CFR 1910.22(a)(1)
- Status: EXPLICIT

### Environmental Compliance

**Rule: Air Quality Standards**
- Subject: Facility air quality
- Relation: must_not_exceed
- Object: OSHA Permissible Exposure Limits (PEL)
- Source: 29 CFR 1910 Subpart Z
- Status: EXPLICIT

## Verdict Examples

### CLEAR Verdict
Telemetry: Equipment maintenance completed on schedule, inspection passed
→ Complies with preventive maintenance requirements
→ **CLEAR**

### FLAG Verdict
Telemetry: Workplace injury requiring hospitalization, no incident report filed
→ Violates 24-hour reporting requirement
→ **FLAG** (Immediate escalation required)

### NULL Verdict
Telemetry: Chemical storage area with missing GHS labels
→ Cannot verify chemical hazard communication compliance
→ **NULL** (Documentation unavailable)

### DISCRETIONARY Verdict
Telemetry: Air quality measurement 95% of PEL
→ Within regulatory limit but near boundary
→ May warrant enhanced monitoring
→ **DISCRETIONARY** (Engineering review recommended)

## Customization Guide

### Using Your Own Safety Standards

1. **Extract rules** from your safety manual
   ```bash
   kg-extractor extract --file your-safety-policy.pdf --sector manufacturing
   ```

2. **Validate extracted rules**
   ```bash
   kg-validator validate --input extracted.json --output validated.json
   ```

3. **Review and approve**
   - Open validated.json in editor
   - Verify against OSHA regulations
   - Add facility-specific requirements

4. **Deploy**
   ```bash
   milm-deploy load-kg --kg your-kg.json
   ```

### Adding Custom Rules

Edit `knowledge-graphs/kg-manufacturing-full.json`:

```json
{
  "id": "custom_m001",
  "subject": "Your equipment type",
  "relation": "must_comply_with",
  "object": "Your specific requirement",
  "source_document": "Your standard or regulation",
  "source_clause": "Section X.X",
  "confidence": "EXPLICIT",
  "reasoning": "Explain the compliance requirement..."
}
```

## Testing Scenarios

### Scenario 1: Normal Operations
- All safety checks passed
- Equipment maintenance completed
- Air quality within limits
- No incidents reported
→ Expected verdict: Mostly CLEAR

### Scenario 2: Safety Incident
- Workplace injury occurred
- Missing incident documentation
- Delayed reporting
→ Expected verdict: FLAG

### Scenario 3: Equipment Issue
- Maintenance overdue
- Inspection failure
- Contaminated samples
→ Expected verdict: Mix of FLAG and DISCRETIONARY

### Scenario 4: Missing Documentation
- No equipment maintenance records
- Chemical labels missing
- Exposure monitoring data unavailable
→ Expected verdict: NULL verdicts

## Compliance Reporting

Generate safety and environmental summary:

```bash
python3 ../../scripts/generate-report.py \
  --ledger data/ledger.db \
  --start-date 2026-01-01 \
  --end-date 2026-05-31 \
  --output manufacturing-compliance-report.html
```

Report includes:
- Injury and illness summary
- OSHA 300 Log data
- Environmental monitoring results
- Equipment maintenance status
- Compliance status by facility section
- Audit trail verification
- Regulatory inspection readiness

## Production Deployment Checklist

- [ ] Review all rules against current OSHA/EPA standards
- [ ] Customize rules for your facility type
- [ ] Integrate with your incident reporting system
- [ ] Set up equipment monitoring data feeds
- [ ] Configure alert thresholds for each area
- [ ] Test with historical incident data
- [ ] Validate verdicts match safety team's assessment
- [ ] Enable audit ledger backup
- [ ] Train safety staff on verdict interpretation
- [ ] Document escalation procedures for FLAGS
- [ ] Schedule quarterly safety review

## Support & Extensions

### Common Customizations
- Add facility-specific exposure limits
- Include industry best practices
- Integrate with maintenance management systems
- Connect to environmental monitoring systems
- Custom incident severity classifications

### Integration Examples
- Connect to equipment monitoring systems
- Integrate with incident reporting platforms
- Link to occupational health databases
- Connect to environmental monitoring sensors
- Link to safety dashboards and alerts

## References

### Regulatory Documents
- [OSHA Safety Standards](https://www.osha.gov/dsg/naics-code)
- [29 CFR 1910 - General Industry Standards](https://www.ecfr.gov/current/title-29/part-1910/)
- [29 CFR 1904 - Recording and Reporting Injuries](https://www.ecfr.gov/current/title-29/part-1904/)

### Guidance Documents
- [OSHA Hazard Communication](https://www.osha.gov/dsg/hazcom/)
- [EPA Air Quality Standards](https://www.epa.gov/criteria-air-pollutants)

### Industry Resources
- [NIOSH Guidelines](https://www.cdc.gov/niosh/)
- [ANSI Safety Standards](https://www.ansi.org/)

## Questions?

- Review individual rule documentation
- Check OSHA and EPA regulatory sources
- Contact your safety director for facility-specific questions
- Open an issue on GitHub

---

**Note:** This example uses simplified data for educational purposes. For production use, work with occupational health and safety professionals to ensure compliance with all applicable regulations.
