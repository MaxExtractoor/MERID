#!/bin/bash
##############################################################################
# MERID Kafka Connect Connector Deployment Script
#
# Deploys sink connectors for trading data analytics.
#
# Usage:
#   ./deploy-connectors.sh              # Deploy all connectors
#   ./deploy-connectors.sh pg           # Deploy PostgreSQL sinks only
#   ./deploy-connectors.sh s3           # Deploy S3 sink only
#   ./deploy-connectors.sh status       # Check connector status
#   ./deploy-connectors.sh delete NAME  # Delete a connector
##############################################################################

set -e

CONNECT_URL="${KAFKA_CONNECT_URL:-http://localhost:8084}"
CONNECTORS_DIR="${CONNECTORS_DIR:-$(dirname $0)/connectors}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for Kafka Connect to be ready
wait_for_connect() {
    log_info "Waiting for Kafka Connect to be ready..."
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "${CONNECT_URL}/connectors" > /dev/null 2>&1; then
            log_info "Kafka Connect is ready!"
            return 0
        fi
        echo -n "."
        sleep 2
        ((attempt++))
    done
    
    log_error "Kafka Connect not ready after ${max_attempts} attempts"
    exit 1
}

# Deploy a single connector
deploy_connector() {
    local config_file="$1"
    local connector_name=$(jq -r '.name' "$config_file")
    
    log_info "Deploying connector: $connector_name"
    
    # Check if connector already exists
    if curl -s "${CONNECT_URL}/connectors/${connector_name}" | jq -e '.name' > /dev/null 2>&1; then
        log_warn "Connector $connector_name already exists, updating..."
        
        # Update existing connector
        curl -s -X PUT \
            -H "Content-Type: application/json" \
            -d "$(jq '.config' "$config_file")" \
            "${CONNECT_URL}/connectors/${connector_name}/config" | jq .
    else
        # Create new connector
        curl -s -X POST \
            -H "Content-Type: application/json" \
            -d "@${config_file}" \
            "${CONNECT_URL}/connectors" | jq .
    fi
    
    log_info "Connector $connector_name deployed"
}

# Deploy PostgreSQL connectors
deploy_pg_connectors() {
    log_info "Deploying PostgreSQL sink connectors..."
    
    for config in "${CONNECTORS_DIR}"/*-pg-sink.json; do
        if [ -f "$config" ]; then
            deploy_connector "$config"
        fi
    done
}

# Deploy S3 connectors
deploy_s3_connectors() {
    log_info "Deploying S3 sink connectors..."
    
    for config in "${CONNECTORS_DIR}"/*-s3-sink.json; do
        if [ -f "$config" ]; then
            deploy_connector "$config"
        fi
    done
}

# Deploy all connectors
deploy_all() {
    log_info "Deploying all connectors..."
    
    for config in "${CONNECTORS_DIR}"/*.json; do
        if [ -f "$config" ]; then
            deploy_connector "$config"
        fi
    done
}

# Check connector status
check_status() {
    log_info "Checking connector status..."
    
    local connectors=$(curl -s "${CONNECT_URL}/connectors" | jq -r '.[]')
    
    if [ -z "$connectors" ]; then
        log_warn "No connectors deployed"
        return
    fi
    
    echo ""
    printf "%-30s %-15s %-10s %s\n" "CONNECTOR" "STATE" "TASKS" "WORKER"
    printf "%-30s %-15s %-10s %s\n" "---------" "-----" "-----" "------"
    
    for connector in $connectors; do
        local status=$(curl -s "${CONNECT_URL}/connectors/${connector}/status")
        local state=$(echo "$status" | jq -r '.connector.state')
        local worker=$(echo "$status" | jq -r '.connector.worker_id')
        local tasks=$(echo "$status" | jq -r '.tasks | length')
        
        # Color code state
        local state_color=""
        case $state in
            RUNNING) state_color="${GREEN}" ;;
            PAUSED) state_color="${YELLOW}" ;;
            FAILED) state_color="${RED}" ;;
            *) state_color="${NC}" ;;
        esac
        
        printf "%-30s ${state_color}%-15s${NC} %-10s %s\n" "$connector" "$state" "$tasks" "$worker"
        
        # Show task errors if any
        local task_errors=$(echo "$status" | jq -r '.tasks[] | select(.state == "FAILED") | .trace' 2>/dev/null)
        if [ -n "$task_errors" ] && [ "$task_errors" != "null" ]; then
            echo "  ERROR: $(echo "$task_errors" | head -1)"
        fi
    done
    echo ""
}

# Delete a connector
delete_connector() {
    local connector_name="$1"
    
    if [ -z "$connector_name" ]; then
        log_error "Connector name required"
        exit 1
    fi
    
    log_info "Deleting connector: $connector_name"
    curl -s -X DELETE "${CONNECT_URL}/connectors/${connector_name}"
    log_info "Connector $connector_name deleted"
}

# Pause a connector
pause_connector() {
    local connector_name="$1"
    
    log_info "Pausing connector: $connector_name"
    curl -s -X PUT "${CONNECT_URL}/connectors/${connector_name}/pause"
    log_info "Connector $connector_name paused"
}

# Resume a connector
resume_connector() {
    local connector_name="$1"
    
    log_info "Resuming connector: $connector_name"
    curl -s -X PUT "${CONNECT_URL}/connectors/${connector_name}/resume"
    log_info "Connector $connector_name resumed"
}

# Restart a connector
restart_connector() {
    local connector_name="$1"
    
    log_info "Restarting connector: $connector_name"
    curl -s -X POST "${CONNECT_URL}/connectors/${connector_name}/restart"
    log_info "Connector $connector_name restarted"
}

# Main
case "${1:-all}" in
    pg)
        wait_for_connect
        deploy_pg_connectors
        ;;
    s3)
        wait_for_connect
        deploy_s3_connectors
        ;;
    all)
        wait_for_connect
        deploy_all
        ;;
    status)
        check_status
        ;;
    delete)
        delete_connector "$2"
        ;;
    pause)
        pause_connector "$2"
        ;;
    resume)
        resume_connector "$2"
        ;;
    restart)
        restart_connector "$2"
        ;;
    help|--help|-h)
        echo "Usage: $0 [command] [args]"
        echo ""
        echo "Commands:"
        echo "  all         Deploy all connectors (default)"
        echo "  pg          Deploy PostgreSQL sinks only"
        echo "  s3          Deploy S3 sink only"
        echo "  status      Check connector status"
        echo "  delete NAME Delete a connector"
        echo "  pause NAME  Pause a connector"
        echo "  resume NAME Resume a connector"
        echo "  restart NAME Restart a connector"
        echo "  help        Show this help"
        ;;
    *)
        log_error "Unknown command: $1"
        echo "Use '$0 help' for usage"
        exit 1
        ;;
esac
