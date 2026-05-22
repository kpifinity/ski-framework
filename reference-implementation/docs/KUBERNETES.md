# Kubernetes deployment

> **Status:** planned for v0.2. The v0.1.0-alpha reference implementation
> ships docker-compose only. This document captures the intended
> direction so adopters can plan around it.

## Why not yet

For a sovereign-by-default, audit-grade workload, the Kubernetes
manifests must address:

1. **Append-only ledger guarantees.** The `BEFORE UPDATE / DELETE /
   TRUNCATE` triggers must survive PVC rebinds and StatefulSet rollouts.
2. **Single-writer constraint.** The SKI Model service is single-worker
   by design. The deployment must guarantee one Pod per shard, not
   "scale to N for capacity."
3. **Secrets handling.** Production secrets (API keys, DB passwords,
   signing keys) belong in your cluster's secret manager (Vault,
   ExternalSecrets, AWS Secrets Manager via the CSI driver, etc.) —
   not in environment variables baked into manifests.
4. **Air-gapped image distribution.** Many target deployments are
   air-gapped. The manifests must work with privately-mirrored images
   and pre-staged Ollama model files.

We would rather ship Kubernetes support that is right than fast.

## Planned shape

```
deploy/k8s/
├── namespace.yaml
├── secrets/                       (ExternalSecrets recommended)
├── postgres/
│   ├── statefulset.yaml           anti-affinity, PV with retain policy
│   ├── service.yaml
│   └── triggers-job.yaml          one-shot Job to apply append_only.sql
├── ollama/
│   ├── statefulset.yaml
│   └── pvc-model-files.yaml
├── ski-model/
│   ├── deployment.yaml            replicas=1 per shard (not scaled by HPA)
│   ├── service.yaml
│   └── networkpolicy.yaml         denies egress except to ollama/postgres
├── sidecar/
│   ├── deployment.yaml            HPA permitted (stateless)
│   └── service.yaml
└── monitoring/
    ├── prometheus.yaml
    ├── postgres-exporter.yaml
    └── alertmanager.yaml
```

## What works today on Kubernetes anyway

The docker-compose stack runs on `docker compose` running on a single
node. If that node is a Kubernetes node, you can run the stack there
and accept the operational caveats. For multi-node clusters, wait for
v0.2 or contribute manifests via a PR.

## Operational requirements regardless of platform

Any Kubernetes deployment must satisfy:

- One SKI Model Pod per ledger / shard at all times. Use a Deployment
  with `replicas=1` per shard and `strategy: Recreate`. Do not put it
  behind an HPA.
- A `NetworkPolicy` that denies egress to anything except `postgres`
  and `ollama`. This is how you enforce the sovereign boundary at the
  cluster level.
- A `PodSecurityContext` with `runAsNonRoot: true`, `readOnlyRootFilesystem: true`,
  `allowPrivilegeEscalation: false`, and a tightly-scoped `securityContext.capabilities.drop`.
- Postgres on a `PersistentVolume` whose `reclaimPolicy: Retain` and
  whose backup schedule is documented in your runbook.
- An external Alertmanager configured for the four SKI alert rules in
  `monitoring/rules/ski-alerts.yml`.

If you build a manifests PR for v0.2, please align with these
requirements and add a conformance-suite job to the chart's CI.
