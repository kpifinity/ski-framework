#!/usr/bin/env bash
# Devcontainer post-create hook for the SKI Framework workspace.
#
# Installs the dev and docs requirements, pre-commit hooks, and the four
# CLI tools in editable mode so contributors can run them from anywhere
# in the workspace. Idempotent — re-running on an existing container is
# safe and is a fast no-op when nothing has changed.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing dev requirements"
pip install -r requirements-dev.txt

echo "==> Installing docs requirements"
pip install -r requirements-docs.txt

echo "==> Installing reference CLIs in editable mode"
for tool in tools/audit-ledger tools/kg-extractor tools/kg-validator tools/ski-model-deploy; do
  if [[ -f "${tool}/pyproject.toml" ]]; then
    pip install -e "${tool}"
  fi
done

echo "==> Installing reference implementation in editable mode"
if [[ -f "reference-implementation/pyproject.toml" ]]; then
  pip install -e reference-implementation
fi

echo "==> Installing pre-commit hook"
pre-commit install --install-hooks

echo "==> Done. Try: pytest -q  |  mkdocs serve -a 0.0.0.0:8765"
