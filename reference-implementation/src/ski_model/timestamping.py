"""RFC 3161 time-stamping of ledger checkpoints, against a TSA inside the deployment.

A signed checkpoint proves the runtime's key saw a Merkle root; a time-stamp
token from an independent Time-Stamping Authority proves the root existed at
a time the runtime does not control. ``SKI_TSA_URL`` names the TSA. It must be
inside the deployment (it is on the egress allowlist and the strict-mode
``egress_allowlist_local`` check), so an air-gapped site runs its own TSA, for
example ``openssl ts`` behind a small HTTP front, or a hardware TSA.

The request is a minimal ``TimeStampReq`` (RFC 3161 §2.4.1): version 1, a
SHA-256 message imprint of the checkpoint statement, a random nonce and
``certReq``. The response is stored as returned (DER ``TimeStampResp``) in
``ledger_checkpoints.tsa_response``; ``audit-ledger checkpoint verify
--tsa-ca`` checks it with ``openssl ts -verify``. Here the runtime checks only
that the TSA granted the request, so a refusal is logged rather than stored.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TSA_URL_ENV = "SKI_TSA_URL"

# DER of AlgorithmIdentifier { id-sha256, NULL }.
_SHA256_ALGORITHM = bytes.fromhex("300d06096086480165030402010500")


class TimestampError(RuntimeError):
    """The TSA did not grant a time-stamp token."""


def _der(tag: int, content: bytes) -> bytes:
    n = len(content)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + content


def _der_integer(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big")  # leading 0 keeps it positive
    return _der(0x02, raw)


def timestamp_request(message: bytes, nonce: int) -> bytes:
    """DER ``TimeStampReq`` for the SHA-256 of ``message``."""
    imprint = _der(0x30, _SHA256_ALGORITHM + _der(0x04, hashlib.sha256(message).digest()))
    return _der(0x30, _der_integer(1) + imprint + _der_integer(nonce) + _der(0x01, b"\xff"))


def _read(data: bytes, offset: int) -> tuple[int, int, int]:
    """(tag, content start, content end) of the DER element at ``offset``."""
    tag, first = data[offset], data[offset + 1]
    if first < 0x80:
        return tag, offset + 2, offset + 2 + first
    size = first & 0x7F
    length = int.from_bytes(data[offset + 2 : offset + 2 + size], "big")
    start = offset + 2 + size
    return tag, start, start + length


def response_status(response: bytes) -> tuple[int, bool]:
    """``(PKIStatus, has_token)`` of a DER ``TimeStampResp``; raises ``ValueError`` if malformed."""
    try:
        tag, start, end = _read(response, 0)
        if tag != 0x30 or end > len(response):
            raise ValueError("TimeStampResp is not a SEQUENCE")
        tag, info_start, info_end = _read(response, start)
        if tag != 0x30:
            raise ValueError("PKIStatusInfo is not a SEQUENCE")
        tag, status_start, status_end = _read(response, info_start)
        if tag != 0x02:
            raise ValueError("PKIStatus is not an INTEGER")
        return int.from_bytes(response[status_start:status_end], "big"), info_end < end
    except IndexError as exc:
        raise ValueError("truncated TimeStampResp") from exc


class TimestampAuthority:
    """An RFC 3161 TSA reached over HTTP (``application/timestamp-query``)."""

    def __init__(self, url: str, timeout_seconds: float = 10.0) -> None:
        self.url = url
        self._timeout = timeout_seconds

    @classmethod
    def from_env(cls) -> Optional[TimestampAuthority]:
        url = os.getenv(TSA_URL_ENV, "").strip()
        return cls(url) if url else None

    async def timestamp(self, message: bytes) -> bytes:
        """The TSA's DER ``TimeStampResp`` over ``message``; raises :class:`TimestampError` unless granted."""
        request = timestamp_request(message, secrets.randbits(63))
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            reply = await client.post(
                self.url, content=request, headers={"Content-Type": "application/timestamp-query"}
            )
        reply.raise_for_status()
        try:
            status, has_token = response_status(reply.content)
        except ValueError as exc:
            raise TimestampError(f"{self.url} returned a malformed TimeStampResp: {exc}") from exc
        if status not in (0, 1) or not has_token:  # granted / grantedWithMods
            raise TimestampError(f"{self.url} refused the time-stamp request (PKIStatus {status}).")
        return reply.content
