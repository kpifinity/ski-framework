# EU AI Act crosswalk

> **License:** CC BY 4.0. See [LICENSE-docs.md](../../LICENSE-docs.md).
>
> **Status: informative, not normative — and not legal advice.** This
> crosswalk maps SKI Framework controls to obligations in Regulation
> (EU) 2024/1689 (the "EU AI Act", Official Journal version of 13 June
> 2024). It is a technical mapping prepared by engineers, not a legal
> opinion, a conformity assessment, or a compliance guarantee.
> Deploying SKI does not make an AI system compliant with the EU AI
> Act. Organisations must engage qualified legal counsel and, where
> required, notified bodies.

## Why this document exists

From **2 August 2026**, the EU AI Act's requirements for high-risk AI
systems (Chapter III, Section 2 — Articles 9–15) and the corresponding
provider and deployer obligations (Articles 16–27) become applicable
for Annex III systems. Non-compliance with high-risk obligations
carries administrative fines of up to **€15 million or 3% of total
worldwide annual turnover**, whichever is higher (Article 99(4));
prohibited practices carry up to €35 million or 7% (Article 99(3)).

Several of the Act's hardest technical asks — automatic, tamper-evident
event logging; traceability of every output to its inputs and reference
data; effective human oversight; declared and monitored accuracy — are
precisely the properties the SKI Framework was architected to provide.
This crosswalk states, article by article, what SKI provides, what it
supports, and what it deliberately does not address.

## Applicability timeline

| Date | What becomes applicable |
|---|---|
| 1 August 2024 | Regulation in force |
| 2 February 2025 | Prohibited practices (Article 5); AI literacy (Article 4) |
| 2 August 2025 | General-purpose AI model obligations (Chapter V); governance; penalties framework |
| **2 August 2026** | **High-risk AI system requirements and operator obligations (Annex III systems); transparency obligations (Article 50)** |
| 2 August 2027 | Article 6(1) high-risk systems embedded in regulated products |

## How to read the coverage column

- **Direct** — a SKI mechanism implements the obligation's technical
  substance for the monitored scope; evidence is produced
  automatically and is auditable.
- **Supports** — SKI produces artefacts or enforcement points that
  materially assist the obligation, but the obligation is broader than
  SKI's scope (organisational, procedural, or covering systems SKI
  does not monitor).
- **Out of scope** — SKI makes no claim. Listed explicitly so the
  boundary is unambiguous.

SKI's role in a high-risk deployment is **compliance-monitoring
infrastructure**: a passive, sovereign, neuro-symbolic evaluator that
watches operational telemetry, evaluates it against a signed Knowledge
Graph of obligations, and seals every verdict in a verifiable audit
trail. The tables below map that role onto the Act.

## Provider-facing requirements (Articles 9–19, 72)

| Article | Obligation (condensed) | SKI control | Coverage |
|---|---|---|---|
| **9** — Risk management system | Continuous, iterative risk identification and mitigation across the lifecycle | Risk-tier governor (per-snapshot tier → mandatory human attestation on elevated tiers); Residual Risk Register (spec Part D) formally records accepted coverage gaps; published threat model | **Supports** — SKI structures and evidences the risk loop for the monitored scope; the Act requires an organisation-wide RMS |
| **10** — Data and data governance | Training/validation/testing data quality and governance | Knowledge Graph governance: every reference rule is extracted, human-validated, Ed25519-signed, and versioned before runtime use | **Supports (reference data only)** — SKI governs its *reference* data (the KG) to Article 10-grade discipline; governance of model training data is out of scope |
| **11** — Technical documentation (Annex IV) | Documentation demonstrating compliance, kept current | Versioned open specification; per-verdict model commitments (model-weight hash, KG-version hash, prompt-template id + hash, decoder seed, grammar hash) generated automatically | **Supports** — provenance anchors feed Annex IV §2–3 (system description, monitoring and logging capabilities); the full Annex IV dossier is the provider's |
| **12** — Record-keeping | Automatic recording of events over the system's lifetime; traceability | **The audit ledger is this obligation, implemented**: append-only (DB-trigger-enforced), hash-chained from genesis, every verdict with signed LLM transcript. See the element-by-element mapping below | **Direct** |
| **13** — Transparency and provision of information to deployers | Output interpretable; instructions for use; characteristics, capabilities, limitations | Closed five-verdict taxonomy (no scores to misread); every verdict carries plain-language reasoning + citations to named source clauses; published accuracy metrics (SKI Evals) and known-limitation docs | **Direct** for verdict interpretability; **Supports** for instructions-for-use |
| **14** — Human oversight | Effective oversight; ability to interpret, override, disregard; automation-bias awareness | DISCRETIONARY verdicts route to humans by design; risk-tier policy forces human attestation on elevated tiers; agreement monitor surfaces LLM↔verifier divergence (the automation-bias tripwire); SKI is read-only with zero control path — a human can always disregard it without operational consequence | **Direct** for the monitoring function's oversight design |
| **15** — Accuracy, robustness, cybersecurity | Declared accuracy; resilience to errors and misuse; security | SKI Evals: published verdict-accuracy metrics incl. the zero-silent-clears safety property; output-contract guard degrades misbehaving model output to human review (never crashes, never silently clears); signed KG required at boot; TLS by default; append-only ledger; air-gap operability proven by a gating CI rig | **Direct** for declared-accuracy and degradation behaviour of the monitoring function; **Supports** for deployment-wide cybersecurity |
| **17** — Quality management system | Documented policies, procedures, instructions | Governed KG update protocol with named accountable roles (Owner sign-off, Domain Expert validation); 77-test conformance suite as the QA gate; versioned spec ↔ suite pairing | **Supports** — SKI supplies the technical QMS spine for the monitoring function; the QMS itself is organisational |
| **18** — Documentation keeping | Keep technical documentation 10 years | Ledger backup/restore via `audit-ledger` CLI (`pg_dump`-based); deterministic replay verifies archived ledgers | **Supports** — retention execution is the operator's |
| **19** — Automatically generated logs | Providers keep Article 12 logs ≥ 6 months | Ledger is durable Postgres; integrity verifiable at any later date via `verify_integrity` (recomputes every entry hash) | **Direct** for log existence and integrity; retention scheduling is the operator's |
| **72** — Post-market monitoring | Plan to collect and review operational experience | The verdict stream *is* continuous post-market monitoring: FLAG/NULL trends, Coverage Register (every NULL_UNMAPPED = documented coverage gap), agreement-rate trend, nightly eval reports | **Direct** as the data source; the documented plan is the provider's |

## Deployer-facing obligations (Article 26)

| Obligation (condensed) | SKI control | Coverage |
|---|---|---|
| 26(1) — use per instructions; technical and organisational measures | Conformance suite gives deployers a runnable definition of "operated correctly" (77 tests, three levels) | **Supports** |
| 26(2) — assign competent human oversight | DISCRETIONARY queue + attestation records make the oversight role concrete, evidenced, and auditable | **Supports** |
| 26(5) — monitor operation; inform provider/authorities of risks and serious incidents | FLAG verdicts with cited obligations are structured incident evidence; NULL_STALE detects silent telemetry failure | **Supports** |
| 26(6) — retain automatically generated logs ≥ 6 months | Append-only ledger with documented backup; tamper-evidence survives archival (hash chain + signed transcripts verify offline) | **Direct** for the log substrate; retention scheduling is the deployer's |

## Article 12, element by element

Article 12 is where SKI's design and the Act's text align most
closely. The Act requires automatic recording of events relevant for
identifying risk and tracing the system's functioning; for the
reference-checking systems it singles out, the logs must capture at
minimum:

| Article 12(3) element | SKI ledger field(s) |
|---|---|
| (a) period of each use | `timestamp` per entry; telemetry timestamps are the authoritative clock (RFC 0001); evaluation `started_at`/`completed_at` in the signed transcript |
| (b) reference database against which input was checked | `knowledge_graph_version` + `kg_version_hash` — the exact signed KG version, cryptographically committed per verdict |
| (c) input data for which the search led to a match | `telemetry_id` + `telemetry_hash` per entry; matched obligation recorded via `rule_id` and envelope KG citations |
| (d) identification of natural persons involved in verification | Human-attestation records on DISCRETIONARY/elevated-tier verdicts; KG Owner and Domain Expert sign-offs in the governance trail |

Beyond the minimum, every entry is hash-chained to its predecessor,
protected by database-layer append-only triggers, and accompanied by an
ed25519-signed transcript of the model's full reasoning — so the log
does not merely exist, it is **tamper-evident and independently
verifiable** (the L3 conformance suite includes a destructive
tamper-resistance rig demonstrating that in-place edits are detected
even when an attacker disables the triggers and rewrites rows).

## What SKI does not do

Stated plainly, because a credible crosswalk is defined by its
boundary:

- **Classification.** SKI does not determine whether your AI system is
  high-risk (Article 6, Annex III) or whether a practice is prohibited
  (Article 5). That is a legal analysis.
- **Fundamental Rights Impact Assessment** (Article 27).
- **Conformity assessment, CE marking, registration** (Articles 43,
  47–49). SKI evidence can be *submitted into* these processes; SKI
  does not perform them.
- **GPAI model obligations** (Chapter V). The local model inside a SKI
  deployment is operator-chosen; obligations attaching to that model's
  provider remain with that provider.
- **Training-data governance** for the models you deploy (Article 10,
  beyond SKI's own reference KG).
- **Organisation-wide processes**: the full risk-management system,
  QMS, retention scheduling, incident-reporting workflows. SKI
  evidences these; it does not constitute them.

## SKI itself under the Act

SKI is monitoring infrastructure, not a decision-maker. Its three
axioms were chosen so that a SKI deployment stays on the right side of
the Act's concerns by construction: it is **passive** (read-only, zero
control path to operations — it cannot take an action affecting any
person), **proximate** (no data leaves the sovereign boundary), and
**provenance-complete** (every output reconstructible by an auditor).
Whether a specific deployment context brings a SKI installation into
scope as part of a high-risk system depends on that context and
belongs to the deployer's legal analysis; SKI's human-authority-
preserving design (humans validate every rule, humans receive every
escalation, humans can disregard any verdict) is intended to make the
supportive role unambiguous.

## References

- Regulation (EU) 2024/1689, Official Journal of 13 June 2024.
- AI Act Explorer (article texts): <https://artificialintelligenceact.eu/ai-act-explorer/>
- Implementation timeline: <https://artificialintelligenceact.eu/high-level-summary/>
- Penalties: Article 99, <https://artificialintelligenceact.eu/article/99/>
- SKI controls referenced: [specification](../specification-v3.md),
  [conformance](../conformance.md), [evals](../evals.md),
  [benchmarks](../benchmarks.md), [threat model](../threat-model.md),
  [governance](../governance.md).

*Prepared June 2026 against reference implementation v3.1.0-alpha.2.
This document will be revised as delegated acts, harmonised standards
(CEN-CENELEC JTC 21), and Commission guidance are published. Corrections
welcome via GitHub issues.*
