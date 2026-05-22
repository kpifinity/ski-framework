# SKI Model REST API

All endpoints are served by the `ski-model` container on port 8000 over
HTTPS (self-signed by default — replace the certs in `tls/` with your
own CA for any non-local use).

Endpoints that mutate or read sensitive state require the
`X-API-Key` header. `GET /api/health` is the only unauthenticated
endpoint and is used for liveness/readiness probes.

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/health` | GET | — | Liveness + KG signature status + canary status |
| `/api/kg/load` | POST | required | Replace the in-memory Knowledge Graph (signature required) |
| `/api/evaluate` | POST | required | Evaluate a telemetry record |
| `/api/verdicts` | GET | required | List ledger entries (paginated) |
| `/api/canary` | GET | required | Determinism canary snapshot |

## `GET /api/health`

```bash
curl -k https://localhost:8000/api/health
```

```json
{
  "status": "healthy",
  "kg_loaded": true,
  "kg_signature_verified": true,
  "canary_status": "ok",
  "verdicts_produced": 124,
  "timestamp": "2026-05-22T10:42:11.000Z"
}
```

`status` values: `healthy`, `no_kg`.

## `POST /api/kg/load`

Body: a Knowledge Graph object with the structure documented in
[`docs/KNOWLEDGE_GRAPH.md`](../../docs/KNOWLEDGE_GRAPH.md), including a
`signature` block. Unsigned KGs are rejected with HTTP 400 (use
`KG_REQUIRE_SIGNATURE=false` only for local demos).

```bash
curl -k -X POST https://localhost:8000/api/kg/load \
  -H "x-api-key: $SKI_API_KEY" \
  -H "content-type: application/json" \
  -d @your-signed-kg.json
```

```json
{ "status": "success", "rules_loaded": 47, "version": "energy-v1.2" }
```

## `POST /api/evaluate`

Body:

```json
{
  "telemetry_id": "tel_e_001",
  "timestamp": "2026-05-22T10:00:00Z",
  "subject": "facility.so2.discharge_ppm",
  "measurement": {
    "so2_ppm": {"value": 85, "unit": "ppm"}
  }
}
```

`subject` is required and is resolved via the Tag Registry. Records
containing a `rule_id` field are rejected — the producer must not
pre-route to a rule.

Response:

```json
{
  "verdict_id": "verdict_000000000125",
  "telemetry_id": "tel_e_001",
  "verdict": "CLEAR",
  "rule_id": "energy.so2.lte_100ppm",
  "track": "symbolic",
  "reasoning": "Rule energy.so2.lte_100ppm satisfied: so2_ppm=85.0 ≤ 100.0",
  "kg_version": "v0.1-demo",
  "ski_model_version": "0.1.0-alpha",
  "timestamp": "2026-05-22T10:00:00.123Z"
}
```

`verdict` ∈ `{CLEAR, FLAG, NULL_UNMAPPED, NULL_STALE, DISCRETIONARY}`.

| Status | Meaning |
|---|---|
| 200 | Verdict produced and written to the audit ledger. |
| 400 | Telemetry record fails schema validation (e.g., contains `rule_id`). |
| 401 | Missing or invalid `X-API-Key`. |
| 503 | No KG loaded yet. |

## `GET /api/verdicts`

Returns ledger entries in append order (oldest first). Parameters:

- `limit` (default 100)
- `offset` (default 0)

```bash
curl -k -H "x-api-key: $SKI_API_KEY" \
  "https://localhost:8000/api/verdicts?limit=20"
```

Each entry includes `entry_hash`, `previous_hash`, `track`, and the
canonical fields documented in
[`tools/audit-ledger/src/audit_ledger/canonical.py`](../../tools/audit-ledger/src/audit_ledger/canonical.py).

## `GET /api/canary`

```bash
curl -k -H "x-api-key: $SKI_API_KEY" \
  https://localhost:8000/api/canary
```

```json
{
  "status": "ok",
  "last_checked": "2026-05-22T10:42:00Z",
  "failures": 0,
  "interval_seconds": 300
}
```

`status` values: `pending`, `baseline_recorded`, `ok`, `backend_error: …`,
`FAILED — non-determinism detected`.

## Error model

Errors are returned with a `detail` field:

```json
{ "detail": "KG missing signature block." }
```

## Authentication

`X-API-Key` is a fixed-length opaque token. Use `secrets.compare_digest`
or the equivalent on the client side if you handle multiple keys. The
service compares with constant-time equality.

For production, terminate TLS at a reverse proxy (Envoy, nginx, Traefik)
and use mTLS between the proxy and the SKI Model service. The
docker-compose stack does this minimally with self-signed certs; a
production-grade setup is environment-specific and out of scope for
this document.

## Versioning

The API is currently `v0.1.0-alpha`. Breaking changes will be documented
in [`CHANGELOG.md`](../../CHANGELOG.md). The intent is to stabilise at
v1.0 alongside the Conformance Level 1 certification.
