"""RFC 3161 time-stamping of ledger checkpoints: the request bytes and the response check."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from ski_model import sovereignty
from ski_model.timestamping import (
    TimestampAuthority,
    TimestampError,
    response_status,
    timestamp_request,
)


def test_request_is_a_der_timestampreq_over_the_sha256() -> None:
    request = timestamp_request(b"statement", nonce=0x1234)
    digest = hashlib.sha256(b"statement").digest()
    assert request[0] == 0x30  # SEQUENCE
    assert request[2:5] == b"\x02\x01\x01"  # version 1
    assert bytes.fromhex("0609608648016503040201") in request  # id-sha256
    assert b"\x04\x20" + digest in request  # hashedMessage
    assert request.endswith(b"\x01\x01\xff")  # certReq TRUE


@pytest.mark.parametrize("nonce", [0, 1, 127, 128, 255, 256, 2**63 - 1])
def test_nonce_is_a_positive_der_integer(nonce: int) -> None:
    request = timestamp_request(b"x", nonce=nonce)
    body = nonce.to_bytes(max(1, (nonce.bit_length() + 8) // 8), "big")
    assert b"\x02" + bytes([len(body)]) + body + b"\x01\x01\xff" in request
    assert body[0] < 0x80


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
def test_openssl_reads_the_request(tmp_path: Path) -> None:
    path = tmp_path / "query.der"
    path.write_bytes(timestamp_request(b"statement", nonce=99))
    text = subprocess.run(
        ["openssl", "ts", "-query", "-in", str(path), "-text"], capture_output=True, text=True, check=True
    ).stdout
    assert "Hash Algorithm: sha256" in text and "Certificate required: yes" in text and "Nonce: 0x63" in text


@pytest.mark.parametrize(
    "response, expected",
    [
        (bytes.fromhex("3005" + "3003020100"), (0, False)),  # granted, no token
        (bytes.fromhex("3009" + "3003020100" + "30020500"), (0, True)),  # granted + token
        (bytes.fromhex("3005" + "3003020102"), (2, False)),  # rejection
    ],
)
def test_response_status(response: bytes, expected: tuple[int, bool]) -> None:
    assert response_status(response) == expected


@pytest.mark.parametrize("response", [b"", b"\x30", b"\x04\x00", bytes.fromhex("3003" + "020100")])
def test_malformed_responses_are_rejected(response: bytes) -> None:
    with pytest.raises(ValueError):
        response_status(response)


_RealAsyncClient = httpx.AsyncClient


def _serve(monkeypatch: pytest.MonkeyPatch, handle: Any) -> None:
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _RealAsyncClient(transport=transport, **kw))


@pytest.mark.parametrize(
    "body",
    [bytes.fromhex("3005" + "3003020102"), bytes.fromhex("3005" + "3003020100"), b"junk"],
    ids=["rejection", "no-token", "malformed"],
)
async def test_a_refusal_or_missing_token_raises(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    _serve(monkeypatch, lambda request: httpx.Response(200, content=body))
    with pytest.raises(TimestampError):
        await TimestampAuthority("http://tsa.internal/ts").timestamp(b"statement")


async def test_a_granted_response_is_returned_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    granted = bytes.fromhex("3009" + "3003020100" + "30020500")
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=granted)

    _serve(monkeypatch, handle)
    assert await TimestampAuthority("http://tsa.internal/ts").timestamp(b"statement") == granted
    assert seen[0].headers["content-type"] == "application/timestamp-query"
    assert hashlib.sha256(b"statement").digest() in seen[0].content


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKI_TSA_URL", raising=False)
    assert TimestampAuthority.from_env() is None
    monkeypatch.setenv("SKI_TSA_URL", "http://tsa.internal/ts")
    tsa = TimestampAuthority.from_env()
    assert tsa is not None and tsa.url == "http://tsa.internal/ts"


def test_the_tsa_is_on_the_egress_allowlist_and_must_be_local() -> None:
    env = {"LEDGER_DSN": "postgresql://w:p@postgres/l", "SKI_TSA_URL": "http://tsa.internal/ts"}
    assert sovereignty.egress_allowlist("fake", env) == ("postgres", "tsa.internal")
    outside = {**env, "SKI_TSA_URL": "https://freetsa.org/tsr"}
    checks = {
        c.id: c
        for c in sovereignty.config_checks(
            backend="ollama", env=outside, trust_anchor_count=1, unanchored=False
        )
    }
    egress = checks["egress_allowlist_local"]
    assert egress.ok is False
    assert egress.detail.endswith("; outside=['freetsa.org']"), egress.detail
