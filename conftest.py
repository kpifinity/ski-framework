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
# ski-schemas (RFC 0003 PR 1): the shared wire-model package, importable
# without an editable install for the same reason as the runtime src.
_SCHEMAS_SRC = _REPO_ROOT / "tools" / "ski-schemas" / "src"

for _p in (_SRC, _SCHEMAS_SRC):
    if _p.is_dir():
        _p_str = str(_p)
        if _p_str not in sys.path:
            sys.path.insert(0, _p_str)
