#!/usr/bin/env bash

# Kalshi Positions/PnL/Stats — Operator Health Check
#
# Usage:
#   ./operator_health_check.sh [--base-url http://localhost:8000] [--verbose]
#
# Exit codes:
#   0 - All checks passed (GREEN)
#   1 - Warning issues detected (YELLOW)
#   2 - Critical issues detected (RED)

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL="${1:-http://localhost:8000}"
VERBOSE="${2:-false}"

if [[ "$1" == "--base-url" ]]; then
    BASE_URL="$2"
    shift 2
fi

if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE=true
fi

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
CHECKS_PASSED=0
CHECKS_WARNED=0
CHECKS_FAILED=0

# ── Helper Functions ──────────────────────────────────────────────────────────

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $*"
    ((CHECKS_PASSED++))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $*"
    ((CHECKS_WARNED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $*"
    ((CHECKS_FAILED++))
}

curl_api() {
    local endpoint="$1"
    local url="${BASE_URL}${endpoint}"

    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Fetching: $url"
    fi

    curl -s -f "$url" || {
        log_error "API endpoint unreachable: $endpoint"
        return 1
    }
}

check_numeric_range() {
    local value="$1"
    local min="$2"
    local max="$3"
    local name="$4"

    if (( $(echo "$value >= $min && $value <= $max" | bc -l) )); then
        return 0
    else
        log_warning "$name out of expected range: $value (expected $min-$max)"
        return 1
    fi
}

# ── Health Checks ─────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  Kalshi Position/PnL/Stats Health Check"
echo "  Base URL: $BASE_URL"
echo "  Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1: API Connectivity
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 1: API Connectivity"

if health_resp=$(curl_api "/api/v1/kalshi/health"); then
    log_success "Kalshi API is reachable"
else
    log_error "Kalshi API is unreachable"
    exit 2
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2: Reconciliation Status
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 2: Reconciliation Status"

recon_severity=$(echo "$health_resp" | jq -r '.reconciliation.severity // "UNKNOWN"')
recon_issue_count=$(echo "$health_resp" | jq -r '.reconciliation.issue_count // 0')

if [[ "$recon_severity" == "OK" ]]; then
    log_success "Reconciliation: OK (no issues)"
elif [[ "$recon_severity" == "WARNING" ]]; then
    log_warning "Reconciliation: WARNING ($recon_issue_count issues)"
    if [[ "$VERBOSE" == "true" ]]; then
        echo "$health_resp" | jq '.reconciliation.issues'
    fi
elif [[ "$recon_severity" == "CRITICAL" ]]; then
    log_error "Reconciliation: CRITICAL ($recon_issue_count issues)"
    echo "$health_resp" | jq '.reconciliation'
else
    log_warning "Reconciliation: UNKNOWN status"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3: Position Count Consistency
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 3: Position Count Consistency"

positions_resp=$(curl_api "/api/v1/kalshi/positions")
position_count=$(echo "$positions_resp" | jq '.positions | length')

recon_internal_count=$(echo "$health_resp" | jq -r '.reconciliation.internal_position_count // 0')
recon_venue_count=$(echo "$health_resp" | jq -r '.reconciliation.venue_position_count // 0')

if [[ "$position_count" == "$recon_internal_count" ]]; then
    log_success "Position count consistent: $position_count positions"
else
    log_warning "Position count mismatch: API=$position_count, Reconciler=$recon_internal_count"
fi

if [[ "$recon_internal_count" == "$recon_venue_count" ]]; then
    log_success "Reconciliation: Internal=$recon_internal_count matches Venue=$recon_venue_count"
else
    log_warning "Reconciliation: Internal=$recon_internal_count != Venue=$recon_venue_count"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4: PnL Consistency Across Endpoints
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 4: PnL Consistency Across Endpoints"

pnl_resp=$(curl_api "/api/v1/kalshi/pnl")
risk_resp=$(curl_api "/api/v1/kalshi/risk")

pnl_daily=$(echo "$pnl_resp" | jq -r '.daily_pnl_usd // 0')
risk_daily=$(echo "$risk_resp" | jq -r '.daily_pnl_usd // 0')

pnl_diff=$(echo "$pnl_daily - $risk_daily" | bc | awk '{print ($1 < 0) ? -$1 : $1}')

if (( $(echo "$pnl_diff < 0.01" | bc -l) )); then
    log_success "Daily PnL consistent across endpoints: \$${pnl_daily}"
else
    log_warning "Daily PnL mismatch: /pnl=\$${pnl_daily}, /risk=\$${risk_daily} (diff=\$${pnl_diff})"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 5: Win Rate Sanity
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 5: Win Rate Sanity"

win_rate=$(echo "$risk_resp" | jq -r '.win_rate_pct // 0')
daily_trades=$(echo "$risk_resp" | jq -r '.daily_trades // 0')

if [[ "$daily_trades" -eq 0 ]]; then
    log_info "No trades today (win rate not applicable)"
elif check_numeric_range "$win_rate" 30 70 "Win rate"; then
    log_success "Win rate is reasonable: ${win_rate}% (${daily_trades} trades)"
else
    if (( $(echo "$win_rate < 30" | bc -l) )); then
        log_warning "Win rate suspiciously low: ${win_rate}% — investigate strategy"
    else
        log_warning "Win rate suspiciously high: ${win_rate}% — check for edge leak"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 6: Daily PnL vs Win Rate Consistency
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 6: Daily PnL vs Win Rate Consistency"

# If win rate > 50% but daily PnL negative → likely fee issue
if (( $(echo "$win_rate > 50 && $pnl_daily < 0 && $daily_trades > 5" | bc -l) )); then
    log_warning "High win rate (${win_rate}%) but negative PnL (\$${pnl_daily}) → check fees"
elif (( $(echo "$win_rate < 50 && $pnl_daily > 10 && $daily_trades > 5" | bc -l) )); then
    log_warning "Low win rate (${win_rate}%) but positive PnL (\$${pnl_daily}) → check edge sizing"
else
    log_success "Win rate (${win_rate}%) and PnL (\$${pnl_daily}) are consistent"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 7: Kill Switch Status
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 7: Kill Switch Status"

kill_switch=$(echo "$risk_resp" | jq -r '.kill_switch_active // false')
kill_reason=$(echo "$risk_resp" | jq -r '.kill_switch_reason // "N/A"')

if [[ "$kill_switch" == "false" ]]; then
    log_success "Kill switch: INACTIVE (trading enabled)"
else
    log_error "Kill switch: ACTIVE — Reason: $kill_reason"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 8: Drawdown Level
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 8: Drawdown Level"

drawdown_pct=$(echo "$pnl_resp" | jq -r '.drawdown_pct // 0')

if (( $(echo "$drawdown_pct < 5" | bc -l) )); then
    log_success "Drawdown: ${drawdown_pct}% (healthy)"
elif (( $(echo "$drawdown_pct < 10" | bc -l) )); then
    log_warning "Drawdown: ${drawdown_pct}% (moderate)"
else
    log_error "Drawdown: ${drawdown_pct}% (excessive — review risk limits)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 9: Open Position Count vs Limit
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 9: Open Position Count vs Limit"

open_markets=$(echo "$risk_resp" | jq -r '.open_market_count // 0')
max_markets=$(echo "$risk_resp" | jq -r '.limits.max_open_markets // 20')

utilization=$(echo "scale=1; $open_markets * 100 / $max_markets" | bc)

if (( $(echo "$utilization < 80" | bc -l) )); then
    log_success "Position count: $open_markets / $max_markets (${utilization}% utilization)"
elif (( $(echo "$utilization < 95" | bc -l) )); then
    log_warning "Position count: $open_markets / $max_markets (${utilization}% — near limit)"
else
    log_error "Position count: $open_markets / $max_markets (${utilization}% — at limit!)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 10: Stale Orders Detection
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 10: Stale Orders Detection (>5 min pending)"

orders_resp=$(curl_api "/api/v1/kalshi/orders")
current_ts=$(date +%s)

stale_orders=$(echo "$orders_resp" | jq -r --arg current_ts "$current_ts" '
    .orders[]
    | select(.status == "pending")
    | select((($current_ts | tonumber) - (.created_at | fromdateiso8601)) > 300)
    | .order_id
' | wc -l)

if [[ "$stale_orders" -eq 0 ]]; then
    log_success "No stale orders detected"
else
    log_warning "Found $stale_orders stale order(s) (pending > 5 minutes)"
    if [[ "$VERBOSE" == "true" ]]; then
        echo "$orders_resp" | jq -r --arg current_ts "$current_ts" '
            .orders[]
            | select(.status == "pending")
            | select((($current_ts | tonumber) - (.created_at | fromdateiso8601)) > 300)
        '
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 11: WebSocket Bridge Health
# ─────────────────────────────────────────────────────────────────────────────

log_info "CHECK 11: WebSocket Bridge Health"

ws_resp=$(curl_api "/api/v1/kalshi/ws" || echo '{"running": false}')
ws_running=$(echo "$ws_resp" | jq -r '.running // false')
ws_subscribed=$(echo "$ws_resp" | jq -r '.subscribed_tickers // 0')

if [[ "$ws_running" == "true" ]]; then
    log_success "WebSocket bridge: RUNNING (subscribed to $ws_subscribed tickers)"
else
    log_warning "WebSocket bridge: NOT RUNNING (using REST polling fallback)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary Report
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  Health Check Summary"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

echo -e "${GREEN}Passed:${NC}  $CHECKS_PASSED"
echo -e "${YELLOW}Warnings:${NC} $CHECKS_WARNED"
echo -e "${RED}Failed:${NC}   $CHECKS_FAILED"
echo ""

if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    echo -e "${RED}Result: CRITICAL — Address failed checks immediately${NC}"
    exit 2
elif [[ "$CHECKS_WARNED" -gt 0 ]]; then
    echo -e "${YELLOW}Result: WARNING — Review warnings and monitor${NC}"
    exit 1
else
    echo -e "${GREEN}Result: HEALTHY — All checks passed${NC}"
    exit 0
fi
