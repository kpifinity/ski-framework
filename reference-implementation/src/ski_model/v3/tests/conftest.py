"""Test-time configuration for the v3 runtime tests.

The server module reads ``API_KEY_REQUIRED`` and ``SKI_V3_LLM_BACKEND``
at import time as module-level constants. This conftest sets sensible
defaults BEFORE the tests import the server, so test files can keep all
imports at the top (no ``E402`` / ``# noqa`` thicket).
"""

from __future__ import annotations

import os

os.environ.setdefault("API_KEY_REQUIRED", "false")
os.environ.setdefault("SKI_V3_LLM_BACKEND", "fake")
