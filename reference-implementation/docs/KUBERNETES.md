# Kubernetes deployment

> **Status:** the v3.1 Helm chart is in tree at
> [`deploy/helm/ski`](../../deploy/helm/ski). The Kubernetes operator,
> CRDs, and per-shard horizontal scaling remain targeted for **v3.2**
> (designed via an RFC before implementation) — see
> [ROADMAP.md](../../ROADMAP.md).

## Install

```bash
# 1. Images: public images are published to ghcr.io/kpifinity/ski-model
#    on every release, with signed build provenance (verify with
#    `gh attestation verify`). The chart defaults to them. Air-gapped
#    clusters mirror the image internally and override image.repository.
#    To build from source instead (repo-root context — the image carries
#    the shared ski-schemas package):
#      docker build -f reference-implementation/Dockerfile.ski-model -t <registry>/ski-model:tag .

# 2. Create the secret — the chart ships NO defaults and refuses to
#    render without it. Use your secret manager in production.
kubectl create secret generic ski-secrets \
  --from-literal=api-key="$(openssl rand -hex 32)" \
  --from-literal=postgres-password="$(openssl rand -hex 24)" \
  --from-literal=ledger-dsn="postgresql://postgres:<password>@ski-ski-postgres:5432/ski_ledger"

# 3. Your SIGNED Knowledge Graph and TLS certificate:
kubectl create configmap ski-kg --from-file=kg.json=signed-kg.json
kubectl create secret tls ski-tls --cert=ski-model.crt --key=ski-model.key

# 4. Install:
helm install ski deploy/helm/ski \
  --set existingSecret=ski-secrets \
  --set kg.configMapName=ski-kg \
  --set tls.secretName=ski-tls
```

The post-install notes walk through staging model weights and running
the conformance suite against the deployment.

## What the chart enforces (not just documents)

- **Single writer.** `replicas: 1`, `strategy: Recreate`, and the
  render **fails** if you set `replicas`/`replicaCount`. Scale by
  installing one release per shard.
- **No default secrets.** The render fails without `existingSecret`;
  there is no password, key, or token anywhere in the chart.
- **Signed KG.** `KG_REQUIRE_SIGNATURE=true` by default; the render
  fails without a KG ConfigMap/Secret.
- **The sovereign boundary as NetworkPolicy.** Egress from the SKI
  Model is limited to the ledger and the LLM backend.
  `networkPolicy.airgap=true` additionally drops DNS egress — with
  bundled Postgres and Ollama the stack is fully functional with zero
  cluster-external destinations (the same property the L3 air-gapped
  conformance rig proves with `--network=none`).
- **Ledger SQL fidelity.** The schema and append-only triggers in the
  chart are byte-identical copies of
  `reference-implementation/src/ledger/` — CI diffs them on every
  build.
- **Hardened pods.** `runAsNonRoot`, uid 10001, all capabilities
  dropped, no privilege escalation.

## Backends

| `skiModel.backend` | Inference | Notes |
|---|---|---|
| `ollama` (default) | bundled StatefulSet or `skiModel.externalOllamaUrl` | pre-stage models into the PVC for air-gapped clusters |
| `vllm` | `skiModel.externalVllmUrl` (your GPU node pool; not bundled) | set `skiModel.modelFileSha256` for the provenance anchor |
| `fake` | in-process deterministic stub | CI/evaluation only — not conformant for production |

## Production ledger

The bundled Postgres is for evaluation. Production deployments set
`postgres.bundled=false`, point `ledger-dsn` at a DBA-managed instance
(with `reclaimPolicy: Retain` storage and a documented backup schedule
— see `SECURITY_DEFAULTS.md`), and apply the chart's `files/*.sql`
there. The append-only triggers are load-bearing for L3 conformance:
verify with `pytest conformance/ -m sovereignty`.

## Telemetry sidecar

The read-only telemetry sidecar is intentionally not in this chart yet:
its deployment shape depends on your data buses (Kafka, OPC-UA, files)
and it is stateless — run it wherever the data is, pointed at the SKI
Model Service. A sidecar sub-chart is tracked for v3.2 alongside the
operator.
