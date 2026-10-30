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
# v3.2.0: the runtime refuses to start on FakeLLM without this explicit opt-in.
os.environ.setdefault("SKI_ALLOW_FAKE_LLM", "true")
# FakeLLM is not a sovereign backend, so the spec §6 strict default would
# refuse to start; the strict checks have their own tests.
os.environ.setdefault("SKI_SOVEREIGNTY", "advisory")
# Tests provision throwaway transcript keys under tmp_path. The fail-closed
# default (no generation without this flag) is covered in test_signing.py.
os.environ.setdefault("SKI_ALLOW_KEY_GENERATION", "true")
