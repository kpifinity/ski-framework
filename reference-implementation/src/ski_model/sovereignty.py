"""Sovereignty mode (spec §6): startup requirements, the egress guard, attestation.

``SKI_SOVEREIGNTY`` is ``strict`` (the default) or ``advisory`` (§6.1). The
runtime checks the five §6.2 requirements on startup, plus the posture a
sovereign deployment depends on: the loaded KG is anchored, the weight hash
is verified against the served weights (not only asserted), the ledger role
is least-privilege, TLS is on and there is a single worker. In ``strict`` it
refuses to start if any fails, naming each failed check; in ``advisory`` it
logs each failure at WARN. Either way the result is logged as one structured
report and served, signed, by ``/api/sovereignty`` (§6.4).

"Local" means inside the deployment: a loopback, private (RFC 1918 / ULA),
link-local or shared-address (100.64/10) IP, ``localhost``, a single-label
host name (a Compose or Kubernetes service), or a name under ``.local``,
``.localhost``, ``.internal``, ``.svc`` or ``.cluster.local``. Operators add
their own internal domains with ``SKI_SOVEREIGN_LOCAL_DOMAINS``
(comma-separated suffixes). Names are judged as written; nothing is
resolved, so the checks themselves make no network call.

The egress guard (§6.3) is a process audit hook, armed once startup is done.
From then on it sees every Python-level ``socket.connect``, ``sendto``,
``sendmsg`` and name lookup in the process, and allows only the egress
allowlist: loopback, the configured ledger host and the configured LLM
backend host (and the addresses those names resolve to). Any other
destination increments ``ski_egress_attempts_total`` in either mode. In
``strict`` mode the call is refused, and the runtime refuses every further
evaluation (fail closed on a non-zero count) until it is restarted.
Connections made by C libraries without Python sockets, such as libpq's,
are outside the hook; the ledger checks cover that destination at startup.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import sys
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Final, Optional
from urllib.parse import urlsplit

from . import metrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

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


def model_hash_verified_check(model_hash_verified: bool, model_hash_source: Optional[str]) -> Check:
    """The pinned weight hash was checked against the served weights, not only asserted."""
    return Check(
        id="model_weight_verified",
        requirement="the model weight hash is verified against the served weights",
        ok=model_hash_verified,
        detail=f"model_hash_verified={model_hash_verified} (source={model_hash_source!r})",
        remedy="Mount the weights file and set SKI_MODEL_FILE_PATH next to SKI_MODEL_FILE_SHA256 (vLLM), "
        "or serve a model whose digest the backend reports (Ollama). A pin alone is operator-asserted.",
    )


def kg_anchored_check(kg_loaded: bool, kg_trust: Optional[str]) -> Check:
    """§3.5: the KG serving verdicts verified against an operator trust anchor."""
    return Check(
        id="kg_anchored",
        requirement="§3.5 the loaded KG verifies against an operator trust anchor",
        ok=kg_loaded and kg_trust == "anchored",
        detail=f"kg_trust={kg_trust!r}" if kg_loaded else "no KG loaded at startup",
        remedy="Mount a KG signed by a key in SKI_KG_TRUST_ANCHORS at KG_PATH (ski-model-deploy sign), "
        "with KG_REQUIRE_SIGNATURE=true.",
    )


def runtime_checks(env: Mapping[str, str]) -> list[Check]:
    """TLS and the single-worker invariant, decided from configuration."""
    tls = env.get("TLS_ENABLED", "true").strip().lower() == "true"
    workers = env.get("SKI_MODEL_WORKERS", "1").strip()
    return [
        Check(
            id="tls_enabled",
            requirement="the API is served over TLS",
            ok=tls,
            detail=f"TLS_ENABLED={env.get('TLS_ENABLED', 'true')!r}",
            remedy="Set TLS_ENABLED=true and mount TLS_CERT / TLS_KEY.",
        ),
        Check(
            id="single_worker",
            requirement="one worker process, so the ledger hash chain has one writer",
            ok=workers == "1",
            detail=f"SKI_MODEL_WORKERS={workers!r}",
            remedy="Set SKI_MODEL_WORKERS=1 and scale with more containers (docs/CONCURRENCY.md).",
        ),
    ]


# The runtime's ledger role must not own, or act as the owner of,
# ledger_entries, and must hold no privilege that rewrites or removes rows.
_LEDGER_ROLE_SQL = """
SELECT current_user,
       r.rolsuper OR r.rolbypassrls OR r.rolcreaterole,
       pg_has_role(c.relowner, 'USAGE'),
       has_table_privilege(c.oid, 'UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES')
  FROM pg_roles r, pg_class c
 WHERE r.rolname = current_user AND c.oid = to_regclass('ledger_entries')
"""

LEDGER_ROLE_REQUIREMENT: Final = "the ledger role is least-privilege (INSERT + SELECT, not the owner)"


async def ledger_role_check(engine: Optional[AsyncEngine]) -> tuple[Check, Optional[str]]:
    """The runtime's own ledger role and whether it is least-privilege (``ski_ledger_writer`` passes)."""

    def result(ok: bool, detail: str) -> Check:
        return Check(
            id="ledger_least_privilege",
            requirement=LEDGER_ROLE_REQUIREMENT,
            ok=ok,
            detail=detail,
            remedy="Connect as ski_ledger_writer (append_only.sql creates it), never as the schema "
            "owner or a superuser: LEDGER_DSN=postgresql://ski_ledger_writer:...@host/db.",
        )

    if engine is None:
        return result(False, "no ledger connection"), None
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(_LEDGER_ROLE_SQL))).first()
    except Exception as exc:
        return result(False, f"could not inspect the ledger role ({exc.__class__.__name__})"), None
    if row is None:
        return result(False, "no ledger_entries table"), None
    role, elevated, owner, rewrite = row
    problems = [
        name
        for name, bad in (
            ("superuser, bypassrls or createrole", elevated),
            ("owns ledger_entries", owner),
            ("may UPDATE/DELETE/TRUNCATE/TRIGGER/REFERENCES ledger_entries", rewrite),
        )
        if bad
    ]
    return result(not problems, f"role={role!r}" + (f": {'; '.join(problems)}" if problems else "")), str(
        role
    )


def not_evaluated(check_id: str, requirement: str, reason: str) -> Check:
    return Check(id=check_id, requirement=requirement, ok=None, detail=f"not evaluated: {reason}")


def refuse_if_failed(mode: str, checks: list[Check]) -> None:
    """In strict mode, stop at the first stage with a failed check (before contacting anything else)."""
    if mode == STRICT and any(c.ok is False for c in checks):
        enforce(mode, checks)


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

_LOOKUP_EVENTS: Final = frozenset(
    {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"}
)
_SEND_EVENTS: Final = frozenset({"socket.connect", "socket.sendto", "socket.sendmsg"})
_bypass = threading.local()


class EgressRefused(PermissionError):
    """Strict mode refused a network call to a destination outside the egress allowlist."""


def egress_allowlist(backend: str, env: Mapping[str, str]) -> tuple[str, ...]:
    """The hosts the process may reach: the configured ledger and LLM backend (loopback is implicit)."""
    url = backend_url(backend, env)
    hosts = {_url_host(env.get("LEDGER_DSN", "")), _url_host(url) if url else ""}
    return tuple(sorted(h.lower() for h in hosts if h))


def _normalise(host: str) -> str:
    return host.strip().strip("[]").split("%", 1)[0].rstrip(".").lower()


class EgressGuard:
    """Counts, and in strict mode refuses, every network call outside the egress allowlist.

    Inactive until :meth:`arm`, so startup (KG load, backend and ledger
    initialisation) runs first; then it watches the whole process.
    """

    def __init__(self, mode: str, allowlist: Iterable[str] = ()) -> None:
        self.mode = mode
        self.allowlist = tuple(sorted({_normalise(h) for h in allowlist if _normalise(h)}))
        self.attempts = 0
        self.armed = False
        self._addresses: frozenset[str] = frozenset()
        self._lock = threading.Lock()

    @property
    def tripped(self) -> bool:
        """Strict mode and at least one attempt: evaluation must not continue (§6.3)."""
        return self.mode == STRICT and self.attempts > 0

    def arm(self) -> EgressGuard:
        """Resolve the allowlisted names and start guarding the process."""
        self._resolve()
        self.armed = True
        return self

    def state(self) -> dict[str, Any]:
        """The guard as ``/api/sovereignty`` attests it."""
        return {
            "mode": self.mode,
            "enforcing": self.mode == STRICT,
            "armed": self.armed,
            "allowlist": ["loopback", *self.allowlist],
            "attempts_total": self.attempts,
            "tripped": self.tripped,
        }

    def _resolve(self) -> None:
        """The addresses the allowlisted names resolve to now; the lookups themselves are not guarded."""
        addresses: set[str] = set()
        with unguarded():
            for host in self.allowlist:
                try:
                    addresses.update(_normalise(str(info[4][0])) for info in socket.getaddrinfo(host, None))
                except (OSError, UnicodeError):
                    continue
        self._addresses = frozenset(addresses)

    def allows(self, host: str) -> bool:
        """True for loopback, an allowlisted name, or an address an allowlisted name resolves to."""
        host = _normalise(host)
        if not host or host == "localhost" or host in self.allowlist or host in self._addresses:
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        if ip.is_loopback or ip.is_unspecified:
            return True
        self._resolve()  # an allowlisted name may have moved to a new address
        return host in self._addresses

    @staticmethod
    def _destination(event: str, args: tuple[Any, ...]) -> Optional[str]:
        if event in _SEND_EVENTS:
            address = args[1] if len(args) >= 2 else None
            # AF_UNIX paths (str/bytes) stay on this host.
            return str(address[0]) if isinstance(address, tuple) and address else None
        if event in _LOOKUP_EVENTS and args and isinstance(args[0], (str, bytes)):
            host = args[0]
            return host.decode("ascii", "replace") if isinstance(host, bytes) else host
        return None

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self.armed or getattr(_bypass, "active", False):
            return
        destination = self._destination(event, args)
        if destination is None or self.allows(destination):
            return
        with self._lock:
            self.attempts += 1
        metrics.EGRESS_ATTEMPTS.labels(mode=self.mode).inc()
        logger.error(
            "Egress attempt outside the allowlist: %s to %r (mode=%s).", event, destination, self.mode
        )
        if self.mode == STRICT:
            raise EgressRefused(
                f"{MODE_ENV}=strict: {event} to {destination!r} is outside the egress allowlist (§6.3)."
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


@contextmanager
def unguarded() -> Iterator[None]:
    """Run the enclosed calls outside the guard. For the guard's own lookups and tests only."""
    previous = getattr(_bypass, "active", False)
    _bypass.active = True
    try:
        yield
    finally:
        _bypass.active = previous
