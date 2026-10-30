"""Sovereignty mode (spec §6): startup requirements, the egress guard, attestation.

``SKI_SOVEREIGNTY`` is ``strict`` (the default) or ``advisory`` (§6.1). The
runtime checks the five §6.2 requirements on startup; in ``strict`` it
refuses to start if any fails, in ``advisory`` it logs each failure at WARN.
Either way the result is logged as one structured report and served, signed,
by ``/api/sovereignty`` (§6.4).

"Local" means inside the deployment: a loopback, private (RFC 1918 / ULA),
link-local or shared-address (100.64/10) IP, ``localhost``, a single-label
host name (a Compose or Kubernetes service), or a name under ``.local``,
``.localhost``, ``.internal``, ``.svc`` or ``.cluster.local``. Operators add
their own internal domains with ``SKI_SOVEREIGN_LOCAL_DOMAINS``
(comma-separated suffixes). Names are judged as written; nothing is
resolved, so the checks themselves make no network call.

The egress guard (§6.3) is a process audit hook. While a verdict is being
evaluated it sees every Python-level ``socket.connect`` and
``socket.getaddrinfo``; one aimed at a non-local destination increments
``ski_egress_attempts_total`` in either mode. In ``strict`` mode the call is
refused, and the runtime refuses every further evaluation (fail closed on a
non-zero count) until it is restarted. Connections made by C libraries
without Python sockets, such as libpq's, are outside the hook; the ledger
check covers that destination at startup.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Final, Optional
from urllib.parse import urlsplit

from . import metrics

logger = logging.getLogger(__name__)

MODE_ENV: Final = "SKI_SOVEREIGNTY"
LOCAL_DOMAINS_ENV: Final = "SKI_SOVEREIGN_LOCAL_DOMAINS"
STRICT: Final = "strict"
ADVISORY: Final = "advisory"

#: Backends that keep inference on the operator's hardware (§6.2 item 1).
SOVEREIGN_BACKENDS: Final = frozenset({"ollama", "vllm"})
#: model_hash_source values that mean the weight hash is in the operator's pin (§6.2 item 2).
REGISTERED_HASH_SOURCES: Final = frozenset(
    {"verified-backend-digest", "verified-file-digest", "operator-asserted"}
)

_LOCAL_SUFFIXES: Final = (".local", ".localhost", ".internal", ".svc", ".cluster.local")
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


class SovereigntyError(RuntimeError):
    """A strict-mode requirement is unmet; the runtime must not start."""


@dataclass(frozen=True)
class Check:
    """One §6.2 requirement and whether this deployment meets it (``None``: not evaluated)."""

    id: str
    requirement: str
    ok: Optional[bool]
    detail: str
    remedy: str = ""


def resolve_mode(env: Mapping[str, str]) -> str:
    """``strict`` unless ``SKI_SOVEREIGNTY=advisory``; any other value refuses to start."""
    mode = env.get(MODE_ENV, "").strip().lower() or STRICT
    if mode not in (STRICT, ADVISORY):
        raise SovereigntyError(f"{MODE_ENV}={mode!r} is not 'strict' or 'advisory'. Refusing to start.")
    return mode


def local_suffixes(env: Mapping[str, str]) -> tuple[str, ...]:
    extra = [s.strip().lower() for s in env.get(LOCAL_DOMAINS_ENV, "").split(",") if s.strip()]
    return _LOCAL_SUFFIXES + tuple(s if s.startswith(".") else "." + s for s in extra)


def is_local_host(host: str, suffixes: tuple[str, ...] = _LOCAL_SUFFIXES) -> bool:
    """True when ``host`` (a name or IP literal) is inside the deployment; see the module docstring."""
    host = host.strip().strip("[]").split("%", 1)[0].rstrip(".").lower()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(suffixes)
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip in _SHARED_ADDRESS_SPACE


def _url_host(url: str) -> str:
    return urlsplit(url if "://" in url else "//" + url).hostname or ""


def backend_url(backend: str, env: Mapping[str, str]) -> Optional[str]:
    """The URL the evaluation path calls for inference (the factory's defaults)."""
    if backend == "ollama":
        return env.get("OLLAMA_BASE_URL", "http://ollama:11434")
    if backend == "vllm":
        return env.get("VLLM_BASE_URL", "http://vllm:8000")
    return None


def config_checks(
    *, backend: str, env: Mapping[str, str], trust_anchor_count: int, unanchored: bool
) -> list[Check]:
    """§6.2 items 1, 3, 4 and 5: decided from configuration, before anything is contacted."""
    suffixes = local_suffixes(env)
    checks = [
        Check(
            id="sovereign_backend",
            requirement="§6.2(1) the language model backend is sovereign (Ollama or vLLM)",
            ok=backend in SOVEREIGN_BACKENDS,
            detail=f"backend={backend!r}",
            remedy="Set SKI_V3_LLM_BACKEND to 'ollama' or 'vllm'. FakeLLM is for demos and CI "
            "(SKI_SOVEREIGNTY=advisory).",
        ),
        Check(
            id="kg_trust_anchor",
            requirement="§6.2(3) the KG signature trust anchor is operator-provided",
            ok=trust_anchor_count > 0,
            detail=f"anchors={trust_anchor_count}"
            + (" (SKI_KG_ALLOW_UNANCHORED=true)" if unanchored else ""),
            remedy="Set SKI_KG_TRUST_ANCHORS to a PEM bundle of your own KG-signing public keys.",
        ),
    ]
    ledger_host = _url_host(env.get("LEDGER_DSN", ""))
    checks.append(
        Check(
            id="ledger_local",
            requirement="§6.2(4) the ledger storage is local to the deployment",
            ok=bool(ledger_host) and is_local_host(ledger_host, suffixes),
            detail=f"ledger host={ledger_host or '(none)'}",
            remedy=f"Point LEDGER_DSN at a database inside the deployment, or declare its domain in {LOCAL_DOMAINS_ENV}.",
        )
    )
    url = backend_url(backend, env)
    destinations = [d for d in (_url_host(url) if url else "", ledger_host) if d]
    outside = [d for d in destinations if not is_local_host(d, suffixes)]
    checks.append(
        Check(
            id="egress_allowlist_local",
            requirement="§6.2(5) no evaluation-path destination is outside the deployment",
            ok=not outside,
            detail=f"evaluation-path destinations={destinations}"
            + (f"; outside={outside}" if outside else ""),
            remedy=f"Serve the model inside the deployment, or declare its domain in {LOCAL_DOMAINS_ENV}.",
        )
    )
    return checks


def model_hash_check(model_hash_source: Optional[str]) -> Check:
    """§6.2 item 2, once the backend has resolved its weight hash."""
    return Check(
        id="model_weight_registered",
        requirement="§6.2(2) the model weight hash is in the operator's weight registry (SKI_MODEL_FILE_SHA256)",
        ok=model_hash_source in REGISTERED_HASH_SOURCES,
        detail=f"model_hash_source={model_hash_source!r}",
        remedy="Pin the model's weight digest in SKI_MODEL_FILE_SHA256.",
    )


def not_evaluated(check_id: str, requirement: str, reason: str) -> Check:
    return Check(id=check_id, requirement=requirement, ok=None, detail=f"not evaluated: {reason}")


def enforce(mode: str, checks: list[Check]) -> None:
    """Log the §6.2 report; in strict mode raise :class:`SovereigntyError` if any check failed."""
    failed = [c for c in checks if c.ok is False]
    report = json.dumps({"sovereignty_mode": mode, "checks": [asdict(c) for c in checks]}, sort_keys=True)
    if not failed:
        logger.info("Sovereignty checks passed (mode=%s): %s", mode, report)
        return
    for check in failed:
        logger.warning(
            "Sovereignty requirement unmet: %s (%s). %s", check.requirement, check.detail, check.remedy
        )
    if mode == STRICT:
        names = ", ".join(c.id for c in failed)
        raise SovereigntyError(
            f"{MODE_ENV}=strict and {len(failed)} requirement(s) unmet: {names}. Report: {report}. "
            f"Fix them, or set {MODE_ENV}=advisory for a non-production deployment."
        )
    logger.warning(
        "Starting in %s=advisory with unmet requirements; NOT for production: %s", MODE_ENV, report
    )


# ---- Egress guard (§6.3) -----------------------------------------------------------

_EVALUATING: ContextVar[bool] = ContextVar("ski_evaluating", default=False)


class EgressRefused(PermissionError):
    """Strict mode refused a network call to a destination outside the deployment."""


class EgressGuard:
    """Counts, and in strict mode refuses, non-local network calls made while evaluating."""

    def __init__(self, mode: str, suffixes: tuple[str, ...] = _LOCAL_SUFFIXES) -> None:
        self.mode = mode
        self.suffixes = suffixes
        self.attempts = 0

    @property
    def tripped(self) -> bool:
        """Strict mode and at least one attempt: evaluation must not continue (§6.3)."""
        return self.mode == STRICT and self.attempts > 0

    @contextmanager
    def evaluation(self) -> Iterator[None]:
        """Mark the current task as evaluating a verdict; calls made inside are guarded."""
        token = _EVALUATING.set(True)
        try:
            yield
        finally:
            _EVALUATING.reset(token)

    def _destination(self, event: str, args: tuple[Any, ...]) -> Optional[str]:
        if event == "socket.connect" and len(args) >= 2 and isinstance(args[1], tuple) and args[1]:
            return str(args[1][0])
        if event == "socket.getaddrinfo" and args and isinstance(args[0], (str, bytes)):
            host = args[0]
            return host.decode("ascii", "replace") if isinstance(host, bytes) else host
        return None

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not _EVALUATING.get():
            return
        destination = self._destination(event, args)
        if destination is None or is_local_host(destination, self.suffixes):
            return
        self.attempts += 1
        metrics.EGRESS_ATTEMPTS.labels(mode=self.mode).inc()
        logger.error("Egress attempt during evaluation: %s to %r (mode=%s).", event, destination, self.mode)
        if self.mode == STRICT:
            raise EgressRefused(
                f"{MODE_ENV}=strict: {event} to {destination!r} is outside the deployment (§6.3)."
            )


_active_guard: Optional[EgressGuard] = None
_hook_installed = False


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if event.startswith("socket.") and _active_guard is not None:
        _active_guard.audit(event, args)


def install_egress_guard(guard: EgressGuard) -> EgressGuard:
    """Make ``guard`` the process's egress guard. The audit hook is added once; it cannot be removed."""
    global _active_guard, _hook_installed
    _active_guard = guard
    if not _hook_installed:
        sys.addaudithook(_audit_hook)
        _hook_installed = True
    return guard
