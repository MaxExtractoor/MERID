#!/bin/bash
# MERID Daily Health Check Script
# Run via cron: 0 */4 * * * /path/to/merid/scripts/daily_health_check.sh
# Or Windows Task Scheduler every 4 hours

set -e

# Configuration
LOG_DIR="${MERID_LOG_DIR:-logs}"
DATA_DIR="${MERID_DATA_DIR:-data}"
API="${MERID_API_URL:-http://localhost:8011}/api/v1"
TELEGRAM_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT="${TELEGRAM_CHAT_ID:-}"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_health_$(date +%Y%m%d).log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== $TIMESTAMP Daily Health Check ===" >> "$LOG_FILE"

# Colors for terminal output (disabled in log)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ALERTS=""

# Function to send Telegram alert
send_alert() {
    local message="$1"
    if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_CHAT" \
            -d "text=$message" \
            -d "parse_mode=Markdown" > /dev/null 2>&1 || true
    fi
    echo "$message" >> "$LOG_FILE"
}

# 1. Check if server is running
echo "[1/6] Checking server status..." >> "$LOG_FILE"
if curl -s "$API/system/ping" > /dev/null 2>&1; then
    echo "✅ Server running" >> "$LOG_FILE"
else
    echo "❌ Server NOT RESPONDING" >> "$LOG_FILE"
    send_alert "🚨 *MERID ALERT* Server not responding at $TIMESTAMP"
    exit 1
fi

# 2. Check kill switch status
echo "[2/6] Checking kill switch..." >> "$LOG_FILE"
KILL_SWITCH=$(curl -s "$API/system/kill-switch" 2>/dev/null | grep -o '"active":[^,]*' | cut -d':' -f2 || echo "unknown")
if [ "$KILL_SWITCH" = "true" ]; then
    echo "⚠️  KILL SWITCH ACTIVE" >> "$LOG_FILE"
    send_alert "⚠️ *MERID WARNING* Kill switch is ACTIVE at $TIMESTAMP"
    ALERTS="${ALERTS}KillSwitch;"
elif [ "$KILL_SWITCH" = "false" ]; then
    echo "✅ Kill switch clear" >> "$LOG_FILE"
else
    echo "⚠️  Kill switch status unknown" >> "$LOG_FILE"
fi

# 3. Check execution lag
echo "[3/6] Checking execution lag..." >> "$LOG_FILE"
LAG_MS=$(curl -s "$API/health/execution-lag" 2>/dev/null | grep -o '"lag_ms":[^,}]*' | cut -d':' -f2 | tr -d ' ' || echo "0")
if [ -n "$LAG_MS" ] && [ "$LAG_MS" -gt 500 ] 2>/dev/null; then
    echo "⚠️  HIGH LAG: ${LAG_MS}ms (threshold: 500ms)" >> "$LOG_FILE"
    send_alert "⚠️ *MERID WARNING* Execution lag: ${LAG_MS}ms at $TIMESTAMP"
    ALERTS="${ALERTS}HighLag;"
elif [ -n "$LAG_MS" ] && [ "$LAG_MS" -gt 300 ] 2>/dev/null; then
    echo "⚠️  Elevated lag: ${LAG_MS}ms (watching)" >> "$LOG_FILE"
else
    echo "✅ Lag OK: ${LAG_MS}ms" >> "$LOG_FILE"
fi

# 4. Check bankroll status
echo "[4/6] Checking bankroll..." >> "$LOG_FILE"
CT_STATUS=$(curl -s "$API/kalshi/continuous-trader/status" 2>/dev/null)
if [ -n "$CT_STATUS" ]; then
    TOTAL_VALUE=$(echo "$CT_STATUS" | grep -o '"total_value_cents":[0-9]*' | cut -d':' -f2 || echo "0")
    DRAWDOWN=$(echo "$CT_STATUS" | grep -o '"drawdown_pct":[^,}]*' | cut -d':' -f2 | tr -d ' ' || echo "0")
    
    TOTAL_DOLLARS=$(echo "scale=2; $TOTAL_VALUE / 100" | bc 2>/dev/null || echo "0")
    echo "💰 Bankroll: \$$TOTAL_DOLLARS | Drawdown: ${DRAWDOWN}%" >> "$LOG_FILE"
    
    # Alert if drawdown > 12%
    if [ -n "$DRAWDOWN" ] && (( $(echo "$DRAWDOWN > 12" | bc -l 2>/dev/null || echo "0") )); then
        send_alert "⚠️ *MERID WARNING* Drawdown at ${DRAWDOWN}% at $TIMESTAMP"
        ALERTS="${ALERTS}HighDrawdown;"
    fi
else
    echo "⚠️  Could not fetch bankroll status" >> "$LOG_FILE"
fi

# 5. Check recent fills
echo "[5/6] Checking recent fills..." >> "$LOG_FILE"
if [ -f "$DATA_DIR/kalshi_fills.db" ]; then
    FILL_STATS=$(sqlite3 "$DATA_DIR/kalshi_fills.db" "SELECT COUNT(*), COALESCE(SUM(fee_cents), 0) FROM fills WHERE timestamp > datetime('now', '-24 hours');" 2>/dev/null || echo "0|0")
    FILL_COUNT=$(echo "$FILL_STATS" | cut -d'|' -f1)
    TOTAL_FEES=$(echo "$FILL_STATS" | cut -d'|' -f2)
    FEE_DOLLARS=$(echo "scale=2; $TOTAL_FEES / 100" | bc 2>/dev/null || echo "0")
    
    echo "📊 24h Fills: $FILL_COUNT | Fees: \$$FEE_DOLLARS" >> "$LOG_FILE"
    
    if [ "$FILL_COUNT" -eq 0 ] 2>/dev/null; then
        echo "⚠️  No fills in last 24 hours" >> "$LOG_FILE"
        ALERTS="${ALERTS}NoFills;"
    fi
else
    echo "⚠️  Fill database not found" >> "$LOG_FILE"
fi

# 6. Check error rate
echo "[6/6] Checking error rate..." >> "$LOG_FILE"
ERROR_LOG="$DATA_DIR/trade_audit.jsonl"
if [ -f "$ERROR_LOG" ]; then
    # Count errors in last hour (approximate using timestamp)
    ONE_HOUR_AGO=$(date -d '1 hour ago' +%s 2>/dev/null || echo "0")
    ERROR_COUNT=$(grep -c '"kill_reason"' "$ERROR_LOG" 2>/dev/null || echo "0")
    echo "⚠️  Total kill events in log: $ERROR_COUNT" >> "$LOG_FILE"
    
    if [ "$ERROR_COUNT" -gt 10 ] 2>/dev/null; then
        send_alert "🚨 *MERID ALERT* $ERROR_COUNT kill events detected"
        ALERTS="${ALERTS}ManyKills;"
    fi
else
    echo "ℹ️  No trade audit log found" >> "$LOG_FILE"
fi

# Summary
echo "" >> "$LOG_FILE"
echo "=== Summary at $TIMESTAMP ===" >> "$LOG_FILE"
if [ -z "$ALERTS" ]; then
    echo "✅ All systems nominal" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    exit 0
else
    echo "⚠️  Alerts: $ALERTS" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    exit 1
fi
