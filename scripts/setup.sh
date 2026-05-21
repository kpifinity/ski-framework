#!/bin/bash

################################################################################
# SKI Framework Setup Script
# Initial deployment setup and configuration
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/kpifinity/ski-framework.git"
REPO_DIR="ski-framework"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        print_error "$1 is not installed"
        return 1
    fi
    print_success "$1 found"
    return 0
}

################################################################################
# Main Setup
################################################################################

main() {
    print_header "SKI Framework Setup"

    # Check environment
    print_header "Checking Prerequisites"

    local all_ok=true

    check_command "docker" || all_ok=false
    check_command "docker-compose" || all_ok=false
    check_command "python3" || all_ok=false
    check_command "git" || all_ok=false

    if [ "$all_ok" = false ]; then
        print_error "Missing required prerequisites"
        echo "Please install Docker, Docker Compose, Python 3, and Git"
        exit 1
    fi

    # Check disk space
    print_header "Checking Disk Space"
    available_space=$(df /tmp | awk 'NR==2 {print $4}')
    required_space=$((10 * 1024 * 1024))  # 10GB

    if [ "$available_space" -lt "$required_space" ]; then
        print_warning "Low disk space available"
    else
        print_success "Sufficient disk space ($(($available_space / 1024 / 1024))GB available)"
    fi

    # Check RAM
    print_header "Checking Memory"
    available_ram=$(free -m | awk 'NR==2 {print $7}')

    if [ "$available_ram" -lt 4096 ]; then
        print_warning "Less than 4GB free RAM available"
    else
        print_success "Sufficient RAM (${available_ram}MB available)"
    fi

    # Setup directories
    print_header "Creating Directory Structure"

    mkdir -p data/{ledger,backups,logs}
    mkdir -p config
    mkdir -p examples/{knowledge-graphs,telemetry}

    print_success "Directory structure created"

    # Setup environment
    print_header "Setting Up Environment"

    if [ ! -f .env ]; then
        if [ -f reference-implementation/.env.example ]; then
            cp reference-implementation/.env.example .env
            print_success "Created .env from template"
        else
            print_warning ".env.example not found"
        fi
    else
        print_warning ".env already exists, skipping"
    fi

    # Check API key
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        print_warning "ANTHROPIC_API_KEY not set in environment"
        echo "Please set your API key:"
        echo "  export ANTHROPIC_API_KEY=sk-..."
    else
        print_success "ANTHROPIC_API_KEY is set"
    fi

    # Install Python dependencies
    print_header "Installing Python Dependencies"

    if [ -f requirements.txt ]; then
        pip3 install -q -r requirements.txt
        print_success "Python dependencies installed"
    fi

    # Install tools
    print_header "Installing SKI Tools"

    if [ -d "tools/kg-extractor" ]; then
        pip3 install -e tools/kg-extractor -q
        print_success "kg-extractor installed"
    fi

    if [ -d "tools/kg-validator" ]; then
        pip3 install -e tools/kg-validator -q
        print_success "kg-validator installed"
    fi

    if [ -d "tools/milm-deploy" ]; then
        pip3 install -e tools/milm-deploy -q
        print_success "milm-deploy installed"
    fi

    # Summary
    print_header "Setup Complete!"

    echo "Next steps:"
    echo "  1. Set your API key: export ANTHROPIC_API_KEY=sk-..."
    echo "  2. Configure .env file: nano .env"
    echo "  3. Start reference implementation: cd reference-implementation && docker-compose up -d"
    echo "  4. Verify: curl http://localhost:8000/api/health"
    echo ""
    echo "For more information:"
    echo "  - Getting Started: docs/GETTING_STARTED.md"
    echo "  - Deployment: reference-implementation/docs/DEPLOYMENT.md"
    echo "  - Tools: tools/<tool>/README.md"
}

# Run main
main "$@"
