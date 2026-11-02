#!/usr/bin/env python3
"""Mutation score of a ``mutmut run``, not counting mutants that only change string text.

mutmut mutates every string literal, so log messages and human-readable notes
produce survivors no test should pin. This script reads mutmut's results
(``mutants/**/*.py.meta``) and, for each mutant, compares the mutated function
with the original (``x_<name>__mutmut_orig``) in the mutants sandbox: when
they are identical once every string constant is blanked, the mutant changed
text only and is excluded. Score = killed / (killed + survived) over the rest.

Usage: python scripts/mutation_score.py reference-implementation/mutants --min-score 0.82
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

_MUTANT = re.compile(r"^(?P<module>.+?)\.(?P<func>(?:x_|xǁ).+?)__mutmut_(?P<n>\d+)$")


class _BlankStrings(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.Constant(value="") if isinstance(node.value, str) else node


def _functions(source: Path) -> dict[str, str]:
    """Function name -> AST dump with string constants blanked, for every def in the mutant sandbox file."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = _BlankStrings().visit(ast.Module(body=node.body, type_ignores=[]))
            out[node.name] = ast.dump(body, include_attributes=False)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mutants_dir", type=Path)
    parser.add_argument("--min-score", type=float, default=0.0)
    args = parser.parse_args(argv)

    killed = survived = text_only = unchecked = 0
    survivors: list[str] = []
    for meta_path in sorted(args.mutants_dir.rglob("*.py.meta")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        functions = _functions(meta_path.with_suffix(""))
        for key, exit_code in meta.get("exit_code_by_key", {}).items():
            match = _MUTANT.match(key)
            if exit_code is None or match is None:
                unchecked += 1
                continue
            mutated = functions.get(f"{match['func']}__mutmut_{match['n']}")
            original = functions.get(f"{match['func']}__mutmut_orig")
            if mutated is not None and mutated == original:
                text_only += 1
            elif exit_code == 0:
                survived += 1
                survivors.append(key)
            else:
                killed += 1
    counted = killed + survived
    score = killed / counted if counted else 0.0
    print(f"killed {killed}, survived {survived}, text-only {text_only} (excluded), unchecked {unchecked}")
    print(f"mutation score: {score:.1%} (minimum {args.min_score:.0%})")
    for key in survivors:
        print(f"  survived: {key}")
    if counted == 0:
        print("no mutants were checked", file=sys.stderr)
        return 1
    return 0 if score >= args.min_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
