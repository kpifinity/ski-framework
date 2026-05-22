#!/usr/bin/env bash
#
# SKI Framework — first-run setup script.
#
# Generates strong random secrets, self-signed TLS certs, writes a .env
# file with 0600 permissions, and verifies the host has the prerequisites
# the reference implementation needs.
#
# This script does NOT make any cloud-API calls. It does NOT require an
# Anthropic, OpenAI, or any other vendor API key.

set -euo pipefail

# ---- pretty-printing --------------------------------------------------------
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

print_header() { printf "\n%s===================================================%s\n%s%s%s\n%s===================================================%s\n\n" "$GREEN" "$NC" "$GREEN" "$1" "$NC" "$GREEN" "$NC"; }
print_success() { printf "%s✓%s %s\n" "$GREEN" "$NC" "$1"; }
print_error()   { printf "%s✗%s %s\n" "$RED" "$NC" "$1" >&2; }
print_warning() { printf "%s⚠%s %s\n" "$YELLOW" "$NC" "$1"; }

# ---- prereqs ----------------------------------------------------------------
check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "$1 is not installed"
        return 1
    fi
    print_success "$1 found"
}

main() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    cd "$REPO_ROOT"

    print_header "SKI Framework setup"

    print_header "Checking prerequisites"
    all_ok=true
    check_command docker || all_ok=false
    check_command python3 || all_ok=false
    check_command openssl || all_ok=false
    if ! docker compose version >/dev/null 2>&1; then
        print_error "docker compose v2 is required (try 'docker compose version')"
        all_ok=false
    else
        print_success "docker compose v2 found"
    fi
    [ "$all_ok" = true ] || { print_error "Missing prerequisites"; exit 1; }

    env_file="$REPO_ROOT/reference-implementation/.env"
    env_example="$REPO_ROOT/reference-implementation/.env.example"
    tls_dir="$REPO_ROOT/reference-implementation/tls"
    grafana_tls="$tls_dir/grafana"

    print_header "Generating secrets"
    if [ -f "$env_file" ]; then
        print_warning ".env already exists at $env_file — not overwriting."
    else
        cp "$env_example" "$env_file"

        SKI_API_KEY=$(openssl rand -hex 32)
        POSTGRES_USER="ski_${RANDOM}${RANDOM}"
        POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-40)
        GRAFANA_USER="grafana_admin"
        GRAFANA_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-40)

        # macOS / Linux compatible in-place sed
        sed_i() { if [ "$(uname)" = "Darwin" ]; then sed -i '' "$@"; else sed -i "$@"; fi; }
        sed_i "s|^SKI_API_KEY=.*|SKI_API_KEY=${SKI_API_KEY}|" "$env_file"
        sed_i "s|^POSTGRES_USER=.*|POSTGRES_USER=${POSTGRES_USER}|" "$env_file"
        sed_i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" "$env_file"
        sed_i "s|^GRAFANA_USER=.*|GRAFANA_USER=${GRAFANA_USER}|" "$env_file"
        sed_i "s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=${GRAFANA_PASSWORD}|" "$env_file"

        chmod 600 "$env_file"
        print_success "Wrote $env_file (0600)"
        print_warning "Strong random secrets generated. They are in the .env file only — they will NOT be reprinted."
    fi

    print_header "Generating self-signed TLS certificates"
    mkdir -p "$tls_dir" "$grafana_tls"
    if [ -f "$tls_dir/ski-model.crt" ]; then
        print_warning "TLS certs already exist in $tls_dir — not regenerating."
    else
        # Local CA
        openssl req -x509 -newkey rsa:4096 -sha256 -nodes -keyout "$tls_dir/ca.key" \
            -out "$tls_dir/ca.crt" -days 825 -subj "/CN=ski-local-ca" >/dev/null 2>&1

        # SKI Model service cert (CN=ski-model so sidecar SNI matches)
        openssl req -newkey rsa:4096 -sha256 -nodes -keyout "$tls_dir/ski-model.key" \
            -out "$tls_dir/ski-model.csr" -subj "/CN=ski-model" >/dev/null 2>&1
        openssl x509 -req -in "$tls_dir/ski-model.csr" -CA "$tls_dir/ca.crt" \
            -CAkey "$tls_dir/ca.key" -CAcreateserial -out "$tls_dir/ski-model.crt" \
            -days 825 -sha256 >/dev/null 2>&1
        rm -f "$tls_dir/ski-model.csr" "$tls_dir/ca.srl"

        # Grafana cert
        openssl req -newkey rsa:4096 -sha256 -nodes -keyout "$grafana_tls/grafana.key" \
            -out "$grafana_tls/grafana.csr" -subj "/CN=ski-grafana" >/dev/null 2>&1
        openssl x509 -req -in "$grafana_tls/grafana.csr" -CA "$tls_dir/ca.crt" \
            -CAkey "$tls_dir/ca.key" -CAcreateserial -out "$grafana_tls/grafana.crt" \
            -days 825 -sha256 >/dev/null 2>&1
        rm -f "$grafana_tls/grafana.csr" "$tls_dir/ca.srl"

        chmod -R go-rwx "$tls_dir"
        print_success "Self-signed CA and per-service certs generated under $tls_dir"
        print_warning "Replace with certs from your own CA before any non-local deployment."
    fi

    print_header "Optional: Python dev environment"
    if [ -f "$REPO_ROOT/requirements-dev.txt" ]; then
        if [ -d ".venv" ]; then
            print_warning "Existing .venv detected — skipping creation."
        else
            python3 -m venv .venv
            # shellcheck disable=SC1091
            . .venv/bin/activate
            pip install -q -r requirements-dev.txt
            print_success "Installed dev requirements into .venv"
        fi
    fi

    print_header "Next steps"
    cat <<EOF
1. (One time) Pull the local LLM weights into the Ollama volume:
     docker compose -f reference-implementation/docker-compose.yml up -d ollama
     docker exec ski-ollama ollama pull qwen2.5:7b-instruct

2. Start the full stack:
     docker compose -f reference-implementation/docker-compose.yml up -d

3. Verify health (note: HTTPS, self-signed):
     curl -k https://localhost:8000/api/health

4. Send a sample telemetry record:
     python scripts/send-telemetry.py examples/energy/telemetry/sample.jsonl

5. Verify the audit ledger:
     python scripts/verify-ledger.py

Read reference-implementation/SECURITY_DEFAULTS.md before any production use.
EOF
}

main "$@"
