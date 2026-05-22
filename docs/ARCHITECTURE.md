# SKI Framework architecture (v2.1)

> **License:** this document is licensed under [CC BY 4.0](../LICENSE-docs.md).

## High-level overview

SKI operates as a **two-phase system** separated by a one-way boundary:

```
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 1 — Offline compilation (outside the sovereign boundary)   │
│ Regulatory documents → kg-extractor → kg-validator (humans) →    │
│ signed Knowledge Graph + compiled Tag Registry                   │
│ Probabilistic work happens here.                                 │
└─────────────────────────────────────────────────────────────────┘
                          │
              one-way boundary crossing
              (data diode, physical media,
               or controlled file transfer)
                          │
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2 — Runtime evaluation (inside the sovereign boundary)     │
│ Telemetry → sidecar → SKI Model service → Tag Registry lookup → │
│ Symbolic Evaluator OR bounded local LLM → verdict → audit ledger │
│ Deterministic work only. No outbound network calls during        │
│ inference under the default configuration.                       │
└─────────────────────────────────────────────────────────────────┘
```

## Phase 1 — offline compilation

**Purpose**: turn regulatory documents into a signed Knowledge Graph
plus a Tag Registry that the runtime can use for deterministic routing.

```
Regulatory documents
        ↓
   Extract rules (LLM-assisted, temperature=0, recorded seed)
        ↓
   Express as structured predicates  {operator, metric, value, unit}
        ↓
   Human expert validation (every rule reviewed)
        ↓
   Conflict declarations + precedence
        ↓
   Compile the Tag Registry  (telemetry subject → rule id)
        ↓
   Sign with Ed25519 over canonical JSON
        ↓
   Transfer across the boundary
```

Key requirements:

- Rules **explicitly stated** in source documents. Inference beyond the
  source text is prohibited (B2.1 Anchor Constraint). The `kg-extractor`
  refuses to emit rules with `confidence: IMPLIED`.
- **Verbatim traceability** to source clause and document version
  (`source_document_version`).
- **Every rule human-validated** (B2.3 Universal Coverage). The
  `kg-validator` does not ship an `auto_approve_explicit` option.
- **Cryptographic signing** with Ed25519 over the canonical
  serialization. Unsigned KGs are rejected at load time.

## Phase 2 — runtime evaluation

```
Operational telemetry
        ↓
   Sidecar (read-only)  ← rejects any record carrying `rule_id`
        ↓
   SKI Model service
        ↓
   Tag Registry  ←  dictionary lookup; no inference
        │
        ├── unmapped → NULL_UNMAPPED (logged to Coverage Register)
        │
        ├── Track 1 → Symbolic Evaluator (deterministic predicates)
        │
        └── Track 2 → bounded local LLM (Ollama, T=0, seed, JSON-only output)
        ↓
   Verdict  ∈  {CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE, DISCRETIONARY}
        ↓
   Audit ledger (append-only, hash-chained)
```

Key requirements:

- All work happens **inside the sovereign boundary**.
- **No outbound network calls during inference** under the default
  configuration. The `anthropic` backend is opt-in, labelled
  non-conformant, and logs a warning on every call.
- **SKI Model at temperature 0 with seeded decoding** and structured
  JSON output.
- **Verdicts are categorical only**. No scores, no confidence intervals
  (B3.1).
- **Every verdict written to the ledger** before being returned.

## Core components

### Knowledge Graph (B2)

```
{
  "metadata":               { version, compiled_at, model_file_sha256, ... },
  "rules": [
    {
      "id":                    "energy.so2.lte_100ppm",
      "subject":               "facility.so2.discharge_ppm",
      "predicate":             { operator, metric, value, unit },
      "track":                 "symbolic" | "llm",
      "confidence":            "EXPLICIT" | "DISCRETIONARY",     /* never IMPLIED */
      "reasoning":             "...",
      "source_document":       "...",
      "source_clause":         "...",
      "source_document_version": "...",
      "effective_date":        "YYYY-MM-DD",
      "sunset_date":           "YYYY-MM-DD" | null,
      "precedence":            <int>,
      "conflicts_with":        [<rule ids>]
    }
  ],
  "tag_registry":           { "<subject>": "<rule_id>", ... },
  "signature":              { algorithm: "ed25519", public_key_pem, value_hex }
}
```

`object` is **never** a free-text string. The Symbolic Evaluator
operates on the structured `predicate` so evaluation is a pure function
of the AST and the input.

### Tag Registry (B4.3)

A frozen lookup from normalised subject → rule id, compiled during
Phase 1 and shipped embedded in the signed KG. At runtime, resolving a
subject is a dict lookup. Runtime tag inference (substring matching,
embedding similarity, LLM disambiguation) is architecturally
prohibited. Missing subjects produce `NULL_UNMAPPED`.

### Symbolic Evaluator (Track 1)

Deterministic predicate evaluator. Operators: `lte`, `gte`, `lt`, `gt`,
`eq`, `range`, `in_set`, `not_in_set`, `exists`. Outputs depend only on
the predicate AST and the input.

The Symbolic Evaluator handles the **majority** of rules in any
well-engineered KG. If most of your rules are Track 2, you have likely
under-specified your predicates.

### SKI Model (Track 2)

Bounded LLM wrapper. Default backend is **Ollama** running a small
open-weights instruction-tuned model. Operating constraints (B3.4):

- Temperature 0, seeded decoding (`SKI_MODEL_SEED`), `top_k = 1`.
- Structured-JSON output enforced. Non-conforming output → `DISCRETIONARY`.
- Model file SHA-256 pinned via `SKI_MODEL_FILE_SHA256`.
- Determinism canary on a fixed input every `DETERMINISM_CANARY_INTERVAL`
  seconds. Divergence flips the canary status and Prometheus alert.

### Audit ledger (B5)

Postgres-backed, append-only, hash-chained. Append-only is enforced at
the database layer (`BEFORE UPDATE / DELETE / TRUNCATE` triggers).
Every entry stores:

```
sequence_number, previous_hash, entry_hash, timestamp,
verdict, telemetry_id, telemetry_hash,
rule_id, knowledge_graph_version, ski_model_version,
reasoning, track,
escalation_status, escalation_notes
```

`entry_hash = SHA-256(canonical_payload)`. The canonical payload is
documented in
[`tools/audit-ledger/src/audit_ledger/canonical.py`](../tools/audit-ledger/src/audit_ledger/canonical.py)
so third parties can verify the ledger without our code.

There is no `confidence_level` column. Confidence scores are prohibited
by B3.1 and Axiom 2.

## Cryptographic primitives

- **KG signatures**: Ed25519 (RFC 8032).
- **Ledger hashes**: SHA-256 over the documented canonical serialization.
- **TLS in transit**: ≥ TLS 1.2; prefer TLS 1.3.

## Deployment modes

| Mode | Description |
|---|---|
| **On-premise** | All components on the customer's infrastructure. Zero external connectivity at runtime. Default. |
| **Air-gapped on-premise** | Network-isolated; updates via physical media. Common for classified / critical infrastructure. |
| **Customer-controlled BYOC** | Customer's own cloud account; customer holds keys and admin. *Not* "KpiFinity-hosts-your-data" — that mode does not exist in v2.1 because it contradicts the Sovereignty pillar. |

## Spec section ↔ implementation map

| Spec | Reference implementation |
|---|---|
| B2.1 Anchor Constraint | `tools/kg-extractor` refuses `IMPLIED`; `scripts/validate-kg.py` enforces |
| B2.2 Conflicts & precedence | `predicate`, `precedence`, `conflicts_with` fields; `kg-validator` conflict detector |
| B2.3 Universal Coverage | `kg-validator` requires human review of every rule |
| B3.1 No confidence scores | Schema has no `confidence_level`; `Verdict` enum is five members |
| B3.2 Local Deployability | Ollama backend, default; no required cloud key |
| B3.4 Determinism Enforcement Controls | Model file SHA-256 pin, fixed seed, canary, structured output |
| B4.3 Tag Registry | `src/tag_registry/`; pure-lookup at runtime |
| B4.4 Stateful Evaluation | Buffer + `NULL_STALE` — **partial in v0.1**, completion planned for v0.2 |
| B5 Audit Ledger | `src/ledger/schema.sql`, `append_only.sql`, real `verify_integrity` and `backup_database` |

## Further reading

- [`KNOWLEDGE_GRAPH.md`](./KNOWLEDGE_GRAPH.md) — KG schema in detail
- [`CONFORMANCE.md`](./CONFORMANCE.md) — Level 1 / 2 / 3 methodology
- [`../reference-implementation/README.md`](../reference-implementation/README.md)
- [`../conformance/README.md`](../conformance/README.md)
