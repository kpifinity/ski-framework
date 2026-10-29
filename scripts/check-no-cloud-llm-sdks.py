#!/usr/bin/env python3
"""Fail if a cloud-LLM SDK is part of the SKI runtime (sovereignty guard).

The SKI Model has no cloud inference backend, so a hosted-LLM client
library has no business in its dependency closure: its mere presence is
an egress capability an attacker or a careless change could use. CI runs
this in two places:

* against the runtime requirements files (default arguments), and
* against the distributions actually installed in the built image::

    docker run --rm --entrypoint python ski-model:ci -c \\
      "import importlib.metadata as m; print('\\n'.join(d.metadata['Name'] for d in m.distributions()))" \\
      | python scripts/check-no-cloud-llm-sdks.py --names -

Build-time tools outside the runtime (``tools/kg-extractor``, which may
call a hosted model while *compiling* a KG) are deliberately not checked.

Exit status: 0 clean, 1 a denied SDK was found, 2 usage / unreadable input.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Distribution names (PEP 503-normalised) of hosted-LLM client SDKs. A deny
# list is never complete; it catches the common ones. Extend it, never shrink it.
DENIED = frozenset(
    {
        "anthropic",
        "openai",
        "google-generativeai",
        "google-genai",
        "google-cloud-aiplatform",
        "vertexai",
        "cohere",
        "mistralai",
        "groq",
        "together",
        "azure-ai-inference",
        "litellm",
    }
)

RUNTIME_REQUIREMENTS = (
    REPO_ROOT / "reference-implementation" / "src" / "ski_model" / "requirements.txt",
    REPO_ROOT / "reference-implementation" / "src" / "sidecar" / "requirements.txt",
)

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_INCLUDE = re.compile(r"^\s*(?:-r|--requirement|-c|--constraint)(?:\s+|=)(\S+)")


def normalize(name: str) -> str:
    """PEP 503 normalisation: lower-case, runs of ``-_.`` become ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names(path: Path, _seen: Optional[Set[Path]] = None) -> Iterator[Tuple[Path, int, str]]:
    """Yield ``(file, line_no, distribution_name)``, following ``-r`` / ``-c`` includes."""
    seen = set() if _seen is None else _seen
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        include = _INCLUDE.match(line)
        if include:
            yield from requirement_names(path.parent / include.group(1), seen)
            continue
        if line.startswith("-"):
            continue  # other pip options (--index-url, -e paths, ...)
        match = _NAME.match(line)
        if match:
            yield path, line_no, match.group(1)


def find_denied(entries: Iterable[Tuple[str, str]]) -> List[str]:
    """Return a report line for every ``(where, name)`` whose name is denied."""
    return [f"{where}: {name}" for where, name in entries if normalize(name) in DENIED]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "requirements",
        nargs="*",
        type=Path,
        help="requirements files to check (default: the SKI runtime requirements)",
    )
    parser.add_argument(
        "--names",
        metavar="FILE",
        help="check newline-separated distribution names instead ('-' = stdin), e.g. from a built image",
    )
    args = parser.parse_args(argv)

    try:
        if args.names is not None:
            text = sys.stdin.read() if args.names == "-" else Path(args.names).read_text(encoding="utf-8")
            names = [line.strip() for line in text.splitlines() if line.strip()]
            if not names:
                print("error: no distribution names given", file=sys.stderr)
                return 2
            findings = find_denied(("installed", name) for name in names)
            checked = f"{len(names)} installed distributions"
        else:
            files = args.requirements or list(RUNTIME_REQUIREMENTS)
            findings = find_denied(
                (f"{path}:{line_no}", name) for req in files for path, line_no, name in requirement_names(req)
            )
            checked = ", ".join(str(f) for f in files)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if findings:
        print("Cloud-LLM SDK(s) found in the SKI runtime (sovereignty violation):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(f"Denied distributions: {', '.join(sorted(DENIED))}", file=sys.stderr)
        return 1
    print(f"OK: no cloud-LLM SDK in {checked}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
