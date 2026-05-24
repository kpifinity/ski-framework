"""SKI Model FastAPI server — runtime inference for the SKI Framework v2.1.

This is the v0.1.0-alpha reference implementation. It demonstrates:

  * Tag-Registry-mediated rule routing (no runtime tag inference; B4.3)
  * Track 1 deterministic evaluation via the Symbolic Evaluator
  * Track 2 bounded LLM evaluation under temperature=0 (Ollama backend)
  * Knowledge Graph signature verification on load
  * Append-only audit ledger writes with hash chaining
  * Determinism canary self-check on a fixed input
  * Five-verdict taxonomy per v2.1
  * Single-worker enforcement (see docs/CONCURRENCY.md)

It is NOT production ready. See README.md for the gap list.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

# Allow execution as `python -m ski_model.server` (package mode) OR as a
# raw script via the container CMD when WORKDIR is /app.
try:
    from symbolic_evaluator import SymbolicEvaluator  # type: ignore
    from tag_registry import TagRegistry  # type: ignore
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from symbolic_evaluator import SymbolicEvaluator  # type: ignore
    from tag_registry import TagRegistry  # type: ignore

from .backends import build_backend, InferenceBackend
from .canary import DeterminismCanary
from .kg_loader import KnowledgeGraph, load_signed_kg
from .ledger_client import LedgerClient
from .verdicts import Verdict


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ski_model.server")


_VERSION = "0.2.0"


# ============================================================================
# State
# ============================================================================


class _State:
    """Process-local state. Workers MUST be 1 — see docs/CONCURRENCY.md."""

    knowledge_graph: Optional[KnowledgeGraph] = None
    tag_registry: Optional[TagRegistry] = None
    symbolic_evaluator: Optional[SymbolicEvaluator] = None
    backend: Optional[InferenceBackend] = None
    ledger: Optional[LedgerClient] = None
    canary: Optional[DeterminismCanary] = None
    telemetry_buffer: Optional[Any] = None  # v0.2 — set in lifespan when LEDGER_DSN is configured
    tenant_id: str = "default"               # v0.2 — single-tenant default
    verdicts_produced: int = 0


state = _State()


# ============================================================================
# Request / response models
# ============================================================================


class TelemetryRecord(BaseModel):
    telemetry_id: str
    timestamp: str  # ISO-8601 UTC
    subject: str  # The raw subject as emitted by the data source
    measurement: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured measurement values. The producer MUST NOT include "
            "a rule_id — rule selection is performed by the Tag Registry."
        ),
    )


class VerdictResponse(BaseModel):
    verdict_id: str
    telemetry_id: str
    verdict: Verdict
    rule_id: Optional[str] = None
    track: Optional[str] = None  # "symbolic" | "llm" | None for NULL_UNMAPPED
    reasoning: str
    kg_version: Optional[str] = None
    ski_model_version: str
    timestamp: str


class HealthStatus(BaseModel):
    status: str
    kg_loaded: bool
    kg_signature_verified: bool
    canary_status: str
    verdicts_produced: int
    timestamp: str


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
# Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Replaces deprecated @app.on_event handlers (FastAPI ≥0.93)."""
    logger.info("SKI Model starting (v%s)", _VERSION)

    kg_path = Path(os.getenv("KG_PATH", "/app/kg/kg.json"))
    require_sig = os.getenv("KG_REQUIRE_SIGNATURE", "true").lower() == "true"
    try:
        state.knowledge_graph = load_signed_kg(kg_path, require_signature=require_sig)
        logger.info(
            "KG loaded: version=%s rules=%d signature_verified=%s",
            state.knowledge_graph.version,
            len(state.knowledge_graph.rules),
            state.knowledge_graph.signature_verified,
        )
    except FileNotFoundError:
        logger.warning("No Knowledge Graph at %s. /api/kg/load can supply one.", kg_path)

    if state.knowledge_graph is not None:
        state.tag_registry = TagRegistry.from_knowledge_graph(state.knowledge_graph)

    state.symbolic_evaluator = SymbolicEvaluator()
    state.backend = build_backend()
    state.ledger = LedgerClient(os.getenv("LEDGER_DSN", ""))
    await state.ledger.initialize()

    # v0.2 telemetry buffer — reuses the LedgerClient's engine when possible
    # so we don't open a second connection pool. Falls back to a no-op when
    # LEDGER_DSN is unset (tests / smoke runs).
    state.tenant_id = os.getenv("SKI_TENANT_ID", "default")
    try:
        from telemetry_buffer import TelemetryBuffer  # type: ignore
        if state.ledger is not None and state.ledger._engine is not None:  # noqa: SLF001
            state.telemetry_buffer = TelemetryBuffer(
                state.ledger._engine,  # noqa: SLF001 — intentional reuse
                tenant_id=state.tenant_id,
            )
            logger.info("Telemetry buffer ready (tenant=%s).", state.tenant_id)
    except Exception as exc:  # pragma: no cover — buffer is best-effort wiring
        logger.warning("Telemetry buffer not initialised (%s); stateful predicates will return DISCRETIONARY.", exc)

    state.canary = DeterminismCanary(
        backend=state.backend,
        interval_seconds=int(os.getenv("DETERMINISM_CANARY_INTERVAL", "300")),
    )
    canary_task = asyncio.create_task(state.canary.run())

    logger.info("SKI Model ready (backend=%s)", state.backend.name)

    try:
        yield
    finally:
        canary_task.cancel()
        try:
            await canary_task
        except asyncio.CancelledError:
            pass
        await state.ledger.close()
        logger.info("SKI Model stopping (verdicts_produced=%d)", state.verdicts_produced)


# ============================================================================
# App
# ============================================================================


app = FastAPI(title="SKI Model Inference Engine", version=_VERSION, lifespan=lifespan)


@app.get("/api/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    return HealthStatus(
        status="healthy" if state.knowledge_graph else "no_kg",
        kg_loaded=state.knowledge_graph is not None,
        kg_signature_verified=bool(
            state.knowledge_graph and state.knowledge_graph.signature_verified
        ),
        canary_status=state.canary.last_status if state.canary else "not_started",
        verdicts_produced=state.verdicts_produced,
        timestamp=_now_iso(),
    )


@app.post("/api/kg/load", dependencies=[Depends(require_api_key)])
async def load_kg(kg_data: dict[str, Any]) -> dict[str, Any]:
    """Load a Knowledge Graph supplied via API. Signature is REQUIRED."""
    if "signature" not in kg_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "KG missing signature block.")
    try:
        kg = KnowledgeGraph.from_dict(kg_data, require_signature=True)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"KG invalid: {exc}") from exc

    state.knowledge_graph = kg
    state.tag_registry = TagRegistry.from_knowledge_graph(kg)
    logger.info("KG (re)loaded: version=%s, rules=%d", kg.version, len(kg.rules))
    return {"status": "success", "rules_loaded": len(kg.rules), "version": kg.version}


@app.post(
    "/api/evaluate",
    response_model=VerdictResponse,
    dependencies=[Depends(require_api_key)],
)
async def evaluate(telemetry: TelemetryRecord) -> VerdictResponse:
    if state.knowledge_graph is None or state.tag_registry is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No KG loaded.")
    if state.backend is None or state.symbolic_evaluator is None or state.ledger is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Service not initialised."
        )

    # 0. v0.2 — write to the telemetry buffer BEFORE evaluation so stateful
    #    predicates on this very record can see it via subsequent queries.
    #    Note: by ordering write-before-evaluate we guarantee replay
    #    determinism (any rule that references "the current event" sees it).
    if state.telemetry_buffer is not None:
        try:
            await state.telemetry_buffer.append(
                subject=telemetry.subject,
                telemetry_id=telemetry.telemetry_id,
                telemetry_ts=_parse_telemetry_ts(telemetry.timestamp),
                measurement=telemetry.measurement,
            )
        except Exception as exc:
            # The buffer being down is a degraded-operation event, not a
            # reason to refuse evaluation. Stateful predicates will return
            # DISCRETIONARY because the buffer queries will fail; stateless
            # predicates still work correctly.
            logger.warning("Buffer append failed for %s: %r", telemetry.telemetry_id, exc)

    # 1. Tag Registry resolves subject → rule. Pure lookup; no inference.
    rule = state.tag_registry.resolve(telemetry.subject)
    if rule is None:
        return await _record_verdict(
            telemetry=telemetry,
            verdict=Verdict.NULL_UNMAPPED,
            rule=None,
            track=None,
            reasoning=(
                f"Subject {telemetry.subject!r} is not present in the Tag "
                f"Registry compiled from KG {state.knowledge_graph.version}. "
                "Coverage gap logged."
            ),
        )

    # 2. Route by rule track.
    track = rule.get("track", "symbolic")
    if track == "symbolic":
        # v0.2 — use the async evaluator with the buffer for stateful predicates.
        decision = await state.symbolic_evaluator.aevaluate(
            rule,
            telemetry.model_dump(),
            buffer=state.telemetry_buffer,
            as_of=_parse_telemetry_ts(telemetry.timestamp),
        )
        return await _record_verdict(
            telemetry=telemetry,
            verdict=decision.verdict,
            rule=rule,
            track="symbolic",
            reasoning=decision.reasoning,
        )

    if track == "llm":
        decision = await state.backend.evaluate(rule, telemetry.model_dump())
        return await _record_verdict(
            telemetry=telemetry,
            verdict=decision.verdict,
            rule=rule,
            track="llm",
            reasoning=decision.reasoning,
        )

    return await _record_verdict(
        telemetry=telemetry,
        verdict=Verdict.NULL_UNMAPPED,
        rule=rule,
        track=None,
        reasoning=f"Rule {rule.get('id')} has unknown track {track!r}.",
    )


async def _record_verdict(
    *,
    telemetry: TelemetryRecord,
    verdict: Verdict,
    rule: Optional[dict[str, Any]],
    track: Optional[str],
    reasoning: str,
) -> VerdictResponse:
    assert state.ledger is not None
    state.verdicts_produced += 1
    verdict_id = f"verdict_{state.verdicts_produced:012d}"

    telemetry_hash = hashlib.sha256(
        json.dumps(
            telemetry.model_dump(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    await state.ledger.append(
        verdict=verdict,
        telemetry_id=telemetry.telemetry_id,
        telemetry_hash=telemetry_hash,
        rule_id=rule.get("id") if rule else None,
        kg_version=state.knowledge_graph.version if state.knowledge_graph else None,
        ski_model_version=_VERSION,
        reasoning=reasoning,
        track=track,
    )

    return VerdictResponse(
        verdict_id=verdict_id,
        telemetry_id=telemetry.telemetry_id,
        verdict=verdict,
        rule_id=rule.get("id") if rule else None,
        track=track,
        reasoning=reasoning,
        kg_version=state.knowledge_graph.version if state.knowledge_graph else None,
        ski_model_version=_VERSION,
        timestamp=_now_iso(),
    )


@app.get("/api/verdicts", dependencies=[Depends(require_api_key)])
async def list_verdicts(limit: int = 100, offset: int = 0) -> dict[str, Any]:
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
async def canary_status() -> dict[str, Any]:
    if state.canary is None:
        return {"status": "not_started"}
    return state.canary.snapshot()


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
    ssl_kwargs: dict[str, Any] = {}
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
