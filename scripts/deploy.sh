#!/bin/bash

################################################################################
# SKI Framework Deploy Script
# Deploy to infrastructure (Docker, Kubernetes, or direct)
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Defaults
DEPLOYMENT_MODE="docker"
STACK="reference-implementation"
CONFIG_FILE=""

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

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

show_help() {
    cat << EOF
SKI Framework Deploy Script

Usage: deploy.sh [OPTIONS]

Options:
  --mode MODE              Deployment mode: docker, kubernetes, direct (default: docker)
  --stack STACK           Stack to deploy: reference-implementation (default)
  --config FILE           Configuration file path
  --environment ENV       Environment: dev, staging, prod (default: dev)
  --help                  Show this help message

Examples:
  # Deploy reference implementation with Docker
  ./scripts/deploy.sh --mode docker

  # Deploy with custom config
  ./scripts/deploy.sh --mode docker --config my-config.yaml

  # Deploy to Kubernetes
  ./scripts/deploy.sh --mode kubernetes --environment prod

EOF
}

################################################################################
# Argument Parsing
################################################################################

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --mode)
                DEPLOYMENT_MODE="$2"
                shift 2
                ;;
            --stack)
                STACK="$2"
                shift 2
                ;;
            --config)
                CONFIG_FILE="$2"
                shift 2
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
}

################################################################################
# Deployment Functions
################################################################################

deploy_docker() {
    print_header "Deploying with Docker"

    local stack_dir="$STACK"

    if [ ! -d "$stack_dir" ]; then
        print_error "Stack directory not found: $stack_dir"
        exit 1
    fi

    cd "$stack_dir"

    # Check for environment file
    if [ ! -f .env ]; then
        if [ ! -f .env.example ]; then
            print_error ".env.example not found in $stack_dir"
            exit 1
        fi
        cp .env.example .env
        print_info "Created .env from template (edit .env to configure)"
    fi

    # Check API key
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        print_error "ANTHROPIC_API_KEY environment variable not set"
        exit 1
    fi

    print_info "Starting Docker services..."
    docker-compose up -d

    print_success "Docker deployment started"
    print_info "Waiting for services to initialize..."
    sleep 30

    # Verify deployment
    if verify_deployment; then
        print_success "Deployment successful!"
        print_info "API: http://localhost:8000"
        print_info "Grafana: http://localhost:3000 (admin/admin)"
        print_info "Prometheus: http://localhost:9090"
    else
        print_error "Deployment verification failed"
        docker-compose logs
        exit 1
    fi

    cd - > /dev/null
}

deploy_kubernetes() {
    print_header "Deploying to Kubernetes"
    print_error "Kubernetes deployment not yet implemented"
    print_info "For now, use Docker deployment: ./scripts/deploy.sh --mode docker"
    exit 1
}

deploy_direct() {
    print_header "Deploying Direct Installation"
    print_error "Direct installation deployment not yet implemented"
    print_info "For now, use Docker deployment: ./scripts/deploy.sh --mode docker"
    exit 1
}

verify_deployment() {
    print_info "Verifying deployment..."

    # Check if MiLM is responding
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        echo -n "."
        sleep 1
    done

    echo ""
    return 1
}

################################################################################
# Main
################################################################################

main() {
    print_header "SKI Framework Deploy"

    parse_args "$@"

    print_info "Configuration:"
    echo "  Deployment Mode: $DEPLOYMENT_MODE"
    echo "  Stack: $STACK"
    echo "  Config File: ${CONFIG_FILE:-default}"
    echo ""

    case $DEPLOYMENT_MODE in
        docker)
            deploy_docker
            ;;
        kubernetes)
            deploy_kubernetes
            ;;
        direct)
            deploy_direct
            ;;
        *)
            print_error "Unknown deployment mode: $DEPLOYMENT_MODE"
            exit 1
            ;;
    esac
}

main "$@"
