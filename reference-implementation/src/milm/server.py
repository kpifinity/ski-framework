"""
MiLM FastAPI Server - RESTful API for SKI Framework inference
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# Configure logging
logging.basicConfig(level=os.getenv("MILM_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="SKI MiLM Inference Engine", version="1.0.0")

# Global state
knowledge_graph = None
verdicts_produced = 0


class TelemetryRecord(BaseModel):
    """Input telemetry record"""
    telemetry_id: str
    timestamp: str
    subject: str
    measurement: str


class Verdict(BaseModel):
    """Evaluation verdict output"""
    verdict_id: str
    telemetry_id: str
    verdict: str  # CLEAR, FLAG, NULL, DISCRETIONARY
    rule_id: Optional[str] = None
    reasoning: str
    timestamp: str


class HealthStatus(BaseModel):
    """Health check response"""
    status: str
    kg_loaded: bool
    verdicts_produced: int
    timestamp: str


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/health", response_model=HealthStatus)
async def health_check():
    """Health check endpoint"""
    return HealthStatus(
        status="healthy",
        kg_loaded=knowledge_graph is not None,
        verdicts_produced=verdicts_produced,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/api/kg/load")
async def load_knowledge_graph(kg_data: Dict[str, Any]):
    """Load Knowledge Graph"""
    global knowledge_graph

    try:
        # Validate Knowledge Graph structure
        if "rules" not in kg_data:
            raise ValueError("Knowledge Graph must contain 'rules' array")

        knowledge_graph = kg_data
        logger.info(f"Knowledge Graph loaded: {len(kg_data.get('rules', []))} rules")

        return {
            "status": "success",
            "rules_loaded": len(kg_data.get("rules", [])),
            "version": kg_data.get("metadata", {}).get("version", "unknown"),
        }
    except Exception as e:
        logger.error(f"Failed to load Knowledge Graph: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/evaluate", response_model=Verdict)
async def evaluate_telemetry(telemetry: TelemetryRecord):
    """Evaluate telemetry against Knowledge Graph"""
    global verdicts_produced

    try:
        if not knowledge_graph:
            raise ValueError("No Knowledge Graph loaded")

        # Simple matching logic for demonstration
        # In production, this would call Claude with temperature=0
        rules = knowledge_graph.get("rules", [])

        # Find matching rules
        matching_rule = None
        for rule in rules:
            if (rule.get("subject", "").lower() == telemetry.subject.lower()):
                matching_rule = rule
                break

        # Determine verdict based on matching
        if matching_rule:
            verdict_value = "CLEAR"  # Simplified logic
            reasoning = f"Matched rule {matching_rule.get('id')}: {matching_rule.get('reasoning', '')}"
        else:
            verdict_value = "NULL"
            reasoning = "No matching rule found for this telemetry"

        verdict = Verdict(
            verdict_id=f"verdict_{verdicts_produced + 1}",
            telemetry_id=telemetry.telemetry_id,
            verdict=verdict_value,
            rule_id=matching_rule.get("id") if matching_rule else None,
            reasoning=reasoning,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

        verdicts_produced += 1
        logger.info(f"Verdict produced: {verdict.verdict_id} = {verdict_value}")

        return verdict

    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verdicts")
async def get_verdicts(limit: int = 100, offset: int = 0):
    """Get recent verdicts (placeholder)"""
    return {
        "verdicts": [],
        "total": verdicts_produced,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/status")
async def get_status():
    """Get detailed system status"""
    return {
        "service": "milm",
        "version": "1.0.0",
        "status": "running",
        "knowledge_graph_loaded": knowledge_graph is not None,
        "knowledge_graph_rules": len(knowledge_graph.get("rules", [])) if knowledge_graph else 0,
        "verdicts_produced": verdicts_produced,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ============================================================================
# STARTUP & SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    global knowledge_graph

    logger.info("MiLM Inference Engine starting...")

    # Try to load Knowledge Graph from file
    kg_path = os.getenv("KG_PATH", "/app/kg.json")
    if os.path.exists(kg_path):
        try:
            with open(kg_path, "r") as f:
                knowledge_graph = json.load(f)
            logger.info(f"Knowledge Graph loaded from {kg_path}")
        except Exception as e:
            logger.warning(f"Failed to load Knowledge Graph from file: {str(e)}")

    logger.info("MiLM Inference Engine ready")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("MiLM Inference Engine shutting down...")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("MILM_PORT", 8000))
    workers = int(os.getenv("MILM_WORKERS", 4))

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        reload=False,
    )
