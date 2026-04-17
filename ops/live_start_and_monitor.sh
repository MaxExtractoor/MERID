#!/bin/bash
# MERID Live Mode Startup + Real-Time Monitor
# Usage: ./ops/live_start_and_monitor.sh [--live] [--confirm LIVE]
#
# This script follows the operator runbook for live trading:
#   1. Pre-flight safety checks
#   2. Live mode confirmation (explicit --confirm LIVE required)
#   3. Backend startup with monitoring
#   4. 30-minute clean-run gate validation
#   5. Continuous anomaly monitoring
#   6. Emergency abort capability

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERID_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/merid"
MONITOR_LOG="$LOG_DIR/monitor.log"
PID_FILE="/tmp/merid-live.pid"
GATE_START_FILE="/tmp/merid-gate-start"
TELEGRAM_ALERT_SCRIPT="$SCRIPT_DIR/telegram_alert.sh"

# Runtime flags
LIVE_MODE=false
CONFIRMED=false
ABORT=false
GATE_MINUTES=30

# Anomaly tracking
ANOMALY_COUNT=0
CRITICAL_ANOMALIES=0
SEQUENCE_GAPS=0
TRADE_PROPOSALS=0
TRADE_EXECUTED=0

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MONITOR_LOG"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MONITOR_LOG"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MONITOR_LOG"
}

log_anomaly() {
    echo -e "${CYAN}[ANOMALY]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MONITOR_LOG"
    ((ANOMALY_COUNT++)) || true
}

log_critical() {
    echo -e "${RED}[CRITICAL]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MONITOR_LOG"
    ((CRITICAL_ANOMALIES++)) || true
}

# Telegram alert function
send_telegram() {
    local severity="$1"
    local message="$2"
    
    if [[ -f "$TELEGRAM_ALERT_SCRIPT" ]]; then
        "$TELEGRAM_ALERT_SCRIPT" "$severity" "MERID Live: $message" || true
    fi
    
    # Also try webhook_client if available
    cd "$MERID_ROOT" && python3 -c "
import sys
try:
    from merid.alerts.webhook_client import tg_send
    tg_send('$severity', 'MERID Live: $message')
except Exception as e:
    print(f'TG fallback failed: {e}', file=sys.stderr)
" 2>/dev/null || true
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --live)
                LIVE_MODE=true
                shift
                ;;
            --confirm)
                if [[ "$2" == "LIVE" ]]; then
                    CONFIRMED=true
                fi
                shift 2
                ;;
            --abort)
                ABORT=true
                shift
                ;;
            --gate-minutes)
                GATE_MINUTES="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

show_help() {
    cat << EOF
MERID Live Mode Startup + Monitor

Usage: ./ops/live_start_and_monitor.sh [OPTIONS]

OPTIONS:
    --live              Enable live trading mode
    --confirm LIVE      Explicitly confirm live mode (REQUIRED for live)
    --abort             Emergency abort - halt all trading and flip to paper
    --gate-minutes N    Set clean-run gate duration (default: 30)
    --help              Show this help

EXAMPLES:
    # Start in paper mode with monitoring
    ./ops/live_start_and_monitor.sh

    # Start in live mode (requires explicit confirmation)
    ./ops/live_start_and_monitor.sh --live --confirm LIVE

    # Emergency abort
    ./ops/live_start_and_monitor.sh --abort

EOF
}

check_live_safety() {
    if [[ "$LIVE_MODE" == true ]]; then
        if [[ "$CONFIRMED" == false ]]; then
            log_error "Live mode requested but not confirmed!"
            log_error "Usage: --live --confirm LIVE"
            send_telegram "CRITICAL" "Live mode startup BLOCKED - confirmation missing"
            exit 1
        fi
        
        # Verify environment
        if [[ "${MERID_ALLOW_LIVE_TRADES:-}" != "true" ]]; then
            log_error "MERID_ALLOW_LIVE_TRADES must be 'true' for live mode"
            exit 1
        fi
        
        if [[ "${MERID_TRADE_MODE:-}" != "live" ]]; then
            log_error "MERID_TRADE_MODE must be 'live' for live mode"
            exit 1
        fi
        
        log_warn "╔════════════════════════════════════════════════════════╗"
        log_warn "║  LIVE MODE CONFIRMED - REAL TRADES WILL BE EXECUTED    ║"
        log_warn "║  This is NOT a drill. Real money is at risk.           ║"
        log_warn "╚════════════════════════════════════════════════════════╝"
        
        send_telegram "CRITICAL" "LIVE MODE STARTING - Real trades will execute"
        sleep 5
    else
        log_info "Paper mode - no real trades will be executed"
        export MERID_TRADE_MODE="paper"
        export MERID_PM_TRADING_MODE="paper"
    fi
}

setup_logging() {
    mkdir -p "$LOG_DIR"
    
    # Rotate old logs
    if [[ -f "$MONITOR_LOG" ]]; then
        mv "$MONITOR_LOG" "$MONITOR_LOG.$(date +%Y%m%d_%H%M%S)"
    fi
    
    # Initialize fix_history.md if not exists
    local fix_history="$MERID_ROOT/fix_history.md"
    if [[ ! -f "$fix_history" ]]; then
        cat > "$fix_history" << 'EOF'
# MERID Fix History
# Document all anomalies, investigations, and fixes here.

## Template
- **Issue**: [Description]
- **Timestamp**: [YYYY-MM-DD HH:MM:SS]
- **Root Cause**: [Investigation findings]
- **Fix**: [What was changed]
- **Validation**: [How verified]
- **Scope**: [Files/components affected]

---

## Session: $(date '+%Y-%m-%d')

EOF
    fi
    
    log_info "Logging initialized: $MONITOR_LOG"
    log_info "Fix history: $fix_history"
}

run_preflight_checks() {
    log_info "Running pre-flight checks..."
    
    cd "$MERID_ROOT"
    
    # Check Python
    if ! python3 --version > /dev/null 2>&1; then
        log_error "Python 3 not available"
        exit 1
    fi
    
    # Run structural tests
    log_info "Running structural test suite..."
    if ! python3 -m pytest tests/test_kalshi_only_profile.py tests/test_ui_backend_contract.py tests/test_sse_smoke.py -q --timeout=60 2>&1 | tee -a "$MONITOR_LOG"; then
        log_error "Structural tests FAILED - aborting startup"
        send_telegram "CRITICAL" "Pre-flight structural tests FAILED"
        exit 1
    fi
    
    log_info "Pre-flight checks PASSED"
}

start_backend() {
    log_info "Starting MERID backend..."
    
    cd "$MERID_ROOT"
    
    # Set critical environment variables
    export MERID_PROFILE="kalshi-only"
    export MERID_ENV="production"
    export MERID_LOG_LEVEL="INFO"
    
    # Ensure kalshi-only profile
    if [[ "$LIVE_MODE" == true ]]; then
        export KALSHI_API_KEY_ID="${KALSHI_API_KEY_ID:-}"
        export KALSHI_PRIVATE_KEY_PATH="${KALSHI_PRIVATE_KEY_PATH:-}"
    fi
    
    # Start the server in background
    nohup python3 -m uvicorn web.main:app \
        --host "${HOST:-0.0.0.0}" \
        --port "${PORT:-8011}" \
        --workers 4 \
        --log-level info \
        --access-log \
        2>&1 | tee -a "$LOG_DIR/server.log" &
    
    local server_pid=$!
    echo $server_pid > "$PID_FILE"
    
    log_info "Server started (PID: $server_pid)"
    
    # Wait for health check
    local max_attempts=60
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -s "http://localhost:${PORT:-8011}/api/v1/health" > /dev/null 2>&1; then
            log_info "✓ Server health check passed"
            send_telegram "INFO" "Backend started successfully (PID: $server_pid)"
            return 0
        fi
        
        if ! kill -0 $server_pid 2>/dev/null; then
            log_error "Server process died during startup"
            exit 1
        fi
        
        sleep 1
        ((attempt++)) || true
    done
    
    log_error "Server failed health check within $max_attempts seconds"
    exit 1
}

# Anomaly detection functions
scan_for_anomalies() {
    local line="$1"
    local source="$2"
    
    # Data ingestion issues
    if [[ "$line" =~ (ingest failed|dropped event|missing ticker|missing symbol|sequence mismatch|gap detected|websocket disconnect|reconnect) ]]; then
        log_anomaly "INGEST: $line"
        ((SEQUENCE_GAPS++)) || true
    fi
    
    # Trade drops
    if [[ "$line" =~ trade_proposal ]]; then
        ((TRADE_PROPOSALS++)) || true
    fi
    if [[ "$line" =~ trade_executed|fill ]]; then
        ((TRADE_EXECUTED++)) || true
    fi
    if [[ "$line" =~ (order rejected|risk check failed|position limit hit|queue overflow) ]]; then
        log_anomaly "TRADE_DROP: $line"
    fi
    
    # Math pathologies
    if [[ "$line" =~ (NaN|inf|Infinity|null pointer|division by zero) ]]; then
        log_critical "MATH: $line"
    fi
    
    # Latency spikes
    if [[ "$line" =~ latency_ms ]]; then
        local latency=$(echo "$line" | grep -oP 'latency_ms[=:]\K[0-9]+' || echo "0")
        if [[ "$latency" -gt 5000 ]]; then
            log_anomaly "LATENCY: ${latency}ms spike detected"
        fi
    fi
    
    # Critical errors
    if [[ "$line" =~ (CRITICAL|FATAL|Exception|Traceback|Error:.*kill switch|Error:.*halt) ]]; then
        log_critical "SYSTEM: $line"
    fi
    
    # Silent agent detection
    if [[ "$line" =~ (agent silent|no heartbeat|stale|timeout) ]]; then
        log_anomaly "AGENT: $line"
    fi
}

monitor_logs() {
    log_info "Starting real-time log monitor..."
    
    # Tail all relevant log sources
    tail -F "$LOG_DIR/server.log" "$MERID_ROOT/logs/kalshi-ingestion.log" 2>/dev/null | while IFS= read -r line; do
        scan_for_anomalies "$line" "server"
    done &
    
    local tail_pid=$!
    echo $tail_pid >> "$PID_FILE"
    
    log_info "Log monitor attached (tail PID: $tail_pid)"
}

calculate_trade_ratio() {
    if [[ $TRADE_PROPOSALS -gt 0 ]]; then
        local ratio=$(echo "scale=3; $TRADE_EXECUTED / $TRADE_PROPOSALS" | bc 2>/dev/null || echo "0")
        echo "$ratio"
    else
        echo "N/A"
    fi
}

run_gate_validation() {
    log_info "╔════════════════════════════════════════════════════════╗"
    log_info "║  30-MINUTE CLEAN-RUN GATE VALIDATION                   ║"
    log_info "║  Started: $(date)                                      ║"
    log_info "╚════════════════════════════════════════════════════════╝"
    
    date +%s > "$GATE_START_FILE"
    send_telegram "INFO" "30-minute clean-run gate started"
    
    local gate_seconds=$((GATE_MINUTES * 60))
    local elapsed=0
    local last_status=0
    
    while [[ $elapsed -lt $gate_seconds ]]; do
        sleep 10
        elapsed=$((elapsed + 10))
        
        # Check for critical anomalies
        if [[ $CRITICAL_ANOMALIES -gt 0 ]]; then
            log_error "╔════════════════════════════════════════════════════════╗"
            log_error "║  GATE FAILED - Critical anomalies detected             ║"
            log_error "║  Critical count: $CRITICAL_ANOMALIES                                ║"
            log_error "╚════════════════════════════════════════════════════════╝"
            
            send_telegram "CRITICAL" "GATE FAILED - $CRITICAL_ANOMALIES critical anomalies"
            
            if [[ "$LIVE_MODE" == true ]]; then
                log_error "HALTING LIVE TRADING - Switching to paper mode"
                emergency_halt
            fi
            
            return 1
        fi
        
        # Check sequence gaps
        if [[ $SEQUENCE_GAPS -gt 10 ]]; then
            log_warn "Sequence gaps detected: $SEQUENCE_GAPS"
        fi
        
        # Periodic status (every 60 seconds)
        if [[ $((elapsed % 60)) -eq 0 ]]; then
            local remaining=$((gate_seconds - elapsed))
            local minutes=$((remaining / 60))
            local trade_ratio=$(calculate_trade_ratio)
            
            log_info "Gate progress: ${minutes}m remaining | Anomalies: $ANOMALY_COUNT | Trade ratio: $trade_ratio"
            
            # Check health endpoint
            if ! curl -s "http://localhost:${PORT:-8011}/api/v1/health" > /dev/null 2>&1; then
                log_critical "Health check failed during gate validation"
                return 1
            fi
        fi
    done
    
    # Gate passed
    log_info "╔════════════════════════════════════════════════════════╗"
    log_info "║  ✓ CLEAN-RUN GATE PASSED                               ║"
    log_info "║  Duration: ${GATE_MINUTES} minutes                                   ║"
    log_info "║  Total anomalies: $ANOMALY_COUNT                                      ║"
    log_info "║  Trade proposal→execution ratio: $(calculate_trade_ratio)              ║"
    log_info "╚════════════════════════════════════════════════════════╝"
    
    send_telegram "INFO" "✓ 30-minute clean-run gate PASSED"
    
    return 0
}

continuous_monitor() {
    log_info "Entering continuous monitoring mode..."
    
    local heartbeat_interval=300  # 5 minutes
    local last_heartbeat=0
    
    while true; do
        sleep 5
        
        # Heartbeat
        local now=$(date +%s)
        if [[ $((now - last_heartbeat)) -ge $heartbeat_interval ]]; then
            local trade_ratio=$(calculate_trade_ratio)
            log_info "Heartbeat | Anomalies: $ANOMALY_COUNT | Trade ratio: $trade_ratio | Mode: $(get_current_mode)"
            send_telegram "INFO" "Heartbeat - Monitoring active"
            last_heartbeat=$now
        fi
        
        # Check server still running
        if [[ -f "$PID_FILE" ]]; then
            local pid=$(cat "$PID_FILE" | head -1)
            if ! kill -0 "$pid" 2>/dev/null; then
                log_critical "Server process died!"
                send_telegram "CRITICAL" "Server process died unexpectedly"
                return 1
            fi
        fi
    done
}

get_current_mode() {
    if [[ "$LIVE_MODE" == true ]]; then
        echo "LIVE"
    else
        echo "PAPER"
    fi
}

emergency_halt() {
    log_error "╔════════════════════════════════════════════════════════╗"
    log_error "║  EMERGENCY HALT TRIGGERED                              ║"
    log_error "╚════════════════════════════════════════════════════════╝"
    
    # Flip environment to safe mode
    export MERID_ALLOW_LIVE_TRADES="false"
    export MERID_TRADE_MODE="paper"
    export MERID_PM_TRADING_MODE="paper"
    
    # Call kill switch via API
    curl -s -X POST "http://localhost:${PORT:-8011}/api/v1/kalshi/kill-switch" \
        -H "Content-Type: application/json" \
        -d '{"action":"halt","reason":"emergency_halt_triggered"}' 2>/dev/null || true
    
    send_telegram "CRITICAL" "EMERGENCY HALT - All live trading stopped"
    
    log_info "Emergency halt complete. System in paper mode."
}

abort_mode() {
    log_error "╔════════════════════════════════════════════════════════╗"
    log_error "║  ABORT MODE ACTIVATED                                  ║"
    log_error "╚════════════════════════════════════════════════════════╝"
    
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" | head -1)
        log_info "Stopping server (PID: $pid)..."
        kill -TERM "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    
    # Ensure env is safe
    export MERID_ALLOW_LIVE_TRADES="false"
    export MERID_TRADE_MODE="paper"
    
    send_telegram "CRITICAL" "ABORT executed - Server stopped, all trading halted"
    
    log_info "Abort complete. Server stopped. Environment set to paper mode."
    exit 0
}

main() {
    parse_args "$@"
    
    # Handle abort first
    if [[ "$ABORT" == true ]]; then
        abort_mode
    fi
    
    setup_logging
    check_live_safety
    run_preflight_checks
    start_backend
    monitor_logs
    
    # Run gate validation
    if run_gate_validation; then
        log_info "✓ System passed clean-run gate. Entering continuous monitor..."
        continuous_monitor
    else
        log_error "✗ Gate validation failed. Entering degraded monitoring..."
        continuous_monitor  # Continue monitoring in degraded state
    fi
}

# Run main
cd "$MERID_ROOT"
main "$@"
