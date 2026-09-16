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

## Trust boundary & OT deployment assumptions

**This section is load-bearing for OT/ICS deployments — read it before you
deploy.** It makes explicit a narrower, easy-to-miss trust boundary implied
by, but not spelled out in, the "Telemetry source" row above.

SKI's guarantees are stated **relative to the telemetry it receives**. The
framework enforces its Ed25519-signed Knowledge Graph, its independent
Symbolic Verifier, and its append-only audit ledger — but it does **not**,
by itself, authenticate the telemetry producer or cryptographically verify
a measurement's timestamp. Per the trust model above, the telemetry source
(SCADA, sensors, ETL) is trusted to produce well-formed records; it is
explicitly not trusted to decide which rule applies. What follows makes
the remaining trust explicit.

**Assumption 1 — telemetry integrity and authenticity are enforced
upstream of the sidecar.** SKI assumes the transport delivering telemetry
to the sidecar (mTLS, a private/segmented OT network, a signed producer,
a historian with its own access control) already establishes that a
record genuinely came from the sensor/PLC/historian it claims to. The
sidecar (`reference-implementation/src/sidecar`) does passive, read-only
intake and forwards normalised records to the SKI Model service over
mTLS; it does not itself authenticate the original producer, and nothing
downstream re-derives that authentication.

**Assumption 2 — the telemetry timestamp is authoritative.** Per the
architecture's "Authoritative clock" invariant (see
[Architecture](architecture.md)), a telemetry record's own `timestamp`
field — never wall-clock-at-arrival — is the "now" used for stateful
predicates (window queries, freshness gates) and effective-date /
jurisdiction scoping. The runtime does not cross-check that field against
any independent clock. A per-tenant `max_clock_skew_seconds` column exists
in the telemetry-buffer schema (default 60s; see
[RFC 0001](RFCs/0001-stateful-evaluation.md)) reserved for bounding
acceptable drift — but as of this writing **no runtime code path reads or
enforces it**. Until it is wired in, the practical tolerance for a forged
timestamp is bounded only by whatever `requires_recent_within_seconds`
window an individual KG rule happens to declare, not by any
centrally-enforced skew limit.

**Residual risk this creates.** A producer that can forge its own
`timestamp` field can make stale or fabricated data appear current,
defeating `NULL_STALE` routing and freshness-gated predicates
(`has_fresh_sample`, `requires_recent_within_seconds`) — see
[`conformance/provenance/test_null_stale_routing.py`](../conformance/provenance/test_null_stale_routing.py)
for the mechanism this affects. This is a real gap SKI does not close on
its own: the framework's fail-closed guarantees are about the KG, the
verifier, and the ledger, not about the sensor's honesty about *when* a
reading was taken.

**Recommendation for OT deployments.** For essentially any live OT/ICS
deployment, where this residual risk matters:

- Use **signed or otherwise authenticated telemetry** at the source
  (device-signed payloads, a historian that itself enforces provenance,
  or an ingestion gateway that attaches a verified capture timestamp)
  rather than trusting the record's own `timestamp` field at face value.
- Use a **trusted time source** (NTP/PTP with monitoring, or a hardware
  time source) on the systems that stamp telemetry, so the
  authoritative-clock assumption above is actually sound upstream.
- Treat `max_clock_skew_seconds` as an assumption to enforce
  *operationally* (at the signing/ingestion layer) until the runtime
  itself consults it.
- **Tier obligations conservatively** (`tier-1`) wherever a spoofed
  reading could mask a real breach. Per spec §5.4, an undeclared or
  unrecognised risk tier already fails safe to `tier-1` (see
  [`policies/risk_tier.py`](https://github.com/kpifinity/ski-framework/blob/main/reference-implementation/src/ski_model/v3/policies/risk_tier.py)),
  which forces any non-`AGREED` verifier result to `DISCRETIONARY` with
  human attestation required — the strongest posture SKI's policy layer
  can offer against a telemetry-side compromise it cannot itself detect.

See also [Limitations & assumptions](architecture.md#limitations--assumptions)
for the companion point about non-formalizable rules, and
[docs/security.md](security.md) for how this fits the project's broader
security posture.

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
- The **Symbolic Verifier** independently re-checks every
  formalizable assertion the LLM emits; a drifted or substituted model
  surfaces as `LLM_CONTRADICTION` / `NEURO_SYMBOLIC_DIVERGENCE`
  statuses in the verdict envelope.
- The **agreement monitor** tracks the rolling LLM-verifier agreement
  rate and alerts on a sustained drop below threshold (default 0.95).
- Every envelope records the model-weight hash, KG version hash,
  prompt-template hash, and decoder seed; `audit-ledger replay`
  re-evaluates the symbolically verifiable part and verifies the
  signed transcript for the rest.

**Residual risk:** assertions outside the formalizable subset are
`UNVERIFIABLE` by construction; defensibility for them rests on the
signed transcript (reconstructible provenance), not re-generation.

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
  `sovereignty/test_no_outbound_calls` conformance test and the
  runtime `test_no_egress` suite.

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
  inference path are not in scope. The Symbolic Verifier's checks are
  pure predicate evaluation with no LLM in the path and are unaffected.
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
3. **Agreement monitor**: `GET /api/canary`; confirm `status` is
   `healthy` and `agreement_rate` is at or above the threshold.
4. **Replay**: `audit-ledger replay --from 1 --to N --kg-path kg.json
   --strict`. Must exit zero; symbolically verifiable parts replay
   exactly, LLM reasoning re-verifies via the signed transcript.
5. **Chain integrity**: `audit-ledger verify`. Must report
   `chain_link_verified = N / N`.

If any of these checks fails on a deployment claiming conformance, the
operator's claim is invalid.
