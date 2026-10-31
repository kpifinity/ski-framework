"""A conformance stand-in for vLLM: the OpenAI-compatible API, answered by FakeLLM.

NOT a language model. The strict-mode air-gap rig needs a *sovereign* backend
(spec §6.2 item 1) serving from inside the loopback-only namespace, and a
real vLLM needs a GPU and gigabytes of weights. This server speaks the two
vLLM routes the runtime calls (``GET /v1/models``, ``POST
/v1/chat/completions``) and answers with the deterministic FakeLLM's output
for the measurement and KG snapshot embedded in the prompt, so the rig's
expected verdicts are the same as in the advisory rig.

The runtime still verifies a real weights file: the rig mounts one and pins
its digest (``SKI_MODEL_FILE_SHA256`` + ``SKI_MODEL_FILE_PATH``).

Usage (inside the runtime image): ``python stub_vllm.py MODEL_NAME PORT``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from ski_model.v3.evaluator import FakeLLM

MODEL_NAME = sys.argv[1]
PORT = int(sys.argv[2])


def _section(prompt: str, header: str) -> Dict[str, Any]:
    """The one-line JSON that follows ``header`` in the rendered prompt template."""
    value: Dict[str, Any] = json.loads(prompt.split(f"\n{header}\n", 1)[1].split("\n", 1)[0])
    return value


class Handler(BaseHTTPRequestHandler):
    def _reply(self, body: Dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/v1/models":
            self.send_error(404)
            return
        self._reply({"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = request["messages"][-1]["content"]
        output = asyncio.run(
            FakeLLM().evaluate(
                measurement=_section(prompt, "MEASUREMENT:"),
                kg_snapshot=_section(prompt, "KG SNAPSHOT:"),
                seed=int(request.get("seed", 0)),
            )
        )
        self._reply(
            {
                "object": "chat.completion",
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(output)},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("stub-vllm: " + format % args + "\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
