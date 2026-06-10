"""Typed error hierarchy for the SKI SDK.

Callers branch on the exception type rather than parsing strings. The API
key is never included in any message or repr.
"""

from __future__ import annotations

from typing import Optional


class SKIError(Exception):
    """Base class for all SKI SDK errors."""


class SKITransportError(SKIError):
    """Network/TLS failure reaching the SKI Model (no HTTP response)."""


class SKIResponseError(SKIError):
    """The SKI Model returned an HTTP error status."""

    def __init__(self, status_code: int, detail: Optional[str] = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SKI Model returned HTTP {status_code}" + (f": {detail}" if detail else ""))


class SKIAuthError(SKIResponseError):
    """401 — missing or invalid API key."""


class SKIServiceUnavailable(SKIResponseError):
    """503 — service not ready (e.g. no Knowledge Graph loaded)."""


class SKIValidationError(SKIResponseError):
    """4xx — the request payload was rejected by the SKI Model."""


__all__ = [
    "SKIAuthError",
    "SKIError",
    "SKIResponseError",
    "SKIServiceUnavailable",
    "SKITransportError",
    "SKIValidationError",
]
