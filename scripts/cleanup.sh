#!/usr/bin/env bash
#
# SKI Framework — cleanup. Removes Python caches and (with explicit opt-in)
# Docker resources. NEVER deletes ledger backups or database state.
#
# Regulatory retention windows vary (commonly 5–10 years). This script
# REFUSES to touch `data/backups/` and `data/ledger/`. Removing audit
# evidence is the operator's responsibility under documented policy.

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

print_header()  { printf "\n%s===================================================%s\n%s%s%s\n%s===================================================%s\n\n" "$GREEN" "$NC" "$GREEN" "$1" "$NC" "$GREEN" "$NC"; }
print_success() { printf "%s✓%s %s\n" "$GREEN" "$NC" "$1"; }
print_warning() { printf "%s⚠%s %s\n" "$YELLOW" "$NC" "$1"; }
print_error()   { printf "%s✗%s %s\n" "$RED" "$NC" "$1" >&2; }

OLDER_THAN=30
CONFIRM=true
DOCKER=false
LOGS=true

show_help() {
cat <<'EOF'
SKI Framework cleanup

Usage: cleanup.sh [OPTIONS]

  --older-than DAYS   Delete *log files* older than N days (default: 30)
  --docker            Also prune stopped containers and dangling images
  --no-logs           Skip log cleanup
  --no-confirm        Do not prompt for confirmation
  --help              This message

This script intentionally does NOT delete:
  * data/backups/         — audit ledger backups (regulatory retention!)
  * data/ledger/          — primary audit ledger state
  * reference-implementation/.env
  * reference-implementation/tls/

To delete those, follow your organisation's documented retention policy.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --older-than) OLDER_THAN="$2"; shift 2 ;;
        --docker)     DOCKER=true; shift ;;
        --no-logs)    LOGS=false; shift ;;
        --no-confirm) CONFIRM=false; shift ;;
        --help|-h)    show_help; exit 0 ;;
        *) print_error "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

print_header "SKI Framework cleanup"
echo "Will remove:"
echo "  * Python caches (__pycache__, .pyc, .coverage, *.egg-info)"
$LOGS   && echo "  * Log files under data/logs/ older than $OLDER_THAN days"
$DOCKER && echo "  * Stopped containers and dangling images"
echo
echo "Will NOT touch:"
echo "  * data/backups/   — audit ledger backups"
echo "  * data/ledger/    — primary audit ledger state"
echo

if [ "$CONFIRM" = true ]; then
    read -r -p "Continue? (y/N) " reply
    [[ "$reply" =~ ^[Yy]$ ]] || { print_warning "Cleanup cancelled"; exit 0; }
fi

deleted=0
while IFS= read -r -d '' dir; do
    rm -rf "$dir"; deleted=$((deleted + 1))
done < <(find . -type d -name __pycache__ -print0 2>/dev/null)
while IFS= read -r -d '' f; do rm -f "$f"; deleted=$((deleted + 1)); done < <(find . -type f -name "*.pyc" -print0 2>/dev/null)
find . -type f -name ".coverage" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
print_success "Cleaned $deleted Python cache entries"

if $LOGS; then
    log_count=0
    for dir in data/logs reference-implementation/logs; do
        [ -d "$dir" ] || continue
        while IFS= read -r -d '' f; do rm -f "$f"; log_count=$((log_count + 1)); done < <(find "$dir" -type f -mtime "+${OLDER_THAN}" -print0 2>/dev/null)
    done
    print_success "Removed $log_count log files older than $OLDER_THAN days"
fi

if $DOCKER; then
    docker container prune -f >/dev/null
    docker image prune -f >/dev/null
    print_success "Pruned stopped containers and dangling images"
fi

print_header "Done"
