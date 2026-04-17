#!/bin/bash
# MERID 24/7 Trading System Startup Script
# Usage: ./scripts/start_merid.sh [--fresh-start]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  MERID Kalshi Trading System${NC}"
echo -e "${BLUE}  24/7 Automated Trading${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Parse arguments
FRESH_START=0
if [ "$1" = "--fresh-start" ]; then
    FRESH_START=1
    echo -e "${YELLOW}⚠️  FRESH START MODE - All state will be reset${NC}"
    echo ""
fi

# 1. Find MERID directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MERID_DIR="$(dirname "$SCRIPT_DIR")"
cd "$MERID_DIR"

echo "📁 Working directory: $MERID_DIR"

# 2. Load environment
if [ -f "$HOME/.merid_env" ]; then
    echo "📝 Loading environment from ~/.merid_env"
    source "$HOME/.merid_env"
elif [ -f ".env" ]; then
    echo "📝 Loading environment from .env"
    set -a
    source ".env"
    set +a
else
    echo -e "${YELLOW}⚠️  No environment file found. Using defaults.${NC}"
fi

# 3. Check Python environment
if [ -d ".venv" ]; then
    echo "🐍 Activating virtual environment"
    source .venv/bin/activate
elif [ -d "venv" ]; then
    echo "🐍 Activating virtual environment"
    source venv/bin/activate
else
    echo -e "${RED}❌ No virtual environment found${NC}"
    echo "Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 4. Pre-flight checks
echo ""
echo -e "${BLUE}🔍 Pre-flight Checks${NC}"
echo "------------------------"

# Check Python
echo -n "✓ Python: "
python --version

# Check disk space
echo -n "✓ Disk space: "
DISK_USAGE=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
echo "${DISK_USAGE}% used"
if [ "$DISK_USAGE" -gt 90 ]; then
    echo -e "${RED}❌ Disk space critical!${NC}"
    exit 1
elif [ "$DISK_USAGE" -gt 80 ]; then
    echo -e "${YELLOW}⚠️  Disk space warning${NC}"
fi

# Check Kalshi API
echo -n "✓ Kalshi API: "
if curl -s --max-time 10 "https://api.elections.kalshi.com/trade-api/v2/markets" > /dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}UNREACHABLE${NC}"
    echo "Check internet connection and Kalshi status"
    exit 1
fi

# Check data directories
echo -n "✓ Data directory: "
if [ -d "data" ]; then
    echo -e "${GREEN}OK${NC}"
else
    mkdir -p data
    echo -e "${YELLOW}Created${NC}"
fi

echo -n "✓ Logs directory: "
if [ -d "logs" ]; then
    echo -e "${GREEN}OK${NC}"
else
    mkdir -p logs
    echo -e "${YELLOW}Created${NC}"
fi

# 5. Check for stale locks
echo ""
echo -n "🔒 Checking for stale process locks... "
PID_FILE="logs/merid.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}Running (PID: $OLD_PID)${NC}"
        echo "Use: kill $OLD_PID && sleep 5 && ./scripts/start_merid.sh"
        exit 1
    else
        echo -e "${YELLOW}Stale lock removed${NC}"
        rm "$PID_FILE"
    fi
else
    echo -e "${GREEN}None${NC}"
fi

# 6. Set environment for fresh start if requested
if [ "$FRESH_START" = "1" ]; then
    echo ""
    echo -e "${YELLOW}🔄 Resetting all state...${NC}"
    export MERID_FRESH_START=1
    
    # Backup old data
    BACKUP_DIR="data/backup/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    for file in data/*.json data/*.db; do
        if [ -f "$file" ]; then
            cp "$file" "$BACKUP_DIR/" 2>/dev/null || true
        fi
    done
    echo "📦 Backed up old state to $BACKUP_DIR"
else
    export MERID_FRESH_START=0
fi

# 7. Start the system
echo ""
echo -e "${GREEN}🚀 Starting MERID Trading System...${NC}"
echo "========================================"
echo ""
echo "Environment settings:"
echo "  KALSHI_CT_PROFILE: ${KALSHI_CT_PROFILE:-initial_live}"
echo "  MERID_PM_TRADING_MODE: ${MERID_PM_TRADING_MODE:-paper}"
echo "  KELLY_FRACTION: ${MERID_KELLY_MAX_FRACTION:-0.20}"
echo "  FRESH_START: ${MERID_FRESH_START}"
echo ""
echo "Press Ctrl+C to stop gracefully"
echo ""

# Write PID file
echo $$ > "$PID_FILE"

# Start with auto-restart on failure
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting server..."
    
    # Run the server
    if python -m web.main 2>&1 | tee -a "logs/server_$(date +%Y%m%d).log"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server exited cleanly"
        break
    else
        EXIT_CODE=${PIPESTATUS[0]}
        echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] Server crashed (exit code: $EXIT_CODE)${NC}"
        echo "Restarting in 60 seconds..."
        sleep 60
    fi
done

# Cleanup
rm -f "$PID_FILE"
echo "👋 MERID stopped"
