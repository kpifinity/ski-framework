"""SKI Framework v3.0 § Pillar S — Air-gapped operability.

The runtime must boot, accept evaluations, and persist to the ledger in
a network namespace with **no external connectivity at all**. The rig
proves it the strongest way Docker allows:

  1. The audit-ledger Postgres starts with ``--network=none`` — its
     namespace has a loopback interface and nothing else.
  2. The SKI Model container joins that same namespace via
     ``--network=container:<postgres>``. The two processes share one
     loopback-only namespace: the model reaches the ledger at
     ``localhost:5432``, and *neither* has an interface, a route, or a
     resolver that could reach anything outside.
  3. A fixed conformance workload is replayed from inside the namespace
     (``docker exec`` + ``curl http://localhost:8000``), and the ledger
     rows are then verified — count, genesis pointer, hash-chain
     linkage — from inside the same namespace via ``psql``.

Provisioning (image build, base-image pull) happens *outside* the
sovereign boundary, exactly as in a real air-gapped deployment:
software is transferred in; the running namespace never gets an
interface.

Infrastructure: requires Docker and the opt-in ``SKI_L3_AIRGAP=1``
environment variable (building the runtime image takes minutes; CI
sets it in the dedicated air-gap job). Skips cleanly otherwise — the
suite stays runnable anywhere. ``SKI_L3_IMAGE`` may name a prebuilt
image to exercise instead of building the reference one.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

pytestmark = pytest.mark.sovereignty

REPO = Path(__file__).resolve().parent.parent.parent
REF_IMPL = REPO / "reference-implementation"
LEDGER_SQL = REF_IMPL / "src" / "ledger"

_OPT_IN = os.environ.get("SKI_L3_AIRGAP", "").lower() in {"1", "true", "yes"}
_PG_IMAGE = "postgres:16-alpine"
_PG_PASSWORD = "airgap-fixture"  # throwaway container in a loopback-only namespace
_GENESIS = "0" * 64

# ---------------------------------------------------------------------------
# Fixed conformance workload
# ---------------------------------------------------------------------------
# Two must_not_exceed obligations (the predicate every conformant verifier
# handles) and five measurements with deterministic expected verdicts under
# the FakeLLM backend. The claim under test is air-gapped *operability*;
# verdict accuracy is what evals/ measures.

_KG_RULES: List[Dict[str, Any]] = [
    {
        "id": "energy.so2.cap",
        "name": "SO2 emissions cap",
        "metric": "so2_ppm",
        "predicate": "must_not_exceed",
        "value": 100,
        "unit": "ppm",
        "jurisdiction": "global",
        "effective_date": "2026-01-01T00:00:00Z",
    },
    {
        "id": "energy.nox.cap",
        "name": "NOx emissions cap",
        "metric": "nox_ppm",
        "predicate": "must_not_exceed",
        "value": 50,
        "unit": "ppm",
        "jurisdiction": "global",
        "effective_date": "2026-01-01T00:00:00Z",
    },
]

_KG_TAG_REGISTRY: Dict[str, str] = {
    "facility.so2_ppm": "energy.so2.cap",
    "facility.nox_ppm": "energy.nox.cap",
}

# (measurement_id, measurement payload, expected verdict)
_WORKLOAD: List[Tuple[str, Dict[str, Any], str]] = [
    ("airgap-001", {"so2_ppm": 85}, "CLEAR"),
    ("airgap-002", {"so2_ppm": 142}, "FLAG"),
    ("airgap-003", {"nox_ppm": 12}, "CLEAR"),
    ("airgap-004", {"nox_ppm": 60}, "FLAG"),
    ("airgap-005", {"co2_ppm": 410}, "NULL_UNMAPPED"),
]


def _signed_fixture_kg() -> Dict[str, Any]:
    """Build the workload KG and sign it with an ephemeral ed25519 key.

    The signature scheme is the one the spec documents (and
    ``kg_loader._canonical_bytes`` implements): ed25519 over the
    RFC 8785-compatible canonical JSON of ``{metadata, rules,
    tag_registry}`` — sorted keys, no whitespace, UTF-8. Signing with a
    throwaway key is conformant: the runtime's claim is "a KG without a
    *verifiable* signature must not load", not "only blessed keys load".
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    metadata = {
        "version": "airgap-fixture-1",
        "compiled_at": "2026-06-01T00:00:00Z",
        "description": "L3 air-gapped boot conformance workload KG.",
    }
    canonical = json.dumps(
        {"metadata": metadata, "rules": _KG_RULES, "tag_registry": _KG_TAG_REGISTRY},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    key = Ed25519PrivateKey.generate()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {
        "metadata": metadata,
        "rules": _KG_RULES,
        "tag_registry": _KG_TAG_REGISTRY,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": public_pem.decode("ascii"),
            "value_hex": key.sign(canonical).hex(),
        },
    }


# ---------------------------------------------------------------------------
# Docker rig
# ---------------------------------------------------------------------------


def _run(
    args: List[str], *, stdin: Optional[str] = None, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)


def _must(args: List[str], *, stdin: Optional[str] = None, timeout: int = 600) -> str:
    proc = _run(args, stdin=stdin, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


@dataclass
class AirgapRig:
    """Handles to the loopback-only pod: Postgres + SKI Model, one namespace."""

    pg: str
    model: str
    api_key: str
    workdir: Path
    _workload: Optional[List[Tuple[str, str, Dict[str, Any]]]] = field(default=None, repr=False)

    def exec(
        self, container: str, argv: List[str], *, stdin: Optional[str] = None
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["docker", "exec", "-i", container] if stdin is not None else ["docker", "exec", container]
        return _run(cmd + argv, stdin=stdin, timeout=120)

    def api(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Dict[str, Any]]:
        """HTTP call to the runtime from *inside* the air-gapped namespace."""
        argv = [
            "curl",
            "-sS",
            "--max-time",
            "60",
            "-X",
            method,
            "-H",
            f"X-API-Key: {self.api_key}",
            "-H",
            "Content-Type: application/json",
            "-w",
            "\n%{http_code}",
            f"http://localhost:8000{path}",
        ]
        stdin: Optional[str] = None
        if body is not None:
            argv += ["-d", "@-"]
            stdin = json.dumps(body)
        out = _must(["docker", "exec", "-i", self.model, *argv], stdin=stdin, timeout=120)
        payload, _, status = out.rpartition("\n")
        return int(status), (json.loads(payload) if payload.strip() else {})

    def sql(self, query: str) -> str:
        """Run a query against the ledger from inside the namespace."""
        return _must(
            [
                "docker",
                "exec",
                self.pg,
                "psql",
                "-U",
                "postgres",
                "-d",
                "ski_ledger",
                "-At",
                "-c",
                query,
            ],
            timeout=120,
        ).strip()

    def logs(self, container: str) -> str:
        proc = _run(["docker", "logs", "--tail", "80", container], timeout=60)
        return proc.stdout + proc.stderr

    def replay_workload(self) -> List[Tuple[str, str, Dict[str, Any]]]:
        """POST the fixed workload once; memoised so tests stay order-independent."""
        if self._workload is None:
            results: List[Tuple[str, str, Dict[str, Any]]] = []
            for measurement_id, measurement, _expected in _WORKLOAD:
                status, envelope = self.api(
                    "POST",
                    "/api/evaluate",
                    {
                        "measurement_id": measurement_id,
                        "timestamp": "2026-06-15T12:00:00Z",
                        "subject": f"facility.{next(iter(measurement))}",
                        "measurement": measurement,
                    },
                )
                assert status == 200, (
                    f"/api/evaluate returned {status} for {measurement_id}: "
                    f"{envelope}\n{self.logs(self.model)}"
                )
                results.append((measurement_id, str(envelope.get("verdict")), envelope))
            self._workload = results
        return self._workload


def _wait(
    probe: List[str],
    *,
    container: str,
    what: str,
    rig_logs: Callable[[str], str],
    deadline_s: int = 180,
) -> None:
    deadline = time.monotonic() + deadline_s
    last: Optional[subprocess.CompletedProcess[str]] = None
    while time.monotonic() < deadline:
        last = _run(["docker", "exec", container, *probe], timeout=30)
        if last.returncode == 0:
            return
        time.sleep(2)
    detail = f"{last.stdout}\n{last.stderr}" if last is not None else "probe never ran"
    raise RuntimeError(
        f"{what} not ready after {deadline_s}s.\nprobe: {detail}\nlogs:\n{rig_logs(container)}"
    )


@pytest.fixture(scope="module")
def rig(request: pytest.FixtureRequest) -> AirgapRig:
    if not _OPT_IN:
        pytest.skip("SKI_L3_AIRGAP not set; the air-gap rig builds and boots containers (opt-in).")
    if shutil.which("docker") is None:
        pytest.skip("Docker not available; the air-gap rig needs a container runtime.")

    suffix = uuid.uuid4().hex[:8]
    pg_name = f"ski-l3-airgap-pg-{suffix}"
    model_name = f"ski-l3-airgap-model-{suffix}"
    api_key = secrets.token_hex(32)

    workdir = Path(tempfile.mkdtemp(prefix="ski-l3-airgap-"))
    workdir.chmod(0o755)  # the runtime container runs as uid 10001
    kg_path = workdir / "kg.json"
    kg_path.write_text(json.dumps(_signed_fixture_kg(), indent=2), encoding="utf-8")
    kg_path.chmod(0o644)

    def cleanup() -> None:
        for name in (model_name, pg_name):
            _run(["docker", "rm", "-f", name], timeout=120)
        shutil.rmtree(workdir, ignore_errors=True)

    request.addfinalizer(cleanup)

    image = os.environ.get("SKI_L3_IMAGE", "")
    if not image:
        image = f"ski-l3-airgap:{suffix}"
        _must(
            [
                "docker",
                "build",
                "-q",
                "-t",
                image,
                "-f",
                str(REF_IMPL / "Dockerfile.ski-model"),
                str(REPO),  # repo-root context: the image carries ski-schemas (RFC 0003)
            ],
            timeout=1800,
        )

    # 1. Ledger Postgres in a namespace with NO network.
    _must(
        [
            "docker",
            "run",
            "-d",
            "--name",
            pg_name,
            "--network=none",
            "-e",
            f"POSTGRES_PASSWORD={_PG_PASSWORD}",
            "-e",
            "POSTGRES_DB=ski_ledger",
            "-v",
            f"{LEDGER_SQL / 'schema.sql'}:/docker-entrypoint-initdb.d/01-schema.sql:ro",
            "-v",
            f"{LEDGER_SQL / 'append_only.sql'}:/docker-entrypoint-initdb.d/02-append-only.sql:ro",
            "-v",
            f"{LEDGER_SQL / 'migrations' / '0002_transcript_columns.sql'}"
            ":/docker-entrypoint-initdb.d/03-transcript-columns.sql:ro",
            _PG_IMAGE,
        ]
    )

    rig_handle = AirgapRig(pg=pg_name, model=model_name, api_key=api_key, workdir=workdir)
    _wait(
        ["pg_isready", "-U", "postgres", "-d", "ski_ledger"],
        container=pg_name,
        what="air-gapped ledger Postgres",
        rig_logs=rig_handle.logs,
    )

    # 2. SKI Model joins the SAME loopback-only namespace.
    _must(
        [
            "docker",
            "run",
            "-d",
            "--name",
            model_name,
            f"--network=container:{pg_name}",
            "-v",
            f"{kg_path}:/app/kg/kg.json:ro",
            "-e",
            "KG_PATH=/app/kg/kg.json",
            "-e",
            "KG_REQUIRE_SIGNATURE=true",
            "-e",
            f"LEDGER_DSN=postgresql://postgres:{_PG_PASSWORD}@localhost:5432/ski_ledger",
            "-e",
            f"API_KEY={api_key}",
            "-e",
            "SKI_V3_LLM_BACKEND=fake",
            "-e",
            "TLS_ENABLED=false",
            image,
        ]
    )
    _wait(
        ["curl", "-fsS", "http://localhost:8000/api/health"],
        container=model_name,
        what="air-gapped SKI Model",
        rig_logs=rig_handle.logs,
    )
    return rig_handle


# ---------------------------------------------------------------------------
# Tests — one hard claim each
# ---------------------------------------------------------------------------


def test_namespace_has_loopback_only(rig: AirgapRig) -> None:
    """The pod's network namespace contains no interface besides ``lo``."""
    assert _must(["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", rig.pg]).strip() == "none"
    assert (
        _must(["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", rig.model])
        .strip()
        .startswith("container:")
    )
    interfaces = set(_must(["docker", "exec", rig.model, "ls", "/sys/class/net"]).split())
    assert interfaces == {"lo"}, f"air-gapped namespace must be loopback-only, found: {interfaces}"


def test_outbound_connectivity_is_impossible(rig: AirgapRig) -> None:
    """Direct egress and DNS resolution both fail from inside the namespace."""
    egress = rig.exec(
        rig.model,
        [
            "python",
            "-c",
            "import socket; socket.setdefaulttimeout(3); socket.create_connection(('1.1.1.1', 443))",
        ],
    )
    assert egress.returncode != 0, (
        f"outbound TCP must fail in the air gap, got: {egress.stdout}{egress.stderr}"
    )
    dns = rig.exec(
        rig.model,
        [
            "python",
            "-c",
            "import socket; socket.setdefaulttimeout(3); socket.getaddrinfo('example.com', 443)",
        ],
    )
    assert dns.returncode != 0, f"DNS resolution must fail in the air gap, got: {dns.stdout}{dns.stderr}"


def test_runtime_boots_with_no_network(rig: AirgapRig) -> None:
    """The runtime is healthy — signed KG loaded and verified — inside the air gap."""
    status, health = rig.api("GET", "/api/health")
    assert status == 200, f"/api/health returned {status}: {health}\n{rig.logs(rig.model)}"
    assert health.get("kg_loaded") is True
    assert health.get("kg_signature_verified") is True, (
        "the air-gapped boot must be a CONFORMANT boot: signed KG, signature verified"
    )


def test_workload_replays_with_expected_verdicts(rig: AirgapRig) -> None:
    """The fixed workload evaluates deterministically inside the air gap."""
    produced = {mid: verdict for mid, verdict, _ in rig.replay_workload()}
    expected = {mid: verdict for mid, _, verdict in _WORKLOAD}
    assert produced == expected


def test_ledger_persists_chained_entries_inside_airgap(rig: AirgapRig) -> None:
    """Every evaluation landed in the ledger, hash-chained from genesis."""
    rig.replay_workload()
    assert int(rig.sql("SELECT count(*) FROM ledger_entries")) == len(_WORKLOAD)
    genesis_prev = rig.sql("SELECT previous_hash FROM ledger_entries ORDER BY sequence_number LIMIT 1")
    assert genesis_prev == _GENESIS
    broken_links = rig.sql(
        "SELECT count(*) FROM ledger_entries l"
        " JOIN ledger_entries p ON l.sequence_number = p.sequence_number + 1"
        " WHERE l.previous_hash <> p.entry_hash"
    )
    assert int(broken_links) == 0, "ledger hash chain must link every entry to its predecessor"
