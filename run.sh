#!/bin/bash

# Product Search Engine - Startup Script
# Starts Elasticsearch and FastAPI server

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ES_DIR="$SCRIPT_DIR/infra/elasticsearch"
SRC_DIR="$SCRIPT_DIR/src"

# Functions
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    if ! command -v uv &> /dev/null; then
        print_error "uv is not installed. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    
    print_success "All prerequisites met"
}

# Start Elasticsearch
start_elasticsearch() {
    print_info "Starting Elasticsearch..."
    
    cd "$ES_DIR"
    
    # Check if already running
    if docker ps | grep -q elasticsearch; then
        print_warning "Elasticsearch container is already running"
        return 0
    fi
    
    # Use docker compose or docker-compose
    if docker compose version &> /dev/null; then
        docker compose up -d
    else
        docker-compose up -d
    fi
    
    print_success "Elasticsearch container started"
}

# Wait for Elasticsearch to be healthy
wait_for_elasticsearch() {
    print_info "Waiting for Elasticsearch to be healthy..."
    
    local max_attempts=30
    local attempt=0
    local es_password="${ELASTIC_PASSWORD:-changeme}"
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s -u "elastic:$es_password" http://localhost:9200/_cluster/health > /dev/null 2>&1; then
            print_success "Elasticsearch is healthy"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    
    echo ""
    print_error "Elasticsearch failed to become healthy after $max_attempts attempts"
    print_info "Check logs with: docker logs elasticsearch"
    exit 1
}

# Install dependencies
install_dependencies() {
    print_info "Installing Python dependencies..."
    
    cd "$SRC_DIR"
    
    if [ ! -d ".venv" ]; then
        print_info "Creating virtual environment..."
        uv venv
    fi
    
    uv sync
    
    print_success "Dependencies installed"
}

# Start FastAPI server
start_server() {
    print_info "Starting FastAPI server..."
    
    cd "$SRC_DIR"
    
    print_success "Server starting on http://localhost:8000"
    print_info "Press Ctrl+C to stop all services"
    echo ""
    
    # Activate venv and run uvicorn
    source .venv/bin/activate
    python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
}

# Cleanup function
cleanup() {
    echo ""
    print_info "Shutting down..."
    
    # Stop Elasticsearch
    cd "$ES_DIR"
    if docker ps | grep -q elasticsearch; then
        print_info "Stopping Elasticsearch..."
        if docker compose version &> /dev/null; then
            docker compose down
        else
            docker-compose down
        fi
        print_success "Elasticsearch stopped"
    fi
    
    exit 0
}

# Trap Ctrl+C
trap cleanup SIGINT SIGTERM

# Main execution
main() {
    echo "=========================================="
    echo "  Product Search Engine - Startup"
    echo "=========================================="
    echo ""
    
    check_prerequisites
    echo ""
    
    start_elasticsearch
    echo ""
    
    wait_for_elasticsearch
    echo ""
    
    install_dependencies
    echo ""
    
    start_server
}

# Run main function
main

