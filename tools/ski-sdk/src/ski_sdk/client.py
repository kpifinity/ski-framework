"""Synchronous and asynchronous HTTP clients for the SKI Model.

Thin wrappers over httpx that send the API key as the ``x-api-key`` header,
verify TLS by default, parse responses into typed models, and map HTTP status
codes onto the SDK error hierarchy. Idempotent GETs are retried with backoff;
non-idempotent POSTs are not.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Union

import httpx

from .errors import (
    SKIAuthError,
    SKIResponseError,
    SKIServiceUnavailable,
    SKITransportError,
    SKIValidationError,
)
from .models import HealthStatus, MeasurementRecord, V3VerdictEnvelope

_DEFAULT_TIMEOUT = 30.0


def _detail(resp: httpx.Response) -> Optional[str]:
    try:
        body = resp.json()
        return body.get("detail") if isinstance(body, dict) else None
    except Exception:
        return None


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    detail = _detail(resp)
    if resp.status_code == 401:
        raise SKIAuthError(401, detail)
    if resp.status_code == 503:
        raise SKIServiceUnavailable(503, detail)
    if 400 <= resp.status_code < 500:
        raise SKIValidationError(resp.status_code, detail)
    raise SKIResponseError(resp.status_code, detail)


def _headers(api_key: Optional[str]) -> Dict[str, str]:
    return {"x-api-key": api_key} if api_key else {}


class _Base:
    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        *,
        verify_tls: Union[bool, str] = True,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = 2,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._max_retries = max_retries

    def __repr__(self) -> str:  # never leak the API key
        return (
            f"{type(self).__name__}(endpoint={self._endpoint!r}, api_key={'***' if self._api_key else None})"
        )


class SKIClient(_Base):
    """Synchronous SKI Model client."""

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        *,
        verify_tls: Union[bool, str] = True,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = 2,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        super().__init__(endpoint, api_key, verify_tls=verify_tls, timeout=timeout, max_retries=max_retries)
        self._client = httpx.Client(
            base_url=self._endpoint,
            verify=verify_tls,
            timeout=timeout,
            headers=_headers(api_key),
            transport=transport,
        )

    def __enter__(self) -> SKIClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = self._client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt >= self._max_retries:
                    raise SKITransportError(str(exc)) from exc
            else:
                if resp.status_code < 500 or attempt >= self._max_retries:
                    _raise_for_status(resp)
                    return resp
            time.sleep(0.25 * (2**attempt))
            attempt += 1

    def _post(self, path: str, json_body: Dict[str, Any]) -> httpx.Response:
        try:
            resp = self._client.post(path, json=json_body)
        except httpx.RequestError as exc:
            raise SKITransportError(str(exc)) from exc
        _raise_for_status(resp)
        return resp

    def evaluate(
        self,
        *,
        measurement_id: str,
        timestamp: str,
        subject: str,
        measurement: Dict[str, Any],
        jurisdiction: Optional[str] = None,
    ) -> V3VerdictEnvelope:
        body = MeasurementRecord(
            measurement_id=measurement_id,
            timestamp=timestamp,
            subject=subject,
            measurement=measurement,
            jurisdiction=jurisdiction,
        ).model_dump()
        return V3VerdictEnvelope.model_validate(self._post("/api/evaluate", body).json())

    def health(self) -> HealthStatus:
        return HealthStatus.model_validate(self._get("/api/health").json())

    def list_verdicts(self, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return dict(self._get("/api/verdicts", params={"limit": limit, "offset": offset}).json())

    def load_kg(self, signed_kg: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._post("/api/kg/load", signed_kg).json())


class AsyncSKIClient(_Base):
    """Asynchronous SKI Model client (mirrors :class:`SKIClient`)."""

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        *,
        verify_tls: Union[bool, str] = True,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = 2,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        super().__init__(endpoint, api_key, verify_tls=verify_tls, timeout=timeout, max_retries=max_retries)
        self._client = httpx.AsyncClient(
            base_url=self._endpoint,
            verify=verify_tls,
            timeout=timeout,
            headers=_headers(api_key),
            transport=transport,
        )

    async def __aenter__(self) -> AsyncSKIClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = await self._client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt >= self._max_retries:
                    raise SKITransportError(str(exc)) from exc
            else:
                if resp.status_code < 500 or attempt >= self._max_retries:
                    _raise_for_status(resp)
                    return resp
            await asyncio.sleep(0.25 * (2**attempt))
            attempt += 1

    async def _post(self, path: str, json_body: Dict[str, Any]) -> httpx.Response:
        try:
            resp = await self._client.post(path, json=json_body)
        except httpx.RequestError as exc:
            raise SKITransportError(str(exc)) from exc
        _raise_for_status(resp)
        return resp

    async def evaluate(
        self,
        *,
        measurement_id: str,
        timestamp: str,
        subject: str,
        measurement: Dict[str, Any],
        jurisdiction: Optional[str] = None,
    ) -> V3VerdictEnvelope:
        body = MeasurementRecord(
            measurement_id=measurement_id,
            timestamp=timestamp,
            subject=subject,
            measurement=measurement,
            jurisdiction=jurisdiction,
        ).model_dump()
        resp = await self._post("/api/evaluate", body)
        return V3VerdictEnvelope.model_validate(resp.json())

    async def health(self) -> HealthStatus:
        resp = await self._get("/api/health")
        return HealthStatus.model_validate(resp.json())

    async def list_verdicts(self, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        resp = await self._get("/api/verdicts", params={"limit": limit, "offset": offset})
        return dict(resp.json())

    async def load_kg(self, signed_kg: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._post("/api/kg/load", signed_kg)
        return dict(resp.json())


__all__ = ["AsyncSKIClient", "SKIClient"]
