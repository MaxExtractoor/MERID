#!/bin/bash
# Telegram alert helper for live monitoring
# Usage: telegram_alert.sh <severity> <message>

SEVERITY="${1:-INFO}"
MESSAGE="${2:-}"

# Source environment for Telegram credentials
if [[ -f "/opt/merid/.env" ]]; then
    source /opt/merid/.env
elif [[ -f "$(dirname $0)/../../.env" ]]; then
    source "$(dirname $0)/../../.env"
fi

TELEGRAM_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT="${TELEGRAM_CHAT_ID:-}"

if [[ -z "$TELEGRAM_TOKEN" || -z "$TELEGRAM_CHAT" ]]; then
    echo "Telegram not configured - alert dropped: $MESSAGE" >&2
    exit 0
fi

# Format message with severity prefix
case "$SEVERITY" in
    CRITICAL)
        PREFIX="🔴 CRITICAL"
        ;;
    HIGH)
        PREFIX="🟠 HIGH"
        ;;
    WARNING)
        PREFIX="🟡 WARN"
        ;;
    INFO)
        PREFIX="🟢 INFO"
        ;;
    *)
        PREFIX="⚪ $SEVERITY"
        ;;
esac

FULL_MESSAGE="$PREFIX: $MESSAGE"

# Send via curl
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    -d "text=${FULL_MESSAGE}" \
    -d "parse_mode=HTML" \
    --max-time 10 \
    2>/dev/null || echo "Telegram send failed" >&2
