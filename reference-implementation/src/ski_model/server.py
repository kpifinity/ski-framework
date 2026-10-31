"""SKI Model FastAPI server — runtime inference for the SKI Framework v3.

The v3 architecture inverts the v2 control flow. A KG-grounded LLM is the
primary evaluator; the Symbolic Verifier (PR 10c) mechanically cross-checks
its formalizable assertions. PR 10b ships the evaluator path end-to-end with
a deterministic ``FakeLLM`` backend so CI exercises the full plumbing without
secrets.

Endpoints:

  POST /api/evaluate      — v3 inference; returns a V3VerdictEnvelope.
  POST /api/kg/load       — hot-load a signed Knowledge Graph (disabled unless
                            SKI_ENABLE_KG_HOT_LOAD=true; needs SKI_ADMIN_API_KEY).
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
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Final, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Allow execution as `python -m ski_model.server` (package mode) OR as a
# raw script via the container CMD when WORKDIR is /app.
try:
    from symbolic_evaluator import SymbolicEvaluator
    from tag_registry import RiskTierGovernor, TagRegistry
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from symbolic_evaluator import SymbolicEvaluator
    from tag_registry import RiskTierGovernor, TagRegistry

from ski_schemas.canonical import CanonicalizationError, canonicalize, sha256_canonical
from ski_schemas.measurement import MeasurementRecord

from . import metrics, sovereignty
from .kg_loader import KGTrustPolicy, KnowledgeGraph, load_signed_kg
from .ledger_client import LedgerClient
from .ledger_migrations import ensure_v3_ledger_schema
from .v3 import (
    AgreementMonitor,
    ModelProvenance,
    TranscriptSigner,
    V3Evaluator,
    V3LLMBackend,
    V3Verdict,
    V3VerdictEnvelope,
    VerifierResult,
    VerifierStatus,
)
from .v3 import (
    build_backend as build_v3_backend,
)
from .v3.backends import resolve_backend_name
from .v3.signing import TranscriptKeyError, transcript_key_path
from .v3.verifier import measurement_input_errors

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ski_model.server")


_VERSION = "3.2.0"

# Safe default when no tenant row and no SKI_MAX_CLOCK_SKEW_SECONDS override
# are available; matches the telemetry_buffer.sql `tenants` column default.
_DEFAULT_MAX_CLOCK_SKEW_SECONDS: Final[int] = 60


# ============================================================================
# State
# ============================================================================


class _State:
    """Process-local state. Workers MUST be 1 — see docs/CONCURRENCY.md."""

    knowledge_graph: Optional[KnowledgeGraph] = None
    # SKI_KG_TRUST_ANCHORS / SKI_KG_ALLOW_UNANCHORED, resolved once at startup.
    kg_trust_policy: Optional[KGTrustPolicy] = None
    tag_registry: Optional[TagRegistry] = None
    symbolic_evaluator: Optional[SymbolicEvaluator] = None
    ledger: Optional[LedgerClient] = None
    telemetry_buffer: Optional[Any] = None
    tenant_id: str = "default"
    verdicts_produced: int = 0
    max_clock_skew_seconds: int = _DEFAULT_MAX_CLOCK_SKEW_SECONDS

    # v3 evaluator state
    llm_backend: Optional[V3LLMBackend] = None
    evaluator: Optional[V3Evaluator] = None
    kg_version_hash: str = "sha256:" + "0" * 64
    transcript_signer: Optional[TranscriptSigner] = None
    agreement_monitor: Optional[AgreementMonitor] = None

    # Spec §6: the startup report and the evaluation-path egress guard.
    sovereignty_mode: str = sovereignty.STRICT
    sovereignty_checks: tuple[sovereignty.Check, ...] = ()
    egress_guard: Optional[sovereignty.EgressGuard] = None
    ledger_role: Optional[str] = None


state = _State()


# ============================================================================
# Request / response models
# ============================================================================


# MeasurementRecord moved to ski-schemas (RFC 0003 PR 1); imported above.


class HealthStatus(BaseModel):
    status: str
    kg_loaded: bool
    kg_signature_verified: bool
    canary_status: str
    verdicts_produced: int
    timestamp: str
    runtime_version: str
    # v3.2.0: what is actually serving verdicts and under what trust. Keys:
    # backend provenance (backend, model_id, model_weight_hash,
    # model_hash_verified, model_hash_source) merged with KG-trust provenance
    # (kg_version_hash, kg_signer_key_id, kg_trust, transcript_key_id). Additive.
    provenance: Dict[str, Any] = Field(default_factory=dict)


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


# KG hot-load (framework v3.2.0). Off by default; when on, it is gated by a
# separate admin key, never API_KEY (which the sidecar holds), and every
# hot-loaded KG passes the same trust-anchor check as the startup KG.
_KG_HOT_LOAD_ENV: Final[str] = "SKI_ENABLE_KG_HOT_LOAD"
_ADMIN_API_KEY_ENV: Final[str] = "SKI_ADMIN_API_KEY"
_ADMIN_KEY_HEADER: Final[str] = "X-SKI-Admin-Key"


def _kg_hot_load_enabled() -> bool:
    return os.getenv(_KG_HOT_LOAD_ENV, "false").strip().lower() == "true"


def _kg_admin_api_key() -> str:
    """Return the hot-load admin key; raise RuntimeError if it is unusable."""
    admin_key = os.getenv(_ADMIN_API_KEY_ENV, "")
    if not admin_key:
        raise RuntimeError(f"{_KG_HOT_LOAD_ENV}=true requires {_ADMIN_API_KEY_ENV} to be set.")
    if _API_KEY and secrets.compare_digest(admin_key.encode(), _API_KEY.encode()):
        raise RuntimeError(f"{_ADMIN_API_KEY_ENV} must differ from API_KEY (the key the sidecar holds).")
    return admin_key


async def require_kg_admin(x_ski_admin_key: Optional[str] = Header(default=None)) -> None:
    if not _kg_hot_load_enabled():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"KG hot-load is disabled. Set {_KG_HOT_LOAD_ENV}=true and {_ADMIN_API_KEY_ENV} to enable it.",
        )
    try:
        admin_key = _kg_admin_api_key()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Server misconfiguration: {exc}") from None
    if not x_ski_admin_key or not secrets.compare_digest(x_ski_admin_key.encode(), admin_key.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid or missing {_ADMIN_KEY_HEADER}.")


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
    """sha256 of the spec §7.3 canonical KG payload — recorded in ModelProvenance.

    A graph KG hashes its signed ``{metadata, nodes, edges}`` content, so an
    auditor recomputes the value from the KG file; a flat (compatibility)
    KG hashes ``{version, rules, tag_registry}``. Raises
    :class:`CanonicalizationError` for a KG that has no canonical form.
    """
    if kg.graph is not None:
        return sha256_canonical(kg.graph)
    return sha256_canonical(
        {
            "version": kg.version,
            "rules": kg.rules,
            "tag_registry": kg.tag_registry,
        }
    )


async def _ledger_has_signed_transcripts(engine: Optional[AsyncEngine]) -> bool:
    """True when ``ledger_entries`` already holds a signed transcript.

    Asked only when the transcript key file is missing. If the ledger cannot
    answer, it is not safe to treat this as a first boot, so this raises.
    """
    try:
        if engine is None:
            raise RuntimeError("ledger engine not initialised")
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM ledger_entries WHERE transcript_signature IS NOT NULL LIMIT 1")
                )
            ).first()
    except Exception as exc:
        raise TranscriptKeyError(
            "The transcript signing key is missing and the audit ledger could not be checked "
            f"for existing signed transcripts ({exc!r}). Refusing to generate a new key."
        ) from exc
    return row is not None


def _trust_provenance() -> Dict[str, Any]:
    """The KG-trust and transcript-key half of /api/health ``provenance``."""
    kg = state.knowledge_graph
    policy = state.kg_trust_policy
    signer = state.transcript_signer
    return {
        "kg_version_hash": state.kg_version_hash if kg is not None else None,
        "kg_signer_key_id": kg.signer_key_id if kg is not None else None,
        "kg_trust": kg.kg_trust if kg is not None else None,
        "kg_trust_anchors": list(policy.anchor_key_ids) if policy is not None else [],
        "transcript_key_id": signer.key_id if signer is not None else None,
    }


async def _init_telemetry_buffer(engine: Optional[AsyncEngine], tenant_id: str) -> Optional[Any]:
    """The telemetry buffer, or None when it is not provisioned (each reason logged).

    Without it, stateful predicates degrade to UNVERIFIABLE and the
    freshness gate to DISCRETIONARY + human attestation: degraded, never
    CLEAR. ``telemetry_buffer.sql`` provisions it (docs/migrations.md).
    """
    if engine is None:
        return None
    try:
        from telemetry_buffer import TelemetryBuffer

        async with engine.connect() as conn:
            table = (await conn.execute(text("SELECT to_regclass('telemetry_buffer')"))).scalar()
            tenant = (
                (
                    await conn.execute(text("SELECT 1 FROM tenants WHERE tenant_id = :t"), {"t": tenant_id})
                ).scalar()
                if table is not None
                else None
            )
    except Exception as exc:
        logger.warning("Telemetry buffer not initialised (%r); stateful predicates will degrade.", exc)
        return None
    if table is None or tenant is None:
        logger.warning(
            "Telemetry buffer not initialised: %s. Stateful predicates degrade to UNVERIFIABLE and the "
            "freshness gate to DISCRETIONARY until reference-implementation/src/ledger/telemetry_buffer.sql "
            "is applied as the schema owner (docs/migrations.md).",
            "no telemetry_buffer table" if table is None else f"no row for tenant {tenant_id!r} in tenants",
        )
        return None
    logger.info("Telemetry buffer ready (tenant=%s).", tenant_id)
    return TelemetryBuffer(engine, tenant_id=tenant_id)


async def _resolve_max_clock_skew_seconds(engine: Optional[AsyncEngine], tenant_id: str) -> int:
    """Resolve the acceptable telemetry clock-skew bound for ``tenant_id``.

    Precedence: the ``tenants.max_clock_skew_seconds`` row when set (the
    schema's intended source of truth — see ``reference-implementation/src/
    ledger/telemetry_buffer.sql``), then ``SKI_MAX_CLOCK_SKEW_SECONDS``, then
    :data:`_DEFAULT_MAX_CLOCK_SKEW_SECONDS`. A NULL column (the seeded
    ``default`` tenant) is "not set for this tenant". A resolved value of
    ``0`` disables the guard entirely (documented operator opt-out).
    """
    if engine is not None:
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT max_clock_skew_seconds FROM tenants WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
                    )
                ).first()
            if row is not None and row[0] is not None:
                return int(row[0])
        except Exception as exc:  # pragma: no cover — DB best-effort, same posture as buffer init
            logger.warning(
                "Could not resolve tenants.max_clock_skew_seconds for tenant=%s (%r); "
                "falling back to SKI_MAX_CLOCK_SKEW_SECONDS / default.",
                tenant_id,
                exc,
            )

    env_value = os.getenv("SKI_MAX_CLOCK_SKEW_SECONDS")
    if env_value is not None:
        try:
            return int(env_value)
        except ValueError:
            logger.warning(
                "Invalid SKI_MAX_CLOCK_SKEW_SECONDS=%r; using default %ds.",
                env_value,
                _DEFAULT_MAX_CLOCK_SKEW_SECONDS,
            )

    return _DEFAULT_MAX_CLOCK_SKEW_SECONDS


def _build_v3_llm_backend() -> V3LLMBackend:
    """Select the v3 LLM backend.

    Delegates to :func:`ski_model.v3.backends.build_backend`. ``SKI_V3_LLM_BACKEND``
    (alias ``SKI_INFERENCE_BACKEND``) controls the selection: ``"ollama"``,
    ``"vllm"`` or ``"fake"`` (the default when unset, refused unless
    ``SKI_ALLOW_FAKE_LLM=true``). Any configuration error, or a model
    weight-hash pin that cannot be honoured, raises here so the runtime
    refuses to start. Additional backends extend the factory without
    touching the server.
    """
    return build_v3_backend()


def _backend_provenance(backend: Optional[V3LLMBackend]) -> Dict[str, Any]:
    """The backend half of ``/api/health``'s ``provenance`` object."""
    if backend is None:
        return {
            "backend": None,
            "model_id": None,
            "model_weight_hash": None,
            "model_hash_verified": False,
            "model_hash_source": None,
        }
    name = str(getattr(backend, "name", type(backend).__name__))
    return {
        "backend": name,
        "model_id": str(getattr(backend, "model_id", name)),
        "model_weight_hash": backend.model_weight_hash,
        "model_hash_verified": getattr(backend, "model_hash_verified", False) is True,
        "model_hash_source": getattr(backend, "model_hash_source", "unspecified"),
    }


# ============================================================================
# Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Replaces deprecated @app.on_event handlers (FastAPI ≥0.93)."""
    logger.info("SKI Model starting (v%s, runtime=v3)", _VERSION)

    # Framework v3.2.0: KG trust anchors (spec §2.1.2, §3.5). An invalid
    # SKI_KG_TRUST_ANCHORS bundle refuses to start; it never degrades.
    state.kg_trust_policy = KGTrustPolicy.from_env()
    logger.info("KG trust policy: %s", state.kg_trust_policy.describe())

    # Spec §6.2: decide the configuration-only requirements before the model
    # backend or the ledger is contacted, so strict mode never calls out to
    # a destination it is about to reject. Each later stage refuses before
    # the next dependency is contacted.
    state.sovereignty_mode = sovereignty.resolve_mode(os.environ)
    backend_name = resolve_backend_name()
    checks = [
        *sovereignty.config_checks(
            backend=backend_name,
            env=os.environ,
            trust_anchor_count=len(state.kg_trust_policy.anchors),
            unanchored=state.kg_trust_policy.allow_unanchored,
        ),
        *sovereignty.runtime_checks(os.environ),
    ]
    sovereignty.refuse_if_failed(state.sovereignty_mode, checks)
    if _kg_hot_load_enabled():
        _kg_admin_api_key()  # refuse to start with an unusable admin key
        logger.warning(
            "KG hot-load ENABLED (%s=true): POST /api/kg/load accepts anchored KGs.", _KG_HOT_LOAD_ENV
        )

    kg_path = Path(os.getenv("KG_PATH", "/app/kg/kg.json"))
    require_sig = os.getenv("KG_REQUIRE_SIGNATURE", "true").lower() == "true"
    try:
        state.knowledge_graph = load_signed_kg(
            kg_path, require_signature=require_sig, trust=state.kg_trust_policy
        )
        state.kg_version_hash = _compute_kg_version_hash(state.knowledge_graph)
        logger.info(
            "KG loaded: version=%s rules=%d signature_verified=%s kg_trust=%s signer=%s kg_hash=%s",
            state.knowledge_graph.version,
            len(state.knowledge_graph.rules),
            state.knowledge_graph.signature_verified,
            state.knowledge_graph.kg_trust,
            state.knowledge_graph.signer_key_id,
            state.kg_version_hash[:16] + "…",
        )
    except FileNotFoundError:
        logger.warning("No Knowledge Graph at %s. /api/kg/load can supply one.", kg_path)

    metrics.KG_SIGNATURE_VERIFIED.set(
        1 if (state.knowledge_graph is not None and state.knowledge_graph.signature_verified) else 0
    )

    if state.knowledge_graph is not None:
        state.tag_registry = TagRegistry.from_knowledge_graph(state.knowledge_graph)
    checks.append(
        sovereignty.kg_anchored_check(
            state.knowledge_graph is not None,
            state.knowledge_graph.kg_trust if state.knowledge_graph is not None else None,
        )
    )
    sovereignty.refuse_if_failed(state.sovereignty_mode, checks)

    state.symbolic_evaluator = SymbolicEvaluator()
    state.llm_backend = _build_v3_llm_backend()
    backend_prov = _backend_provenance(state.llm_backend)
    logger.info(
        "Inference backend: backend=%s model_id=%s model_weight_hash=%s model_hash_verified=%s (source=%s)",
        backend_prov["backend"],
        backend_prov["model_id"],
        backend_prov["model_weight_hash"],
        backend_prov["model_hash_verified"],
        backend_prov["model_hash_source"],
    )
    checks += [
        sovereignty.model_hash_check(backend_prov["model_hash_source"]),
        sovereignty.model_hash_verified_check(
            backend_prov["model_hash_verified"], backend_prov["model_hash_source"]
        ),
    ]
    sovereignty.refuse_if_failed(state.sovereignty_mode, checks)

    # The ledger comes up before the transcript signer: a missing signing key
    # is only a first boot if the ledger holds no signed transcripts yet.
    state.ledger = LedgerClient(os.getenv("LEDGER_DSN", ""))
    await state.ledger.initialize()
    # PR 16 (v3.0.2): probe ledger_entries for the v3 audit-trail columns
    # and apply migrations/0002_transcript_columns.sql in place if missing.
    # Idempotent. Closes the gap where Postgres' /docker-entrypoint-initdb.d/
    # only runs on first init — operators upgrading on top of an existing
    # volume would otherwise hit "column envelope_json does not exist" at
    # evaluation time. Set SKI_AUTOMIGRATE=false to opt out.
    if state.ledger._engine is not None:
        await ensure_v3_ledger_schema(state.ledger._engine)
    ledger_check, state.ledger_role = await sovereignty.ledger_role_check(state.ledger._engine)
    checks.append(ledger_check)
    state.sovereignty_checks = tuple(checks)
    sovereignty.enforce(state.sovereignty_mode, checks)

    key_path = transcript_key_path()
    ledger_has_signed = False
    if not key_path.exists():
        ledger_has_signed = await _ledger_has_signed_transcripts(state.ledger._engine)
    state.transcript_signer = TranscriptSigner.auto_provision(
        key_path, ledger_has_signed_transcripts=ledger_has_signed
    )
    logger.info("Transcript signer ready (key_id=%s)", state.transcript_signer.key_id)
    kg = state.knowledge_graph
    state.evaluator = V3Evaluator(
        llm=state.llm_backend,
        kg_version_hash=state.kg_version_hash,
        decoder_seed=int(os.getenv("SKI_MODEL_SEED", "0")),
        signer=state.transcript_signer,
        kg_signer_key_id=kg.signer_key_id if kg is not None else None,
        kg_trust=kg.kg_trust if kg is not None else None,
    )

    state.tenant_id = os.getenv("SKI_TENANT_ID", "default")
    state.max_clock_skew_seconds = await _resolve_max_clock_skew_seconds(
        state.ledger._engine if state.ledger is not None else None,
        state.tenant_id,
    )
    logger.info(
        "Telemetry clock-skew guard: max_clock_skew_seconds=%d (0 disables), mode=%s.",
        state.max_clock_skew_seconds,
        _clock_skew_mode(),
    )
    state.telemetry_buffer = await _init_telemetry_buffer(
        state.ledger._engine if state.ledger is not None else None, state.tenant_id
    )

    # PR 12: neuro-symbolic agreement monitor replaces the v2 determinism
    # canary. Tracks the rolling LLM↔verifier agreement rate across the
    # last SKI_AGREEMENT_WINDOW evaluations; pages when the rate dips
    # below SKI_AGREEMENT_THRESHOLD.
    state.agreement_monitor = AgreementMonitor(
        window_size=int(os.getenv("SKI_AGREEMENT_WINDOW", "1000")),
        threshold=float(os.getenv("SKI_AGREEMENT_THRESHOLD", "0.95")),
    )

    # Startup is done: from here on the whole process may reach only
    # loopback, the ledger and the LLM backend (spec §6.3).
    state.egress_guard = sovereignty.install_egress_guard(
        sovereignty.EgressGuard(
            state.sovereignty_mode, sovereignty.egress_allowlist(backend_name, os.environ)
        ).arm()
    )
    logger.info("Egress guard armed: %s", state.egress_guard.state())

    metrics.RUNTIME_INFO.labels(version=_VERSION, backend=state.llm_backend.name).set(1)
    metrics.AGREEMENT_RATE.set(1.0)  # empty window == no observed disagreement

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
        provenance={**_backend_provenance(state.llm_backend), **_trust_provenance()},
    )


@app.post("/api/kg/load", dependencies=[Depends(require_kg_admin)])
async def load_kg(kg_data: Dict[str, Any]) -> Dict[str, Any]:
    """Hot-load a Knowledge Graph supplied via API.

    Disabled unless ``SKI_ENABLE_KG_HOT_LOAD=true``; then requires the
    ``X-SKI-Admin-Key`` header to match ``SKI_ADMIN_API_KEY``. Signature is
    REQUIRED and must verify against a configured trust anchor (or, with no
    anchors, the explicit ``SKI_KG_ALLOW_UNANCHORED=true`` dev mode).
    """
    if "signature" not in kg_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "KG missing signature block.")
    try:
        policy = state.kg_trust_policy if state.kg_trust_policy is not None else KGTrustPolicy.from_env()
        kg = KnowledgeGraph.from_dict(kg_data, require_signature=True, trust=policy)
        kg_version_hash = _compute_kg_version_hash(kg)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"KG invalid: {exc}") from exc

    state.knowledge_graph = kg
    state.tag_registry = TagRegistry.from_knowledge_graph(kg)
    state.kg_version_hash = kg_version_hash

    if state.evaluator is not None:
        state.evaluator.kg_version_hash = state.kg_version_hash
        state.evaluator.kg_signer_key_id = kg.signer_key_id
        state.evaluator.kg_trust = kg.kg_trust

    metrics.KG_SIGNATURE_VERIFIED.set(1 if kg.signature_verified else 0)
    logger.warning(
        "KG hot-loaded via /api/kg/load: version=%s, rules=%d, kg_trust=%s, signer=%s",
        kg.version,
        len(kg.rules),
        kg.kg_trust,
        kg.signer_key_id,
    )
    return {
        "status": "success",
        "rules_loaded": len(kg.rules),
        "version": kg.version,
        "kg_signer_key_id": kg.signer_key_id,
        "kg_trust": kg.kg_trust,
    }


@app.post(
    "/api/evaluate",
    response_model=V3VerdictEnvelope,
    dependencies=[Depends(require_api_key)],
)
async def evaluate(measurement: MeasurementRecord) -> V3VerdictEnvelope:
    """v3 evaluation: KG-grounded LLM → V3VerdictEnvelope.

    The evaluator validates citations against the KG snapshot before
    returning; bogus citations are mapped to NULL_UNMAPPED. The Symbolic
    Verifier mechanically cross-checks every formalizable assertion the
    LLM emits and populates :attr:`VerifierResult` with the real agreement
    outcome (``AGREED`` / ``LLM_CONTRADICTION`` / ``NEURO_SYMBOLIC_DIVERGENCE``
    / ``UNVERIFIABLE``); the risk-tier policy then decides whether a
    disagreeing result may still pass through or must downgrade to
    ``DISCRETIONARY``.

    The process runs under the spec §6.3 egress guard: in strict sovereignty
    mode one network call outside the egress allowlist stops all further
    evaluation (``503``) until the runtime is restarted.
    """
    guard = state.egress_guard
    if guard is not None and guard.tripped:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Evaluation refused: {guard.attempts} egress attempt(s) outside the allowlist "
            "(SKI_SOVEREIGNTY=strict, spec §6.3). Investigate ski_egress_attempts_total and restart.",
        )
    return await _evaluate(measurement)


async def _evaluate(measurement: MeasurementRecord) -> V3VerdictEnvelope:
    """The evaluation itself; :func:`evaluate` refuses it once the egress guard has tripped."""
    if state.knowledge_graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No KG loaded.")
    if state.evaluator is None or state.ledger is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Service not initialised.")
    _eval_started = datetime.now(timezone.utc)
    metrics.LAST_TELEMETRY_TS.set(_eval_started.timestamp())
    telemetry_ts = _parse_telemetry_ts(measurement.timestamp)
    # v3.2.0 (finding C1): non-finite numbers anywhere, and booleans where a
    # KG obligation expects a number, are rejected before anything is
    # buffered, scoped or evaluated.
    input_errors = measurement_input_errors(measurement.measurement, state.knowledge_graph.rules)
    if input_errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(input_errors))
    # The ledger's telemetry_hash and the buffer row's measurement_hash are
    # this one value, so replay can join them. A record with no canonical
    # form (an integer a double cannot hold, a lone surrogate) cannot be
    # hashed into the ledger and is rejected here, before anything runs.
    try:
        telemetry_hash = _hash_measurement(measurement)
    except CanonicalizationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"measurement has no canonical JSON form (spec §7.3): {exc}",
        ) from exc

    # Clock-skew guard (docs/threat-model.md "Assumption 2"). The telemetry
    # timestamp is authoritative for stateful predicates and freshness
    # gates — but that only holds if it is honest. A forged or badly
    # drifted timestamp can make stale/fabricated data appear current,
    # defeating NULL_STALE routing, requires_recent_within_seconds, and
    # window predicates. Checked before the buffer write and KG scoping so
    # a rejected record is never treated as fresh or persisted as such.
    skew_seconds = _clock_skew_delta_seconds(telemetry_ts, _eval_started)
    if state.max_clock_skew_seconds > 0 and skew_seconds > state.max_clock_skew_seconds:
        metrics.TELEMETRY_CLOCK_SKEW.inc()
        skew_note = (
            f"clock_skew: telemetry Δ{skew_seconds:.1f}s exceeds "
            f"max_clock_skew_seconds={state.max_clock_skew_seconds}"
        )
        logger.warning(
            "Clock skew guard triggered for %s (subject=%s): %s",
            measurement.measurement_id,
            measurement.subject,
            skew_note,
        )
        if _clock_skew_mode() == "reject":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, skew_note)

        # Fail-closed + auditable: never silently drop. The record is
        # routed to DISCRETIONARY and ledgered, but is NOT written into
        # the telemetry buffer as a fresh sample, and never reaches the
        # evaluator/LLM.
        state.verdicts_produced += 1
        skew_envelope = _build_clock_skew_envelope(
            skew_note=skew_note,
            kg_version_hash=state.kg_version_hash,
            kg=state.knowledge_graph,
        )
        await state.ledger.append_v3(
            envelope=skew_envelope,
            transcript=None,
            telemetry_id=measurement.measurement_id,
            telemetry_hash=telemetry_hash,
            rule_id=None,
            kg_version=state.knowledge_graph.version,
            ski_model_version=_VERSION,
            track="v3-clock-skew-guard",
        )
        metrics.VERDICTS.labels(
            verdict=getattr(skew_envelope.verdict, "value", str(skew_envelope.verdict))
        ).inc()
        metrics.EVALUATION_SECONDS.observe((datetime.now(timezone.utc) - _eval_started).total_seconds())
        return skew_envelope

    # Write to the telemetry buffer BEFORE evaluation so the verifier's
    # stateful predicates (must_average_within, must_not_exceed_in_window)
    # can see the current event via subsequent queries. Same ordering
    # rationale as v2.1: write-before-evaluate guarantees replay
    # determinism for any rule that references "the current event".
    if state.telemetry_buffer is not None:
        try:
            await state.telemetry_buffer.append(
                subject=measurement.subject,
                telemetry_id=measurement.measurement_id,
                telemetry_ts=telemetry_ts,
                measurement=measurement.measurement,
                measurement_hash=telemetry_hash,
            )
        except Exception as exc:
            logger.warning("Buffer append failed for %s: %r", measurement.measurement_id, exc)

    state.verdicts_produced += 1

    # PR 11.7: scope the KG to the tenant's jurisdiction + measurement timestamp
    # before sending it to the LLM. This prevents the prompt from blowing the
    # model's context window on real-sized KGs, and records the scope in the
    # snapshot's ``scope`` field so the transcript captures *what was sent*.
    measurement_ts = telemetry_ts
    snapshot = state.knowledge_graph.scope_to(
        jurisdiction=measurement.jurisdiction,
        as_of=measurement_ts,
    )

    # PR 11: evaluator yields envelope + signed transcript; ledger persists both.
    # PR 11.6: subject/as_of/buffer are forwarded so stateful predicates
    # (rolling averages, window peaks) can be verified against the
    # telemetry buffer. If the buffer is None, stateful predicates degrade
    # to UNVERIFIABLE — operability problem, not a correctness one.
    effective_tier = RiskTierGovernor.tier_for_snapshot(snapshot)
    result = await state.evaluator.aevaluate_with_transcript(
        measurement=measurement.measurement,
        kg_snapshot=snapshot,
        risk_tier=effective_tier,
        subject=measurement.subject,
        as_of=measurement_ts,
        buffer=state.telemetry_buffer,
    )
    envelope = result.envelope

    # A5 observability: UNVERIFIABLE volume by the *effective* (KG-derived)
    # tier. At tier-2/tier-3 the risk policy accepts UNVERIFIABLE with only
    # a note (spec §5.4) -- this is the series operators alert on to catch
    # sustained under-verification that isn't triggering human review.
    if envelope.verifier_result.status == VerifierStatus.UNVERIFIABLE:
        metrics.UNVERIFIABLE_BY_TIER.labels(tier=effective_tier).inc()

    await state.ledger.append_v3(
        envelope=envelope,
        transcript=result.transcript,
        telemetry_id=measurement.measurement_id,
        telemetry_hash=telemetry_hash,
        rule_id=_first_obligation_id(envelope),
        kg_version=state.knowledge_graph.version,
        ski_model_version=_VERSION,
        track="v3-evaluator",
    )

    # PR 12: record the verifier outcome for the agreement-rate monitor.
    if state.agreement_monitor is not None:
        state.agreement_monitor.record(envelope.verifier_result.status)
        snapshot = state.agreement_monitor.snapshot()
        rate = snapshot.get("agreement_rate")
        if rate is not None:
            metrics.AGREEMENT_RATE.set(float(rate))

    metrics.VERDICTS.labels(verdict=getattr(envelope.verdict, "value", str(envelope.verdict))).inc()
    metrics.EVALUATION_SECONDS.observe((datetime.now(timezone.utc) - _eval_started).total_seconds())
    return envelope


@app.get("/api/sovereignty")
async def sovereignty_attestation() -> Dict[str, Any]:
    """Spec §6.4: a signed statement of what this runtime is running and under which mode.

    ``signature.value_hex`` is the runtime's Ed25519 transcript key over the
    §7.3 canonical JSON of ``document``; ``signature.signing_key_id`` names
    the key, the same one that signs LLM transcripts and is recorded on every
    ledger entry, so an auditor pins it from the ledger and verifies offline
    (``ski_sdk.verify_sovereignty_attestation``).
    """
    if state.transcript_signer is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Signer not initialised.")
    backend_prov = _backend_provenance(state.llm_backend)
    guard = state.egress_guard
    kg = state.knowledge_graph
    ledger_check = next((c for c in state.sovereignty_checks if c.id == "ledger_least_privilege"), None)
    document: Dict[str, Any] = {
        "sovereignty_mode": state.sovereignty_mode,
        "strict": state.sovereignty_mode == sovereignty.STRICT,
        "checks": [asdict(c) for c in state.sovereignty_checks],
        "model_id": backend_prov["model_id"],
        "model_weight_hash": backend_prov["model_weight_hash"],
        "model_hash_verified": backend_prov["model_hash_verified"],
        "model_hash_source": backend_prov["model_hash_source"],
        "kg_version": kg.version if kg is not None else None,
        "kg_version_hash": state.kg_version_hash,
        **{k: v for k, v in _trust_provenance().items() if k in ("kg_signer_key_id", "kg_trust")},
        "egress_guard": guard.state() if guard is not None else None,
        "egress_attempts_total": guard.attempts if guard is not None else 0,
        "ledger_role": {
            "role": state.ledger_role,
            "least_privilege": ledger_check.ok if ledger_check is not None else None,
        },
        "codebase_commit_hash": os.getenv("SKI_BUILD_COMMIT") or "unknown",
        "image_digest": os.getenv("SKI_IMAGE_DIGEST") or None,
        "build_provenance_attestation": _build_provenance(),
        "runtime_version": _VERSION,
        "signed_at": _now_iso(),
    }
    return {
        "document": document,
        "signature": {
            "algorithm": "ed25519",
            "signing_key_id": state.transcript_signer.key_id,
            "public_key_pem": state.transcript_signer.public_key_pem,
            "value_hex": state.transcript_signer.sign(canonicalize(document)),
        },
    }


def _build_provenance() -> Optional[Any]:
    """The SLSA provenance at ``$SKI_BUILD_PROVENANCE`` (JSON), or None when the build supplied none."""
    path = os.getenv("SKI_BUILD_PROVENANCE")
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("SKI_BUILD_PROVENANCE=%s is unreadable (%r); attesting without it.", path, exc)
        return None


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


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus exposition. Unauthenticated by design (scrape endpoint):
    aggregate counters only — no payloads, verdict bodies, or tenant data —
    and contained by the sovereign-boundary NetworkPolicy."""
    payload, content_type = metrics.render()
    return Response(content=payload, media_type=content_type)


# ============================================================================
# Helpers
# ============================================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_telemetry_ts(value: str) -> datetime:
    """Parse the telemetry timestamp; HTTP 422 if it is malformed or has no timezone.

    Telemetry timestamps are the authoritative clock for stateful evaluation
    (see docs/RFCs/0001-stateful-evaluation.md), KG scoping and the clock-skew
    guard. Before v3.2.0 a malformed timestamp was silently replaced by the
    wall clock -- which also defeated the skew guard -- and a timezone-less
    one raised ``TypeError`` (HTTP 500). Neither is ever substituted now.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"timestamp {value!r} is not an ISO-8601 date-time.",
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"timestamp {value!r} has no timezone; send UTC ('Z') or an explicit offset.",
        )
    return parsed


def _clock_skew_mode() -> str:
    """``SKI_CLOCK_SKEW_MODE``: ``"discretionary"`` (default) or ``"reject"``.

    Read live rather than cached on :class:`_State` — it is a cheap,
    operator-facing toggle, not per-tenant configuration.
    """
    return os.getenv("SKI_CLOCK_SKEW_MODE", "discretionary").strip().lower()


def _clock_skew_delta_seconds(telemetry_ts: datetime, arrival_ts: datetime) -> float:
    """Absolute distance in seconds between the telemetry and arrival clocks."""
    return abs((arrival_ts - telemetry_ts).total_seconds())


def _build_clock_skew_envelope(
    *, skew_note: str, kg_version_hash: str, kg: Optional[KnowledgeGraph] = None
) -> V3VerdictEnvelope:
    """Build the short-circuit DISCRETIONARY envelope for an over-skew record.

    No LLM ran and no formalizable assertions were checked — the record
    never reached the evaluator — so ``model_provenance`` carries the same
    all-zero sentinel hash :class:`_State` uses before any KG is loaded,
    and ``verifier_result`` is honestly ``UNVERIFIABLE`` rather than
    implying a check that never happened.
    """
    sentinel_hash = "sha256:" + "0" * 64
    return V3VerdictEnvelope(
        verdict=V3Verdict.DISCRETIONARY,
        reasoning=(
            "Telemetry timestamp deviates from arrival wall-clock by more than the "
            "configured max_clock_skew_seconds bound (docs/threat-model.md "
            "'Assumption 2'). The record was not evaluated as fresh and is routed "
            "to human review."
        ),
        kg_citations=[],
        formalizable_assertions=[],
        verifier_result=VerifierResult(
            status=VerifierStatus.UNVERIFIABLE,
            checked_assertions=0,
            divergences=[skew_note],
        ),
        model_provenance=ModelProvenance(
            model_weight_hash=sentinel_hash,
            kg_version_hash=kg_version_hash,
            prompt_template_id="ski.v3.clock-skew-guard",
            prompt_template_hash=sentinel_hash,
            decoder_seed=0,
            structured_grammar_hash=sentinel_hash,
            kg_signer_key_id=kg.signer_key_id if kg is not None else None,
            kg_trust=kg.kg_trust if kg is not None else None,
        ),
        transcript_ref="transcript:none-clock-skew-guard",
        human_attestation={"required": True, "fulfilled": False},
        notes=[skew_note],
    )


def _hash_measurement(measurement: MeasurementRecord) -> str:
    """``telemetry_hash``: bare-hex sha256 of the spec §7.3 canonical telemetry record.

    Raises :class:`CanonicalizationError` for a record with no canonical form.
    """
    return hashlib.sha256(canonicalize(measurement.model_dump())).hexdigest()


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


def main() -> None:
    """Serve the app: one worker, TLS unless ``TLS_ENABLED=false`` (strict mode refuses that)."""
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


if __name__ == "__main__":
    main()
