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

import hashlib
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
#
# The KG is in the spec §3 graph shape. Each Rule declares its risk_tier
# explicitly (spec §5.4): an undeclared tier resolves to tier-1, where the
# UNVERIFIABLE NULL_UNMAPPED path (airgap-005: no assertion to check) is
# forced to DISCRETIONARY instead of being accepted with a note. No
# obligation is scoped_to a jurisdiction, so both apply everywhere.


def _cap(
    metric: str, gas: str, limit: int, *, fresh_within: Optional[int] = None
) -> Dict[str, List[Dict[str, Any]]]:
    rule_id, ob_id = f"energy.{gas}.cap", f"energy.{gas}.lte_{limit}ppm"
    freshness = {} if fresh_within is None else {"requires_recent_within_seconds": fresh_within}
    return {
        "subjects": [{"id": f"facility.{metric}", "type": "Subject", "version": "airgap-1", "name": metric}],
        "rules": [
            {
                "id": rule_id,
                "type": "Rule",
                "version": "airgap-1",
                "name": f"{gas.upper()} emissions cap",
                "risk_tier": "medium",
            }
        ],
        "obligations": [
            {
                "id": ob_id,
                "type": "Obligation",
                "version": "airgap-1",
                "obligation_type": "must_not_exceed",
                "metric": metric,
                "value": limit,
                "unit": "ppm",
                "effective_date_start": "2026-01-01T00:00:00Z",
                **freshness,
            }
        ],
        "citations": [
            {
                "id": f"cite.{gas}",
                "type": "Citation",
                "version": "airgap-1",
                "source_document": "Conformance fixture (not a real legal citation)",
                "source_clause": gas,
            }
        ],
        "edges": [
            {"type": "applies_to", "from": rule_id, "to": f"facility.{metric}"},
            {"type": "consists_of", "from": rule_id, "to": ob_id},
            {"type": "cited_by", "from": ob_id, "to": f"cite.{gas}"},
        ],
    }


# The PM2.5 cap carries a freshness gate: it can only come back CLEAR if the
# runtime's telemetry buffer recorded the reading (write-before-evaluate);
# without a working buffer it degrades to DISCRETIONARY.
_CAPS = [
    _cap("so2_ppm", "so2", 100),
    _cap("nox_ppm", "nox", 50),
    _cap("pm25_ppm", "pm25", 35, fresh_within=600),
]
_KG_NODES: Dict[str, List[Dict[str, Any]]] = {
    kind: [node for cap in _CAPS for node in cap[kind]]
    for kind in ("subjects", "rules", "obligations", "citations")
}
_KG_EDGES: List[Dict[str, Any]] = [edge for cap in _CAPS for edge in cap["edges"]]

# (measurement_id, measurement payload, expected verdict)
_WORKLOAD: List[Tuple[str, Dict[str, Any], str]] = [
    ("airgap-001", {"so2_ppm": 85}, "CLEAR"),
    ("airgap-002", {"so2_ppm": 142}, "FLAG"),
    ("airgap-003", {"nox_ppm": 12}, "CLEAR"),
    ("airgap-004", {"nox_ppm": 60}, "FLAG"),
    ("airgap-005", {"co2_ppm": 410}, "NULL_UNMAPPED"),
    ("airgap-006", {"pm25_ppm": 12}, "CLEAR"),
]


@dataclass(frozen=True)
class SignedFixtureKG:
    """The workload KG plus the trust anchor the rig pins for it."""

    kg: Dict[str, Any]
    anchor_pem: str  # one-key PEM trust-anchor bundle (SKI_KG_TRUST_ANCHORS)
    anchor_key_id: str  # sha256:<hex sha256 of the raw 32-byte public key>


def _signed_fixture_kg() -> SignedFixtureKG:
    """Build the workload KG and sign it with an ephemeral ed25519 key.

    The signature scheme is the one the spec documents (§3.5): ed25519
    over the §7.3 canonical JSON of ``{metadata, nodes, edges}``. The throwaway
    key is conformant only because the rig PINS it as the runtime's trust
    anchor (``SKI_KG_TRUST_ANCHORS``, spec §2.1.2/§3.5): a KG loads only if
    its signature verifies against an operator-pinned anchor, never against
    the key the KG embeds, so the rig must declare which key it trusts.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ski_schemas.canonical import canonicalize

    metadata = {
        "name": "L3 air-gap conformance KG",
        "schema_version": "3.0",
        "version": "airgap-fixture-1",
        "compiled_at": "2026-06-01T00:00:00Z",
        "description": "L3 air-gapped boot conformance workload KG.",
    }
    canonical = canonicalize({"metadata": metadata, "nodes": _KG_NODES, "edges": _KG_EDGES})

    key = Ed25519PrivateKey.generate()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    raw_public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kg = {
        "metadata": metadata,
        "nodes": _KG_NODES,
        "edges": _KG_EDGES,
        "signature": {
            "algorithm": "ed25519",
            "public_key_pem": public_pem.decode("ascii"),
            "value_hex": key.sign(canonical).hex(),
        },
    }
    return SignedFixtureKG(
        kg=kg,
        anchor_pem=public_pem.decode("ascii"),
        anchor_key_id="sha256:" + hashlib.sha256(raw_public).hexdigest(),
    )


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
    anchor_key_id: str
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
    fixture = _signed_fixture_kg()
    kg_path = workdir / "kg.json"
    kg_path.write_text(json.dumps(fixture.kg, indent=2), encoding="utf-8")
    kg_path.chmod(0o644)
    # The throwaway signing key, pinned as the runtime's only KG trust anchor.
    anchors_path = workdir / "kg-trust-anchors.pem"
    anchors_path.write_text(fixture.anchor_pem, encoding="utf-8")
    anchors_path.chmod(0o644)

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
            "-v",
            f"{LEDGER_SQL / 'telemetry_buffer.sql'}:/docker-entrypoint-initdb.d/05-telemetry-buffer.sql:ro",
            _PG_IMAGE,
        ]
    )

    rig_handle = AirgapRig(
        pg=pg_name, model=model_name, api_key=api_key, workdir=workdir, anchor_key_id=fixture.anchor_key_id
    )
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
            "-v",
            f"{anchors_path}:/app/trust/kg-trust-anchors.pem:ro",
            "-e",
            "SKI_KG_TRUST_ANCHORS=/app/trust/kg-trust-anchors.pem",
            # Fresh ledger, fresh container: generating the transcript
            # signing key on this first boot is an explicit opt-in.
            "-e",
            "SKI_ALLOW_KEY_GENERATION=true",
            "-e",
            f"LEDGER_DSN=postgresql://postgres:{_PG_PASSWORD}@localhost:5432/ski_ledger",
            "-e",
            f"API_KEY={api_key}",
            "-e",
            "SKI_V3_LLM_BACKEND=fake",
            # v3.2.0: FakeLLM needs an explicit opt-in to start.
            "-e",
            "SKI_ALLOW_FAKE_LLM=true",
            # FakeLLM is not a sovereign backend: advisory mode (spec §6.1).
            "-e",
            "SKI_SOVEREIGNTY=advisory",
            "-e",
            "TLS_ENABLED=false",
            # The fixed workload below is pinned to a fixed 2026-06-15
            # timestamp for reproducibility, not "now" -- exactly the
            # legitimate-backfill case the clock-skew guard must not
            # break. Disabled here; guard behaviour itself is covered by
            # test_clock_skew_guard.py and
            # conformance/provenance/test_clock_skew_enforced.py.
            "-e",
            "SKI_MAX_CLOCK_SKEW_SECONDS=0",
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
    provenance = health.get("provenance") or {}
    assert provenance.get("kg_trust") == "anchored", (
        f"the KG must verify against the pinned trust anchor, got provenance={provenance}"
    )
    assert provenance.get("kg_signer_key_id") == rig.anchor_key_id


def test_workload_replays_with_expected_verdicts(rig: AirgapRig) -> None:
    """The fixed workload evaluates deterministically inside the air gap."""
    produced = {mid: verdict for mid, verdict, _ in rig.replay_workload()}
    expected = {mid: verdict for mid, _, verdict in _WORKLOAD}
    assert produced == expected
    for mid, _, envelope in rig.replay_workload():
        provenance = envelope.get("model_provenance") or {}
        assert provenance.get("kg_signer_key_id") == rig.anchor_key_id, mid
        assert provenance.get("kg_trust") == "anchored", mid


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


def test_sovereignty_attestation_inside_airgap(rig: AirgapRig) -> None:
    """Spec §6.4: the runtime attests itself, signed, and reports no egress after the workload."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from ski_schemas.canonical import canonicalize

    rig.replay_workload()
    status, body = rig.api("GET", "/api/sovereignty")
    assert status == 200, body
    document, signature = body["document"], body["signature"]
    assert document["sovereignty_mode"] == "advisory"  # the rig runs FakeLLM
    assert document["egress_attempts_total"] == 0
    assert {c["id"] for c in document["checks"]} >= {"sovereign_backend", "kg_trust_anchor", "ledger_local"}
    public_key = serialization.load_pem_public_key(signature["public_key_pem"].encode("ascii"))
    assert isinstance(public_key, Ed25519PublicKey)
    public_key.verify(bytes.fromhex(signature["value_hex"]), canonicalize(document))


def test_telemetry_buffer_records_every_reading_inside_airgap(rig: AirgapRig) -> None:
    """The image ships the telemetry buffer: every reading is buffered and joins its ledger entry."""
    rig.replay_workload()
    assert int(rig.sql("SELECT count(*) FROM telemetry_buffer")) == len(_WORKLOAD)
    joined = rig.sql(
        "SELECT count(*) FROM ledger_entries l JOIN telemetry_buffer b ON b.measurement_hash = l.telemetry_hash"
    )
    assert int(joined) == len(_WORKLOAD), (
        "deterministic replay finds a ledger entry's reading by telemetry_hash"
    )
