"""SKI Sidecar — passive, read-only telemetry intake.

Receives operational telemetry (file, HTTP, or Kafka), normalises it, and
forwards each record to the SKI Model. Does NOT perform tag inference or
any compliance evaluation itself — those are SKI Model concerns.

This implementation uses httpx.AsyncClient (true async I/O), the FastAPI
lifespan context manager (replaces deprecated @app.on_event), and emits a
heartbeat so gaps can be detected downstream.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from pydantic import BaseModel

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sidecar.main")


class _State:
    telemetry_received: int = 0
    last_telemetry_time: Optional[float] = None
    ski_model_client: Optional[httpx.AsyncClient] = None
    heartbeat_task: Optional[asyncio.Task] = None


state = _State()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ca_cert = os.getenv("SKI_MODEL_CA_CERT")
    verify: Any = ca_cert if ca_cert and os.path.exists(ca_cert) else True

    state.ski_model_client = httpx.AsyncClient(
        base_url=os.getenv("SKI_MODEL_ENDPOINT", "https://ski-model:8000"),
        timeout=httpx.Timeout(30.0, connect=5.0),
        verify=verify,
        transport=httpx.AsyncHTTPTransport(retries=3),
        headers={"x-api-key": os.getenv("SKI_MODEL_API_KEY", "")},
    )
    state.heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info(
        "Sidecar ready (endpoint=%s, source=%s)",
        os.getenv("SKI_MODEL_ENDPOINT"),
        os.getenv("TELEMETRY_SOURCE", "file"),
    )

    try:
        yield
    finally:
        if state.heartbeat_task:
            state.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.heartbeat_task
        if state.ski_model_client:
            await state.ski_model_client.aclose()
        logger.info("Sidecar shutting down (telemetry_received=%d)", state.telemetry_received)


app = FastAPI(title="SKI Data Sidecar", version="0.1.0-alpha", lifespan=lifespan)

# Observability contract: monitoring/rules/ski-alerts.yml pages on
# telemetry going silent via this exact series name.
METRICS_REGISTRY = CollectorRegistry()
LAST_TELEMETRY_TS = Gauge(
    "ski_sidecar_last_telemetry_timestamp",
    "Unix time of the last telemetry record the sidecar forwarded.",
    registry=METRICS_REGISTRY,
)


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(METRICS_REGISTRY), media_type=CONTENT_TYPE_LATEST)


class TelemetryPayload(BaseModel):
    id: Optional[str] = None
    timestamp: Optional[str] = None
    subject: str
    measurement: dict[str, Any]


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "telemetry_received": state.telemetry_received,
        "ski_model_connected": await _check_ski_model(),
        "last_telemetry_at": (
            datetime.fromtimestamp(state.last_telemetry_time, tz=timezone.utc).isoformat()
            if state.last_telemetry_time
            else None
        ),
    }


@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload) -> dict[str, Any]:
    if state.ski_model_client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sidecar not ready.")

    state.telemetry_received += 1
    state.last_telemetry_time = time.time()
    LAST_TELEMETRY_TS.set(state.last_telemetry_time)

    record = {
        "telemetry_id": payload.id or f"tel_{state.telemetry_received}",
        "timestamp": payload.timestamp or datetime.now(timezone.utc).isoformat(),
        "subject": payload.subject,
        "measurement": payload.measurement,
    }

    try:
        response = await state.ski_model_client.post("/api/evaluate", json=record)
        response.raise_for_status()
        verdict = response.json()
        logger.info(
            "Verdict: telemetry_id=%s verdict=%s rule=%s",
            record["telemetry_id"],
            verdict.get("verdict"),
            verdict.get("rule_id"),
        )
        return {"status": "evaluated", "telemetry_id": record["telemetry_id"], "verdict": verdict}
    except httpx.HTTPError as exc:
        logger.error("SKI Model call failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"SKI Model unreachable: {exc}") from exc


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return {
        "service": "sidecar",
        "status": "running",
        "telemetry_received": state.telemetry_received,
        "ski_model_endpoint": os.getenv("SKI_MODEL_ENDPOINT"),
        "last_telemetry": state.last_telemetry_time,
    }


async def _check_ski_model() -> bool:
    if state.ski_model_client is None:
        return False
    try:
        resp = await state.ski_model_client.get("/api/health", timeout=5.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def _heartbeat_loop() -> None:
    interval = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
    while True:
        await asyncio.sleep(interval)
        connected = await _check_ski_model()
        logger.info(
            "heartbeat connected=%s telemetry_received=%d",
            connected,
            state.telemetry_received,
        )


if __name__ == "__main__":
    uvicorn.run(
        "sidecar.main:app",
        host=os.getenv("HOST", "0.0.0.0"),  # nosec B104 — container default
        port=int(os.getenv("PORT", "8001")),
        workers=1,
        reload=False,
    )
