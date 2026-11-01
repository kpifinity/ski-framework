"""The black-box suite's LLM hook: an OpenAI-compatible chat-completions server that answers from a script.

The implementation under test is configured to use this server as its
language model (any OpenAI-compatible base URL). A test scripts the answer
for one evaluation before sending it, keyed by a unique *token* the test puts
in the telemetry record's measurement object (as ``conformance_token``, a
field no obligation maps). Every prompt carries the measurement (spec §5.2),
so the token reaches the request whatever the implementation's prompt
template looks like. The scripted ``content`` is the
raw model output, usually the JSON verdict object the implementation's
structured-generation grammar asks for (spec §5.2): ``verdict``,
``reasoning``, ``kg_citations``, ``formalizable_assertions``. It can also be
malformed on purpose.

Routes:

* ``GET /v1/models``: one model, the name given on the command line.
* ``POST /v1/chat/completions``: the scripted content for the first token
  found in the request body. An unscripted request gets HTTP 503, which an
  implementation must treat as an LLM failure (fail closed).
* ``POST /__script`` ``{"token": str, "content": str}``: script one answer.
* ``GET /__requests?token=<token>``: the request bodies that carried the token.

Standard library only, so it runs anywhere the suite runs. Usage:
``python scripted_llm.py MODEL_NAME PORT [HOST]``.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

_LOCK = threading.Lock()
_SCRIPTS: dict[str, str] = {}
_REQUESTS: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    model_name = "scripted"

    def _send(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> str:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": self.model_name, "object": "model"}]})
        elif url.path == "/__requests":
            token = parse_qs(url.query).get("token", [""])[0]
            with _LOCK:
                self._send(200, [r for r in _REQUESTS if token and token in r])
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        body = self._body()
        if url.path == "/__script":
            script = json.loads(body)
            with _LOCK:
                _SCRIPTS[str(script["token"])] = str(script["content"])
            self._send(200, {"scripted": script["token"]})
            return
        if url.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        with _LOCK:
            _REQUESTS.append(body)
            content = next((c for t, c in _SCRIPTS.items() if t in body), None)
        if content is None:
            self._send(503, {"error": {"message": "no scripted answer for this request"}})
            return
        self._send(
            200,
            {
                "id": "chatcmpl-scripted",
                "object": "chat.completion",
                "model": self.model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("scripted-llm: " + format % args + "\n")


def serve(model_name: str, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """A running server (in a daemon thread); call ``shutdown()`` to stop it."""
    _Handler.model_name = model_name
    server = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    _Handler.model_name = sys.argv[1]
    ThreadingHTTPServer(
        (sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1", int(sys.argv[2])), _Handler
    ).serve_forever()
