# Threat model

This document enumerates the threats the SKI Framework reference
implementation defends against, the assumptions behind those defences,
and the threats explicitly **out of scope**. It is intentionally
specific so that auditors can verify each control end-to-end.

The framework is presumed to be operated by a regulated organisation
inside its own infrastructure boundary. The threat model is written from
the operator's perspective.

---

## Trust model

| Entity | Trusted for | Not trusted for |
|---|---|---|
| **Operator** (the regulated org) | Running the stack, holding KG signing keys, reviewing FLAG/DISCRETIONARY verdicts | Modifying the audit ledger, bypassing append-only triggers, downgrading conformance |
| **KG editor** | Producing the signed Knowledge Graph | Producing telemetry, deciding rule routing at runtime |
| **Telemetry source** (SCADA, sensors, ETL) | Producing well-formed telemetry records | Deciding which rule applies (the Tag Registry decides) |
| **External auditor** | Reading the audit ledger to re-verify | Modifying the ledger or its hash chain |
| **SKI Framework maintainers** | Publishing signed releases | Accessing operator data; the framework never phones home |
| **LLM weights publisher** (Ollama, etc.) | Providing the model artifact | Modifying behaviour after deployment; the SHA-256 pin (`SKI_MODEL_FILE_SHA256`) prevents silent substitution |

---

## In-scope threats

### T-1: Tampering with recorded verdicts

**Goal:** an insider rewrites a FLAG verdict to CLEAR to hide a breach.

**Controls:**

- Postgres BEFORE UPDATE / DELETE / TRUNCATE triggers on
  `ledger_entries` and `telemetry_buffer` raise an exception.
  (`reference-implementation/src/ledger/append_only.sql`)
- The audit ledger entry hash chains to the prior entry; any post-hoc
  edit breaks the chain.
- The canonical serialization is documented (`audit_ledger/canonical.py`)
  so an external auditor can re-verify independently.
- Database role separation: the `ski_model` service connects with a
  role that has `INSERT` only on the ledger tables; `UPDATE` /
  `DELETE` would require a different role with elevated privileges.

**Residual risk:** a sufficiently privileged DBA can disable the
triggers. Mitigated by Postgres audit logging (operator responsibility)
and out-of-band ledger archival (Level 3 conformance).

### T-2: Loading a tampered Knowledge Graph

**Goal:** an attacker swaps the KG file to weaken or invert the rules.

**Controls:**

- Ed25519 signature verification on KG load. The SKI Model service
  refuses to start with `KG signature verification FAILED`.
- `KG_REQUIRE_SIGNATURE=false` is permitted only for local demos and
  immediately disqualifies the deployment from any conformance level
  (specification B2.4).
- Public key is mounted read-only into the container.

**Residual risk:** the signing key is held offline by the KG editor;
key custody is the operator's responsibility. Loss of the private key
permits forged KGs.

### T-3: Non-deterministic inference output

**Goal:** the local LLM drifts (model substitution, library version
change, GPU non-determinism) so the same input produces different
verdicts.

**Controls:**

- `SKI_MODEL_FILE_SHA256` is checked against the actual model file at
  service start. Mismatch -> refuse to start (specification B3.4).
- Inference uses `temperature=0`, fixed `seed=42`, structured output
  enforcement.
- The **determinism canary** re-runs a fixed canary input on a
  schedule (default 300s). Canary failure raises an alert.
- Track 1 (`track: "symbolic"`) does not call the LLM at all; only
  Track 2 (`track: "llm"`) is exposed to this threat.
- `audit-ledger replay` deterministically re-evaluates Track 1
  entries and detects any divergence.

**Residual risk:** Track 2 (LLM) is acknowledged best-effort; replay
intentionally skips Track 2 entries. Pure determinism for natural-
language rules is not currently provable.

### T-4: Producer claiming a rule_id

**Goal:** a compromised producer attaches `rule_id: "lenient_rule"` to
its telemetry, hoping the runtime will trust it.

**Controls:**

- The sidecar and `send-telemetry.py` reject any record containing a
  `rule_id` key (client-side, `B4.3`).
- The SKI Model server ignores any `rule_id` it receives and always
  asks the Tag Registry to resolve `subject -> rule`.
- Conformance test `test_demo_telemetry_has_no_rule_id` enforces this
  on the demo telemetry.

**Residual risk:** none for the documented APIs; an operator who
bypasses the sidecar and writes directly to the SKI Model can still
have their rule_id ignored, so this is fully mitigated.

### T-5: Data exfiltration via cloud LLM

**Goal:** operational data leaks because the runtime calls a cloud API.

**Controls:**

- Default backend is `ollama` (local). The `anthropic` backend is
  labelled non-conformant in `.env.example` and the SKI Model logs a
  bright warning if it is selected.
- The `ski-internal` Docker network has no external connectivity in
  the air-gapped profile (`networks.ski-internal.internal: true`).
- The service makes no outbound network calls during inference when
  the default backend is used. Verified by the
  `test_no_outbound_calls` conformance test (planned for v0.3).

**Residual risk:** the operator can intentionally choose a cloud
backend. This is a policy violation, not a framework bug.

### T-6: Replay-attack against the ledger

**Goal:** an attacker replays a CLEAR verdict to mask a later FLAG.

**Controls:**

- Each ledger entry includes `sequence_number` (monotonic, unique) and
  `telemetry_id` (unique per record). A duplicate insertion would
  collide on the unique constraint.
- The chain hash binds each entry to its predecessor; a replayed entry
  would break the chain.

**Residual risk:** none.

### T-7: Secrets leakage

**Goal:** an attacker reads the Postgres / API / Grafana password.

**Controls:**

- `scripts/setup.sh` generates strong random secrets and writes
  `.env` with mode `0600`.
- No defaults are present; the stack refuses to start without secrets
  (Docker compose uses `${VAR:?error}` syntax).
- `.env` is in `.gitignore`.
- TLS certificates (self-signed by setup) live under `tls/` with mode
  `go-rwx`.

**Residual risk:** operator-side handling of `.env` is the operator's
responsibility.

### T-8: Supply-chain compromise

**Goal:** a malicious dependency is pulled in via pip.

**Controls:**

- All dependencies pinned in `requirements-dev.txt` and per-tool
  `requirements.txt`.
- Dependabot is enabled with grouped minor/patch updates and a
  monthly cadence.
- CI runs `pip-audit` and Trivy against every PR.
- CycloneDX SBOM generated for each release.
- (v0.3 planned) Sigstore / cosign signing of release artifacts and
  container images; SLSA Level 3 provenance.

**Residual risk:** a typosquat slipping past `pip-audit`. Mitigated by
review-before-merge.

---

## Out of scope

The following are **not** defended against by the framework itself.
They are the operator's responsibility.

- **Host OS compromise.** If the host running Docker is rooted, all
  bets are off.
- **Insider with full Postgres superuser.** A DBA can disable
  triggers; mitigation is administrative, not technical.
- **Compromise of the offline signing key.** Key custody is the
  operator's responsibility.
- **Side-channel attacks on the LLM.** Timing / cache attacks on the
  inference path are not in scope; Track 1 has no LLM in the path
  and is unaffected.
- **Denial of service.** Rate limiting and admission control are
  out of scope for the reference implementation; production
  deployments are expected to put the SKI Model behind an ingress
  controller that handles this.
- **Compromise of upstream LLM weights publishers.** The SHA-256 pin
  prevents silent substitution but cannot detect a backdoor in the
  originally-published weights.

---

## Re-verification

An external auditor can independently verify every control above:

1. **Append-only triggers**: query `pg_trigger` and read the trigger
   bodies. Run `UPDATE ledger_entries SET verdict = 'CLEAR' WHERE
   sequence_number = 1` — it must error.
2. **Signature requirement**: corrupt one byte of `kg.json`; the SKI
   Model service must refuse to start.
3. **Determinism canary**: read the canary metric in Prometheus;
   confirm it is reporting PASS on the configured interval.
4. **Replay**: `audit-ledger replay --from 1 --to N --kg-path kg.json
   --strict`. Must exit zero on Track 1 entries.
5. **Chain integrity**: `audit-ledger verify`. Must report
   `chain_link_verified = N / N`.

If any of these checks fails on a deployment claiming conformance, the
operator's claim is invalid.
