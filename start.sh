#!/bin/bash
# MERID Production Startup Script
# Usage: ./start.sh [environment]
#   environment: development | production | test (default: development)

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT="${1:-development}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="MERID"
PID_FILE="/tmp/merid.pid"

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check Python installation
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    log_info "Python version: $PYTHON_VERSION"
}

# Check environment file
check_env() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            log_warn ".env file not found, copying from .env.example"
            cp .env.example .env
        else
            log_error "No .env or .env.example file found"
            exit 1
        fi
    fi
}

# Setup virtual environment
setup_venv() {
    if [ ! -d "venv" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    
    # Upgrade pip
    pip install --quiet --upgrade pip
    
    # Install requirements
    log_info "Installing dependencies..."
    pip install --quiet -r requirements.txt
}

# Run health check
health_check() {
    local url="http://localhost:${PORT:-8011}/api/v1/health"
    local max_attempts=30
    local attempt=1
    
    log_info "Waiting for server to start..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            log_info "✓ Server is healthy"
            return 0
        fi
        
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done
    
    log_error "Server failed to start within $max_attempts seconds"
    return 1
}

# Start the server
start_server() {
    log_info "Starting $APP_NAME in $ENVIRONMENT mode..."
    
    export MERID_ENV="$ENVIRONMENT"
    
    if [ "$ENVIRONMENT" = "production" ]; then
        # Production: Use gunicorn with uvicorn workers
        export MERID_PROFILE="kalshi-only"
        export MERID_LOG_LEVEL="INFO"
        export RELOAD="false"
        
        exec gunicorn web.main:app \
            --bind "${HOST:-0.0.0.0}:${PORT:-8011}" \
            --workers 4 \
            --worker-class uvicorn.workers.UvicornWorker \
            --timeout 60 \
            --keepalive 5 \
            --max-requests 1000 \
            --max-requests-jitter 50 \
            --access-logfile - \
            --error-logfile - \
            --capture-output \
            --enable-stdio-inheritance
    else
        # Development: Use uvicorn directly with auto-reload
        export MERID_PROFILE="full"
        export MERID_LOG_LEVEL="DEBUG"
        export RELOAD="true"
        
        exec python -m uvicorn web.main:app \
            --host "${HOST:-127.0.0.1}" \
            --port "${PORT:-8011}" \
            --reload \
            --log-level debug
    fi
}

# Stop the server
stop_server() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        log_info "Stopping server (PID: $pid)..."
        kill -TERM "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
        log_info "Server stopped"
    else
        log_warn "No PID file found, server may not be running"
    fi
}

# Show help
show_help() {
    cat << EOF
MERID Trading System - Startup Script

Usage: ./start.sh [command] [environment]

Commands:
    start [env]     Start the server (default)
    stop            Stop the server
    restart [env]   Restart the server
    status          Check server status
    health          Run health check only

Environments:
    development     Development mode with hot reload (default)
    production      Production mode with gunicorn
    test            Testing mode

Examples:
    ./start.sh                      # Start in development mode
    ./start.sh production           # Start in production mode
    ./start.sh restart production   # Restart in production mode
    ./start.sh stop                 # Stop the server
    ./start.sh health               # Check health endpoint

EOF
}

# Main execution
main() {
    local command="${1:-start}"
    local env="${2:-development}"
    
    case "$command" in
        start)
            check_python
            check_env
            setup_venv
            start_server
            ;;
        stop)
            stop_server
            ;;
        restart)
            stop_server
            sleep 2
            check_python
            check_env
            setup_venv
            start_server
            ;;
        status)
            if [ -f "$PID_FILE" ]; then
                local pid=$(cat "$PID_FILE")
                if kill -0 "$pid" 2>/dev/null; then
                    log_info "Server is running (PID: $pid)"
                else
                    log_warn "Server is not running (stale PID file)"
                fi
            else
                log_warn "Server is not running"
            fi
            ;;
        health)
            health_check
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
