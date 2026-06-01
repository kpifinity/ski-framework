"""SKI Model FastAPI server — runtime inference for the SKI Framework v3.

The v3 architecture inverts the v2 control flow. A KG-grounded LLM is the
primary evaluator; the Symbolic Verifier (PR 10c) mechanically cross-checks
its formalizable assertions. PR 10b ships the evaluator path end-to-end with
a deterministic ``FakeLLM`` backend so CI exercises the full plumbing without
secrets.

Endpoints:

  POST /api/evaluate      — v3 inference; returns a V3VerdictEnvelope.
  POST /api/kg/load       — load a signed Knowledge Graph at runtime.
  GET  /api/health        — liveness + readiness.
  GET  /api/verdicts      — paginated verdict ledger (auth required).
  GET  /api/canary        — neuro-symbolic agreement-rate snapshot.

It is NOT production ready. See README.md for the gap list. Single-worker
enforcement is preserved from v2.1 (see docs/CONCURRENCY.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

# Allow execution as `python -m ski_model.server` (package mode) OR as a
# raw script via the container CMD when WORKDIR is /app.
try:
    from symbolic_evaluator import SymbolicEvaluator
    from tag_registry import RiskTierGovernor, TagRegistry
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from symbolic_evaluator import SymbolicEvaluator
    from tag_registry import RiskTierGovernor, TagRegistry

from .kg_loader import KnowledgeGraph, load_signed_kg
from .ledger_client import LedgerClient
from .v3 import (
    AgreementMonitor,
    TranscriptSigner,
    V3Evaluator,
    V3LLMBackend,
    V3VerdictEnvelope,
)
from .v3 import (
    build_backend as build_v3_backend,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ski_model.server")


_VERSION = "3.0.0-alpha"


# ============================================================================
# State
# ============================================================================


class _State:
    """Process-local state. Workers MUST be 1 — see docs/CONCURRENCY.md."""

    knowledge_graph: Optional[KnowledgeGraph] = None
    tag_registry: Optional[TagRegistry] = None
    symbolic_evaluator: Optional[SymbolicEvaluator] = None
    ledger: Optional[LedgerClient] = None
    telemetry_buffer: Optional[Any] = None
    tenant_id: str = "default"
    verdicts_produced: int = 0

    # v3 evaluator state
    llm_backend: Optional[V3LLMBackend] = None
    evaluator: Optional[V3Evaluator] = None
    kg_version_hash: str = "sha256:" + "0" * 64
    transcript_signer: Optional[TranscriptSigner] = None
    agreement_monitor: Optional[AgreementMonitor] = None


state = _State()


# ============================================================================
# Request / response models
# ============================================================================


class MeasurementRecord(BaseModel):
    """Measurement input for /api/evaluate.

    The v3 evaluator consumes the full measurement; the LLM scopes the KG
    snapshot to the measurement's jurisdiction and effective date. PR 10b
    passes the full KG as the snapshot. Jurisdiction-scoped snapshots are a
    follow-up.
    """

    measurement_id: str = Field(..., description="Stable id for replay correlation.")
    timestamp: str = Field(..., description="ISO-8601 UTC.")
    subject: str = Field(..., description="Subject token (e.g. data source identifier).")
    measurement: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured measurement values keyed by metric name.",
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        description=(
            "Tenant-declared jurisdiction (e.g. 'us-ca', 'eu', 'global'). When set, "
            "the KG is scoped to obligations whose jurisdiction matches or is "
            "universal ('global', '*'). None means 'no restriction' — all rules "
            "effective at the measurement's timestamp are sent to the LLM."
        ),
    )


class HealthStatus(BaseModel):
    status: str
    kg_loaded: bool
    kg_signature_verified: bool
    canary_status: str
    verdicts_produced: int
    timestamp: str
    runtime_version: str


# ============================================================================
# Authentication
# ============================================================================


_API_KEY = os.getenv("API_KEY", "")
_API_KEY_REQUIRED = os.getenv("API_KEY_REQUIRED", "true").lower() == "true"


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not _API_KEY_REQUIRED:
        return
    if not _API_KEY:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: API_KEY_REQUIRED=true but no API_KEY set.",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, _API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key.")


# ============================================================================
# KG snapshot adapter
# ============================================================================


def _kg_to_v3_snapshot(kg: KnowledgeGraph) -> Dict[str, Any]:
    """Convert a :class:`KnowledgeGraph` into the snapshot dict the evaluator wants.

    The v3 schema names regulatory items ``obligations``. The current
    :class:`KnowledgeGraph` exposes them as ``rules`` for historical reasons;
    PR 10e renames the KG tooling fields. Until then this adapter remaps.
    """
    return {
        "version": kg.version,
        "obligations": kg.rules,
        "definitions": kg.metadata.get("definitions", []),
    }


def _compute_kg_version_hash(kg: KnowledgeGraph) -> str:
    """sha256 of the canonical KG payload — recorded in ModelProvenance."""
    payload = json.dumps(
        {
            "version": kg.version,
            "rules": kg.rules,
            "tag_registry": kg.tag_registry,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _build_v3_llm_backend() -> V3LLMBackend:
    """Select the v3 LLM backend.

    Delegates to :func:`ski_model.v3.build_backend`. ``SKI_V3_LLM_BACKEND``
    controls the selection (``"fake"`` default, ``"ollama"`` for the
    Ollama-v3 backend). PR 11.5 added the Ollama backend; future
    additions (vLLM, etc.) extend the factory without touching the
    server.
    """
    return build_v3_backend()


# ============================================================================
# Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Replaces deprecated @app.on_event handlers (FastAPI ≥0.93)."""
    logger.info("SKI Model starting (v%s, runtime=v3)", _VERSION)

    kg_path = Path(os.getenv("KG_PATH", "/app/kg/kg.json"))
    require_sig = os.getenv("KG_REQUIRE_SIGNATURE", "true").lower() == "true"
    try:
        state.knowledge_graph = load_signed_kg(kg_path, require_signature=require_sig)
        state.kg_version_hash = _compute_kg_version_hash(state.knowledge_graph)
        logger.info(
            "KG loaded: version=%s rules=%d signature_verified=%s kg_hash=%s",
            state.knowledge_graph.version,
            len(state.knowledge_graph.rules),
            state.knowledge_graph.signature_verified,
            state.kg_version_hash[:16] + "…",
        )
    except FileNotFoundError:
        logger.warning("No Knowledge Graph at %s. /api/kg/load can supply one.", kg_path)

    if state.knowledge_graph is not None:
        state.tag_registry = TagRegistry.from_knowledge_graph(state.knowledge_graph)

    state.symbolic_evaluator = SymbolicEvaluator()
    state.llm_backend = _build_v3_llm_backend()
    state.transcript_signer = TranscriptSigner.auto_provision()
    logger.info(
        "Transcript signer ready (key_id=%s)",
        state.transcript_signer.key_id[:24] + "…",
    )
    state.evaluator = V3Evaluator(
        llm=state.llm_backend,
        kg_version_hash=state.kg_version_hash,
        decoder_seed=int(os.getenv("SKI_MODEL_SEED", "0")),
        signer=state.transcript_signer,
    )

    state.ledger = LedgerClient(os.getenv("LEDGER_DSN", ""))
    await state.ledger.initialize()

    state.tenant_id = os.getenv("SKI_TENANT_ID", "default")
    try:
        from telemetry_buffer import TelemetryBuffer

        if state.ledger is not None and state.ledger._engine is not None:
            state.telemetry_buffer = TelemetryBuffer(
                state.ledger._engine,
                tenant_id=state.tenant_id,
            )
            logger.info("Telemetry buffer ready (tenant=%s).", state.tenant_id)
    except Exception as exc:  # pragma: no cover — buffer is best-effort wiring
        logger.warning(
            "Telemetry buffer not initialised (%s); stateful predicates will degrade.",
            exc,
        )

    # PR 12: neuro-symbolic agreement monitor replaces the v2 determinism
    # canary. Tracks the rolling LLM↔verifier agreement rate across the
    # last SKI_AGREEMENT_WINDOW evaluations; pages when the rate dips
    # below SKI_AGREEMENT_THRESHOLD.
    state.agreement_monitor = AgreementMonitor(
        window_size=int(os.getenv("SKI_AGREEMENT_WINDOW", "1000")),
        threshold=float(os.getenv("SKI_AGREEMENT_THRESHOLD", "0.95")),
    )

    logger.info(
        "SKI Model ready (evaluator=v3, llm=%s, agreement_window=%d, agreement_threshold=%.3f)",
        state.llm_backend.name,
        state.agreement_monitor.window_size,
        state.agreement_monitor.threshold,
    )

    try:
        yield
    finally:
        await state.ledger.close()
        logger.info("SKI Model stopping (verdicts_produced=%d)", state.verdicts_produced)


# ============================================================================
# App
# ============================================================================


app = FastAPI(title="SKI Model Inference Engine", version=_VERSION, lifespan=lifespan)


@app.get("/api/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    monitor = state.agreement_monitor
    if monitor is None:
        agreement_status = "not_started"
    else:
        agreement_status = "healthy" if monitor.is_healthy() else "degraded"
    return HealthStatus(
        status="healthy" if state.knowledge_graph else "no_kg",
        kg_loaded=state.knowledge_graph is not None,
        kg_signature_verified=bool(state.knowledge_graph and state.knowledge_graph.signature_verified),
        canary_status=agreement_status,
        verdicts_produced=state.verdicts_produced,
        timestamp=_now_iso(),
        runtime_version="v3",
    )


@app.post("/api/kg/load", dependencies=[Depends(require_api_key)])
async def load_kg(kg_data: Dict[str, Any]) -> Dict[str, Any]:
    """Load a Knowledge Graph supplied via API. Signature is REQUIRED."""
    if "signature" not in kg_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "KG missing signature block.")
    try:
        kg = KnowledgeGraph.from_dict(kg_data, require_signature=True)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"KG invalid: {exc}") from exc

    state.knowledge_graph = kg
    state.tag_registry = TagRegistry.from_knowledge_graph(kg)
    state.kg_version_hash = _compute_kg_version_hash(kg)

    if state.evaluator is not None:
        state.evaluator.kg_version_hash = state.kg_version_hash

    logger.info("KG (re)loaded: version=%s, rules=%d", kg.version, len(kg.rules))
    return {"status": "success", "rules_loaded": len(kg.rules), "version": kg.version}


@app.post(
    "/api/evaluate",
    response_model=V3VerdictEnvelope,
    dependencies=[Depends(require_api_key)],
)
async def evaluate(measurement: MeasurementRecord) -> V3VerdictEnvelope:
    """v3 evaluation: KG-grounded LLM → V3VerdictEnvelope.

    The evaluator validates citations against the KG snapshot before
    returning; bogus citations are mapped to NULL_UNMAPPED. PR 10c will
    wire the Symbolic Verifier so :attr:`VerifierResult` is populated with
    real agreement data — until then the result reports ``UNVERIFIABLE``.
    """
    if state.knowledge_graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No KG loaded.")
    if state.evaluator is None or state.ledger is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Service not initialised.")

    # Write to the telemetry buffer BEFORE evaluation so stateful predicates
    # in PR 10c can see the current event via subsequent queries. Same
    # ordering rationale as v2.1: write-before-evaluate guarantees replay
    # determinism for any rule that references "the current event".
    if state.telemetry_buffer is not None:
        try:
            await state.telemetry_buffer.append(
                subject=measurement.subject,
                telemetry_id=measurement.measurement_id,
                telemetry_ts=_parse_telemetry_ts(measurement.timestamp),
                measurement=measurement.measurement,
            )
        except Exception as exc:
            logger.warning("Buffer append failed for %s: %r", measurement.measurement_id, exc)

    state.verdicts_produced += 1

    # PR 11.7: scope the KG to the tenant's jurisdiction + measurement timestamp
    # before sending it to the LLM. This prevents the prompt from blowing the
    # model's context window on real-sized KGs, and records the scope in the
    # snapshot's ``scope`` field so the transcript captures *what was sent*.
    measurement_ts = _parse_telemetry_ts(measurement.timestamp)
    snapshot = state.knowledge_graph.scope_to(
        jurisdiction=measurement.jurisdiction,
        as_of=measurement_ts,
    )

    # PR 11: evaluator yields envelope + signed transcript; ledger persists both.
    # PR 11.6: subject/as_of/buffer are forwarded so stateful predicates
    # (rolling averages, window peaks) can be verified against the
    # telemetry buffer. If the buffer is None, stateful predicates degrade
    # to UNVERIFIABLE — operability problem, not a correctness one.
    result = await state.evaluator.aevaluate_with_transcript(
        measurement=measurement.measurement,
        kg_snapshot=snapshot,
        risk_tier=RiskTierGovernor.tier_for_snapshot(snapshot),
        subject=measurement.subject,
        as_of=measurement_ts,
        buffer=state.telemetry_buffer,
    )
    envelope = result.envelope

    await state.ledger.append_v3(
        envelope=envelope,
        transcript=result.transcript,
        telemetry_id=measurement.measurement_id,
        telemetry_hash=_hash_measurement(measurement),
        rule_id=_first_obligation_id(envelope),
        kg_version=state.knowledge_graph.version,
        ski_model_version=_VERSION,
        track="v3-evaluator",
    )

    # PR 12: record the verifier outcome for the agreement-rate monitor.
    if state.agreement_monitor is not None:
        state.agreement_monitor.record(envelope.verifier_result.status)

    return envelope


@app.get("/api/verdicts", dependencies=[Depends(require_api_key)])
async def list_verdicts(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    if state.ledger is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ledger not initialised.")
    entries = await state.ledger.list(limit=limit, offset=offset)
    return {
        "verdicts": entries,
        "total": state.verdicts_produced,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/canary", dependencies=[Depends(require_api_key)])
async def canary_status() -> Dict[str, Any]:
    """Neuro-symbolic agreement monitor snapshot (PR 12).

    The endpoint name is preserved from v2 for operator continuity; the
    payload shape is the v3 monitor's :meth:`AgreementMonitor.snapshot`.
    """
    if state.agreement_monitor is None:
        return {"status": "not_started"}
    snapshot = state.agreement_monitor.snapshot()
    snapshot["status"] = "healthy" if snapshot["is_healthy"] else "degraded"
    return snapshot


# ============================================================================
# Helpers
# ============================================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_telemetry_ts(value: str) -> datetime:
    """Parse telemetry timestamp; fall back to now() only if parsing fails.

    Telemetry timestamps are the authoritative clock for stateful evaluation
    (see docs/RFCs/0001-stateful-evaluation.md). A malformed timestamp is a
    producer bug; we log and degrade rather than crash.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        logger.warning("Malformed telemetry timestamp %r; falling back to wall clock.", value)
        return datetime.now(timezone.utc)


def _hash_measurement(measurement: MeasurementRecord) -> str:
    return hashlib.sha256(
        json.dumps(measurement.model_dump(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _first_obligation_id(envelope: V3VerdictEnvelope) -> Optional[str]:
    citations: List[Any] = envelope.kg_citations
    for c in citations:
        node_id = getattr(c, "node_id", None) or (c.get("node_id") if isinstance(c, dict) else None)
        if node_id:
            return str(node_id)
    return None


# ============================================================================
# Main
# ============================================================================


if __name__ == "__main__":
    workers = int(os.getenv("SKI_MODEL_WORKERS", "1"))
    if workers != 1:
        raise RuntimeError(
            "SKI_MODEL_WORKERS must be 1. See docs/CONCURRENCY.md for rationale. "
            "Scale horizontally with additional containers, not uvicorn workers."
        )

    tls_enabled = os.getenv("TLS_ENABLED", "true").lower() == "true"
    ssl_kwargs: Dict[str, Any] = {}
    if tls_enabled:
        ssl_kwargs = {
            "ssl_certfile": os.getenv("TLS_CERT", "/app/tls/ski-model.crt"),
            "ssl_keyfile": os.getenv("TLS_KEY", "/app/tls/ski-model.key"),
        }

    uvicorn.run(
        "ski_model.server:app",
        host=os.getenv("HOST", "0.0.0.0"),  # nosec B104 — container default
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        reload=False,
        **ssl_kwargs,
    )
