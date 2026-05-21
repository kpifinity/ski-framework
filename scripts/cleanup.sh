#!/bin/bash

################################################################################
# SKI Framework Cleanup Script
# Clean up temporary files, logs, and test data
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Defaults
OLDER_THAN=30
CONFIRM=true

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo -e "\n${GREEN}===================================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}===================================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

show_help() {
    cat << EOF
SKI Framework Cleanup Script

Usage: cleanup.sh [OPTIONS]

Options:
  --older-than DAYS       Delete files older than N days (default: 30)
  --no-confirm            Don't ask for confirmation
  --help                  Show this help message

Examples:
  # Clean files older than 30 days
  ./scripts/cleanup.sh

  # Clean files older than 7 days
  ./scripts/cleanup.sh --older-than 7

  # Clean without confirmation
  ./scripts/cleanup.sh --no-confirm

EOF
}

################################################################################
# Cleanup Functions
################################################################################

cleanup_logs() {
    print_warning "Cleaning logs older than $OLDER_THAN days..."

    local deleted=0

    for dir in data/logs reference-implementation/logs; do
        if [ -d "$dir" ]; then
            while IFS= read -r -d '' file; do
                rm -f "$file"
                deleted=$((deleted + 1))
            done < <(find "$dir" -type f -mtime +$OLDER_THAN -print0 2>/dev/null)
        fi
    done

    print_success "Deleted $deleted old log files"
}

cleanup_temp() {
    print_warning "Cleaning temporary files..."

    local deleted=0

    # Remove __pycache__ directories
    while IFS= read -r -d '' dir; do
        rm -rf "$dir"
        deleted=$((deleted + 1))
    done < <(find . -type d -name __pycache__ -print0 2>/dev/null)

    # Remove .pyc files
    while IFS= read -r -d '' file; do
        rm -f "$file"
        deleted=$((deleted + 1))
    done < <(find . -type f -name "*.pyc" -print0 2>/dev/null)

    # Remove test artifacts
    deleted=$((deleted + $(find . -type f -name ".coverage" -o -name "*.egg-info" | wc -l)))
    find . -type f -name ".coverage" -delete 2>/dev/null
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null

    print_success "Deleted $deleted temporary files"
}

cleanup_docker() {
    print_warning "Cleaning Docker resources..."

    local deleted=0

    # Remove stopped containers
    if docker ps -a --format '{{.Status}}' | grep -q "Exited"; then
        deleted=$((deleted + $(docker ps -a --format '{{.Status}}' | grep "Exited" | wc -l)))
        docker container prune -f > /dev/null 2>&1
    fi

    # Remove unused images
    if docker images --format '{{.Repository}}' | grep -q "none"; then
        docker image prune -f > /dev/null 2>&1
    fi

    print_success "Cleaned Docker resources"
}

cleanup_database() {
    print_warning "Cleaning old database backups..."

    local deleted=0
    local backup_dir="data/backups"

    if [ -d "$backup_dir" ]; then
        while IFS= read -r -d '' file; do
            rm -f "$file"
            deleted=$((deleted + 1))
        done < <(find "$backup_dir" -type f -mtime +90 -print0 2>/dev/null)
    fi

    print_success "Deleted $deleted old backup files"
}

################################################################################
# Main
################################################################################

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --older-than)
                OLDER_THAN="$2"
                shift 2
                ;;
            --no-confirm)
                CONFIRM=false
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    print_header "SKI Framework Cleanup"

    # Show what will be cleaned
    echo "This will clean:"
    echo "  • Log files older than $OLDER_THAN days"
    echo "  • Python cache and temporary files"
    echo "  • Docker stopped containers and images"
    echo "  • Database backups older than 90 days"
    echo ""

    if [ "$CONFIRM" = true ]; then
        read -p "Continue? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_warning "Cleanup cancelled"
            exit 0
        fi
    fi

    # Run cleanup
    cleanup_logs
    cleanup_temp
    cleanup_docker
    cleanup_database

    print_header "Cleanup Complete!"
    echo "Disk space freed: $(du -sh . | cut -f1)"
}

main "$@"
