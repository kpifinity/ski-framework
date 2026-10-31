"""Boot the runtime exactly as the image does, plus one conformance-only route.

The strict-mode air-gap rig must show the egress guard refusing a call made
from *inside* the runtime process, which no production route does on
purpose. This harness adds ``POST /conformance/egress-probe``, which tries
one outbound TCP connect and one outbound DNS lookup, then starts the
server through the image's own entry point (:func:`ski_model.server.main`),
so startup, the strict checks, TLS and the guard are the shipped ones.

It lives in conformance/, never in the image.
"""

from __future__ import annotations

import socket
from typing import Callable, Dict

from fastapi import Depends
from ski_model import server


@server.app.post("/conformance/egress-probe", dependencies=[Depends(server.require_api_key)])
def egress_probe() -> Dict[str, str]:
    """Attempt two outbound calls; report what stopped each one."""
    attempts: Dict[str, Callable[[], object]] = {
        "connect": lambda: socket.create_connection(("203.0.113.10", 443), timeout=2).close(),
        "lookup": lambda: socket.getaddrinfo("egress-canary.example.com", 443),
    }
    outcome: Dict[str, str] = {}
    for name, attempt in attempts.items():
        try:
            attempt()
            outcome[name] = "connected"
        except Exception as exc:
            outcome[name] = type(exc).__name__
    return outcome


if __name__ == "__main__":
    server.main()
