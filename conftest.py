"""Root pytest conftest — makes the reference-implementation packages importable.

The repo uses a src-layout under ``reference-implementation/src/`` but does
not install those packages with ``pip install -e .`` because there is no
top-level ``pyproject.toml`` package definition. Adding the src directory
to ``sys.path`` at pytest collection time gives every test file the same
import view CI uses for the v3 runtime tests.

This file affects only the test session; it is not imported at runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "reference-implementation" / "src"

if _SRC.is_dir():
    src_str = str(_SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
