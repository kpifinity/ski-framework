"""
SKI Data Sidecar - Read-only integration with operational telemetry
"""

import json
import logging
import os
import time
from typing import Optional
from fastapi import FastAPI
import uvicorn
import requests

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="SKI Data Sidecar", version="1.0.0")

# Global state
telemetry_received = 0
last_telemetry_time = None
milm_endpoint = os.getenv("MILM_ENDPOINT", "http://milm:8000")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "telemetry_received": telemetry_received,
        "milm_connected": await check_milm_connection(),
    }


@app.post("/api/telemetry")
async def receive_telemetry(data: dict):
    """Receive operational telemetry"""
    global telemetry_received, last_telemetry_time

    try:
        telemetry_received += 1
        last_telemetry_time = time.time()

        # Normalize telemetry to standard format
        normalized = {
            "telemetry_id": data.get("id", f"tel_{telemetry_received}"),
            "timestamp": data.get("timestamp", time.time()),
            "subject": data.get("subject", "unknown"),
            "measurement": data.get("measurement", "unknown"),
        }

        # Forward to MiLM for evaluation
        try:
            response = requests.post(
                f"{milm_endpoint}/api/evaluate",
                json=normalized,
                timeout=30,
            )
            verdict = response.json()
            logger.info(f"Verdict: {verdict.get('verdict')}")
        except Exception as e:
            logger.error(f"Failed to get verdict from MiLM: {str(e)}")

        return {"status": "received", "telemetry_id": normalized["telemetry_id"]}

    except Exception as e:
        logger.error(f"Error processing telemetry: {str(e)}")
        return {"status": "error", "message": str(e)}, 400


@app.get("/api/status")
async def get_status():
    """Get sidecar status"""
    return {
        "service": "sidecar",
        "status": "running",
        "telemetry_received": telemetry_received,
        "milm_endpoint": milm_endpoint,
        "last_telemetry": last_telemetry_time,
    }


async def check_milm_connection() -> bool:
    """Check if MiLM is accessible"""
    try:
        response = requests.get(f"{milm_endpoint}/api/health", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    logger.info("SKI Sidecar starting...")
    logger.info(f"MiLM Endpoint: {milm_endpoint}")
    logger.info("Sidecar ready for telemetry")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info(f"Sidecar shutting down. Total telemetry received: {telemetry_received}")


if __name__ == "__main__":
    port = 8001
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
