# SKI Framework Architecture

## High-Level Overview

SKI operates as a **two-phase system** separated by a physical boundary:

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: OFFLINE (Outside Sovereign Boundary)               │
│ ─────────────────────────────────────────────────────────── │
│ Regulatory Documents → LLM Extraction → Knowledge Graph      │
│ (Probabilistic work happens here)                            │
│ Output: Signed Knowledge Graph                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
                  One-way boundary crossing
                  (Data diode or physical media)
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: RUNTIME (Inside Sovereign Boundary)                │
│ ─────────────────────────────────────────────────────────── │
│ Operational Telemetry → MiLM Evaluation → Verdicts → Ledger │
│ (Deterministic work happens here)                            │
│ Output: Immutable Audit Ledger                               │
└─────────────────────────────────────────────────────────────┘
```

## Architecture Components

### Phase 1: Knowledge Graph Compilation

**Purpose**: Transform regulatory documents into machine-readable rules

**Flow**:
```
Regulatory Documents
        ↓
   Extract Rules (LLM-assisted)
        ↓
   Structure as Triplets (Subject-Relation-Object)
        ↓
   Human Expert Validation
        ↓
   Create Precedence Rules (for conflicts)
        ↓
   Sign Knowledge Graph (cryptographic)
        ↓
   Transfer to Sovereign Boundary (one-way only)
```

**Key Requirements**:
- Rules must be **explicitly stated** in source documents (no inference)
- Every rule must have **verbatim traceability** to source clause
- **Human validation** mandatory before activation
- **Cryptographic signing** prevents tampering
- **Version control** for full audit trail

**Output**: Signed Knowledge Graph file

### Phase 2: Runtime Evaluation

**Purpose**: Evaluate operational telemetry against Knowledge Graph in real-time

**Flow**:
```
Operational Telemetry
        ↓
   Normalize to Standard Record Format
        ↓
   MiLM Evaluates Against Knowledge Graph
        ↓
   Produce Categorical Verdict
        ↓
   Write to Immutable Audit Ledger
        ↓
   Optional: Escalate (FLAG or DISCRETIONARY)
```

**Key Requirements**:
- All work happens **inside sovereign boundary**
- **No external network calls** during inference
- MiLM operates at **temperature zero** (deterministic)
- Verdicts are **categorical only** (no scores)
- Every verdict **written to ledger** immediately

**Output**: Immutable Audit Ledger entry

---

## Core Components

### 1. Knowledge Graph

**What it is**: Structured representation of compliance obligations

**Structure**:
```
Subject-Relation-Object Triplet
├── Subject: The entity being evaluated (e.g., "Emissions Monitor")
├── Relation: The compliance obligation (e.g., "Must be within")
└── Object: The regulatory limit (e.g., "100 ppm")

With metadata:
├── Source Document: Which regulation this came from
├── Source Clause: Exact location in regulation
├── Effective Date: When this rule starts
├── Status: EXPLICIT (stated) or DISCRETIONARY (ambiguous)
└── Precedence: Priority if conflicts with other rules
```

**Validation**:
- Every rule reviewed by compliance expert
- Compared against original regulatory document
- Cross-checked for conflicts
- Approved before activation

**Versioning**:
- Each update creates new version (immutable history)
- Previous versions retained forever
- Can roll back to any prior version
- Each version signed and dated

### 2. MiLM (Micro Language Model)

**What it is**: The inference engine that evaluates telemetry

**Characteristics**:
- **Small** (runs on-premise, not in cloud)
- **Constrained** (temperature=0, structured output only)
- **Deterministic** (same input → same output, always)
- **Bounded** (only accesses Knowledge Graph, not external context)

**Execution**:
```
Input: {
  "telemetry_record": { ... },
  "relevant_kg_rules": [ ... ],
  "evaluation_context": { ... }
}
        ↓
MiLM Processing
        ↓
Output: {
  "verdict": "CLEAR" | "FLAG" | "NULL" | "DISCRETIONARY",
  "matching_rule_id": "kg_rule_12345",
  "confidence": null (not permitted),
  "reasoning_trace": "Rule matched because..."
}
```

**Key Constraint**: 
- Output schema strictly validated
- Non-conforming outputs rejected as NULL verdict
- No probabilistic scores or confidence intervals

### 3. Data Integration (Sidecar)

**What it is**: Read-only connection to operational telemetry

**Architecture**:
```
Primary System (untouched)
        ↓ (read-only tap)
Telemetry Stream
        ↓
SKI Sidecar
├── Normalize to standard format
├── Validate quality
└── Pass to MiLM
```

**Requirements**:
- **Read-only** (never modifies primary systems)
- **Passive** (primary systems unaware of SKI)
- **Non-blocking** (if SKI fails, operations continue)
- **Monitored** (heartbeat signal for gap detection)

**Data Flow**:
- Raw telemetry enters sidecar
- Normalized to SKI telemetry record
- Passed to MiLM for evaluation
- Raw values **purged after evaluation** (privacy)
- Only verdict metadata written to ledger

### 4. Immutable Audit Ledger

**What it is**: Tamper-evident record of all verdicts

**Structure**:
```
Entry N:
├── Sequence Number: [Unique, no gaps]
├── Previous Hash: [Hash of Entry N-1] (chain linkage)
├── Entry Hash: [Hash of this entry] (tamper detection)
├── Timestamp: [UTC when evaluated]
├── Verdict: "CLEAR" | "FLAG" | "NULL" | "DISCRETIONARY"
├── Rule ID: "kg_rule_12345" (which rule produced this)
├── Telemetry Reference: "tel_98765" (hash of input, not values)
├── Knowledge Graph Version: "kg_v2.1_hash_abc123"
├── MiLM Version: "milm_v1.0"
└── Optional Escalation: [Human reviewer, decision, timestamp]
```

**Properties**:
- **Append-only** (new entries only, no deletions)
- **Hash-chained** (detects any modification)
- **Cryptographically verifiable** (no proprietary tools needed)
- **Audit-grade** (holds up in regulatory inspection)

**Retention**:
- Kept for full regulatory retention period
- Backed up off-site
- Verified annually for integrity

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 1 (Offline)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Regulatory Documents (PDF, HTML, etc.)                           │
│           ↓                                                        │
│  LLM Extraction Pipeline                                          │
│  ├─ Extract compliance rules                                      │
│  ├─ Create triplets (S-R-O)                                       │
│  └─ Flag ambiguous rules → DISCRETIONARY                          │
│           ↓                                                        │
│  Human Validation Review                                          │
│  ├─ Verify rules match source                                     │
│  ├─ Check for conflicts                                           │
│  └─ Approve for production                                        │
│           ↓                                                        │
│  Knowledge Graph Compilation                                      │
│  ├─ Organize rules with precedence                                │
│  ├─ Sign with cryptographic key                                   │
│  └─ Version and timestamp                                         │
│           ↓                                                        │
│  Signed Knowledge Graph File ✓                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────┘
              One-way boundary crossing (data diode or media)
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 2 (Runtime)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Operational Telemetry Streams (continuous)                       │
│  ├─ Process measurements (flow, pressure, temp, etc.)            │
│  ├─ Transaction data (financial events)                           │
│  ├─ Event logs (equipment state changes)                          │
│  └─ Other: Status, alarms, metrics                                │
│           ↓                                                        │
│  SKI Sidecar (read-only integration)                              │
│  ├─ Tap into data streams (never modify)                          │
│  ├─ Normalize to standard SKI record format                       │
│  ├─ Validate data quality                                         │
│  └─ Emit heartbeat (gap detection)                                │
│           ↓                                                        │
│  MiLM Inference Engine (on-premise, temperature=0)                │
│  ├─ Load signed Knowledge Graph                                   │
│  ├─ Evaluate telemetry against rules                              │
│  ├─ Produce categorical verdict only                              │
│  └─ No external network calls permitted                           │
│           ↓                                                        │
│  Verdict Generation                                                │
│  └─ CLEAR | FLAG | NULL | DISCRETIONARY                          │
│           ↓                                                        │
│  Immutable Audit Ledger                                           │
│  ├─ Hash-chained entries                                          │
│  ├─ Timestamp, verdict, rule ID                                   │
│  ├─ No raw telemetry values (only metadata)                       │
│  └─ Signed, versioned, immutable                                  │
│           ↓                                                        │
│  Escalation (if needed)                                            │
│  ├─ FLAG: Notify compliance team (breach detected)               │
│  ├─ DISCRETIONARY: Route to human expert                          │
│  └─ NULL: Document in Coverage Register                           │
│                                                                     │
│  Output: Audit-ready evidence ledger ✓                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Security & Boundaries

### Sovereign Boundary

The **sovereign boundary** is the perimeter within which runtime evaluation occurs:

**Inside the boundary (on-premise)**:
- MiLM inference engine
- Knowledge Graph (signed)
- Audit ledger
- Data sidecar integration
- No external network connectivity

**Outside the boundary (during compilation only)**:
- LLM extraction and validation
- Document repositories
- External connectivity allowed

**Crossing the boundary**:
- One-way only (data diode or physical media)
- Knowledge Graph signed before crossing
- No data exits during runtime under any circumstances

### Cryptographic Integrity

```
Knowledge Graph Signing:
  Knowledge Graph File
         ↓
  Compute SHA-256 hash
         ↓
  Sign with private key
         ↓
  Produce Signing Certificate
         ↓
  Verified on every MiLM startup
         ↓
  If invalid → Shutdown (refuse to operate)

Audit Ledger Chain:
  Entry N-1 Hash
         ↓
  Entry N Content
         ↓
  Compute Entry N Hash
         ↓
  Include Previous Hash in Entry N+1
         ↓
  Verifiable without proprietary tools
```

---

## Deployment Modes

### Mode 1: On-Premise (Recommended)
- All components on customer's infrastructure
- Zero external connectivity during runtime
- Customer manages all aspects
- Maximum sovereignty

### Mode 2: Air-Gapped On-Premise
- Isolated network (no internet)
- Updates via physical media only
- Maximum security for classified/sensitive
- Common in defense/critical infrastructure

### Mode 3: Managed (Optional, Future)
- KpiFinity hosts infrastructure
- Customer retains data ownership
- Read-only audit ledger access for customer
- Hybrid model (operational data stays with customer)

---

## Next Steps

- [Getting Started Guide](./GETTING_STARTED.md) for implementation overview
- [Knowledge Graph Guide](./KNOWLEDGE_GRAPH.md) for rules structure
- [Full SKI Framework](https://skiframework.org) for complete specification

Questions? Open an issue or contact hello@kpifinity.com
