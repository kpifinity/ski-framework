#!/usr/bin/env bash
#
# SKI Framework — deploy helper. Wraps docker compose for the reference
# implementation. The reference implementation is sovereign by default —
# no cloud API key is required or accepted by this script.

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

print_header() { printf "\n%s===%s %s\n" "$GREEN" "$NC" "$1"; }
print_info()   { printf "%sℹ%s %s\n" "$BLUE" "$NC" "$1"; }
print_success(){ printf "%s✓%s %s\n" "$GREEN" "$NC" "$1"; }
print_error()  { printf "%s✗%s %s\n" "$RED" "$NC" "$1" >&2; }

show_help() {
cat <<'EOF'
SKI Framework deploy

Usage: deploy.sh [OPTIONS]

  --stack <name>          Stack to deploy (only "reference-implementation" today)
  --profile <name>        Optional docker compose profile (kafka, pgadmin)
  --help                  This message.

The script does NOT take an --anthropic-key flag and does not check for one.
The default inference backend is the local Ollama runtime.
EOF
}

STACK="reference-implementation"
PROFILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stack) STACK="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --help|-h) show_help; exit 0 ;;
        *) print_error "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

stack_dir="$REPO_ROOT/$STACK"
if [ ! -d "$stack_dir" ]; then
    print_error "Stack directory not found: $stack_dir"
    exit 1
fi

env_file="$stack_dir/.env"
if [ ! -f "$env_file" ]; then
    print_error "No .env at $env_file. Run scripts/setup.sh first."
    exit 1
fi

print_header "Deploying $STACK"

compose=(docker compose -f "$stack_dir/docker-compose.yml" --env-file "$env_file")
if [ -n "$PROFILE" ]; then
    compose+=(--profile "$PROFILE")
fi

"${compose[@]}" up -d

print_info "Waiting up to 90s for SKI Model to report healthy…"
deadline=$(( SECONDS + 90 ))
while (( SECONDS < deadline )); do
    if curl -k -fsS "https://localhost:8000/api/health" >/dev/null 2>&1; then
        print_success "SKI Model healthy at https://localhost:8000"
        exit 0
    fi
    sleep 2
done

print_error "SKI Model did not become healthy within 90s."
"${compose[@]}" logs --tail=80 ski-model || true
exit 1
