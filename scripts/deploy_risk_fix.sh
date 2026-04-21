#!/bin/bash
# Production Deployment Script: Risk Oversizing Fix
# =================================================
# This script ensures USE_TOPN_ALLOCATOR is properly set for live deployment.
# Run this after code deployment and before service restart.
#
# Usage:
#   ./scripts/deploy_risk_fix.sh [systemd|docker|pm2]

set -euo pipefail

ENV_TYPE="${1:-systemd}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "==============================================================="
echo "Risk Oversizing Fix - Production Deployment"
echo "==============================================================="
echo "Environment type: $ENV_TYPE"
echo ""

# Verify code changes are present
echo "[1/5] Verifying code changes..."
if grep -q "USE_TOPN_ALLOCATOR" core/settings.py; then
    echo -e "${GREEN}✓${NC} core/settings.py has USE_TOPN_ALLOCATOR"
else
    echo -e "${RED}✗${NC} core/settings.py missing USE_TOPN_ALLOCATOR!"
    exit 1
fi

if grep -q "GlobalRiskGuard" merid/trading/kalshi_continuous_trader.py; then
    echo -e "${GREEN}✓${NC} kalshi_continuous_trader.py has GlobalRiskGuard"
else
    echo -e "${RED}✗${NC} kalshi_continuous_trader.py missing GlobalRiskGuard!"
    exit 1
fi

# Check .env file
echo ""
echo "[2/5] Checking .env configuration..."
if grep -q "^USE_TOPN_ALLOCATOR=true" .env; then
    echo -e "${GREEN}✓${NC} .env has USE_TOPN_ALLOCATOR=true"
else
    echo -e "${YELLOW}⚠${NC} .env missing USE_TOPN_ALLOCATOR=true"
    echo "    Adding to .env..."
    echo "" >> .env
    echo "# Risk Management - Top-N Allocator (CRITICAL)" >> .env
    echo "USE_TOPN_ALLOCATOR=true" >> .env
    echo "MAX_CYCLE_RISK_PCT=0.02" >> .env
    echo "MAX_TOTAL_RISK_PCT=0.02" >> .env
    echo -e "${GREEN}✓${NC} Added to .env"
fi

# Setup environment-specific config
echo ""
echo "[3/5] Configuring $ENV_TYPE environment..."

case "$ENV_TYPE" in
    systemd)
        SERVICE_FILE="/etc/systemd/system/merid-trader.service"
        if [ -f "$SERVICE_FILE" ]; then
            if grep -q "USE_TOPN_ALLOCATOR" "$SERVICE_FILE"; then
                echo -e "${GREEN}✓${NC} systemd service already has USE_TOPN_ALLOCATOR"
            else
                echo -e "${YELLOW}⚠${NC} Adding USE_TOPN_ALLOCATOR to systemd service..."
                sudo sed -i '/\[Service\]/a Environment="USE_TOPN_ALLOCATOR=true"' "$SERVICE_FILE"
                sudo systemctl daemon-reload
                echo -e "${GREEN}✓${NC} Updated systemd service"
            fi
        else
            echo -e "${YELLOW}⚠${NC} systemd service file not found at $SERVICE_FILE"
            echo "    Manual setup required - see DEPLOY_RISK_FIX.md"
        fi
        ;;
    
    docker)
        COMPOSE_FILE="docker-compose.yml"
        if [ -f "$COMPOSE_FILE" ]; then
            if grep -q "USE_TOPN_ALLOCATOR" "$COMPOSE_FILE"; then
                echo -e "${GREEN}✓${NC} docker-compose already has USE_TOPN_ALLOCATOR"
            else
                echo -e "${YELLOW}⚠${NC} Adding USE_TOPN_ALLOCATOR to docker-compose..."
                # Add to all service definitions that need it
                sed -i '/environment:/a\      - USE_TOPN_ALLOCATOR=true\n      - MAX_CYCLE_RISK_PCT=0.02\n      - MAX_TOTAL_RISK_PCT=0.02' "$COMPOSE_FILE"
                echo -e "${GREEN}✓${NC} Updated docker-compose.yml"
            fi
        else
            echo -e "${YELLOW}⚠${NC} docker-compose.yml not found"
        fi
        ;;
    
    pm2)
        ECOSYSTEM_FILE="ecosystem.config.js"
        if [ -f "$ECOSYSTEM_FILE" ]; then
            if grep -q "USE_TOPN_ALLOCATOR" "$ECOSYSTEM_FILE"; then
                echo -e "${GREEN}✓${NC} PM2 ecosystem already has USE_TOPN_ALLOCATOR"
            else
                echo -e "${YELLOW}⚠${NC} Adding USE_TOPN_ALLOCATOR to PM2 ecosystem..."
                # This is a simplified check - actual PM2 config varies
                echo "    Manual update may be required - see DEPLOY_RISK_FIX.md"
            fi
        else
            echo -e "${YELLOW}⚠${NC} ecosystem.config.js not found"
        fi
        ;;
    
    *)
        echo -e "${YELLOW}⚠${NC} Unknown environment type: $ENV_TYPE"
        echo "    Supported: systemd, docker, pm2"
        ;;
esac

# Run tests
echo ""
echo "[4/5] Running regression tests..."
export USE_TOPN_ALLOCATOR=true
if python -m pytest tests/trading/test_risk_oversizing_regression.py -v --tb=short -q; then
    echo -e "${GREEN}✓${NC} All regression tests passed"
else
    echo -e "${RED}✗${NC} Regression tests failed!"
    exit 1
fi

# Pre-flight check
echo ""
echo "[5/5] Pre-flight verification..."
python scripts/verify_risk_fix.py
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}===============================================================${NC}"
    echo -e "${GREEN}✓ DEPLOYMENT READY${NC}"
    echo -e "${GREEN}===============================================================${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review the changes above"
    echo "  2. Restart the service:"
    case "$ENV_TYPE" in
        systemd)  echo "     sudo systemctl restart merid-trader" ;;
        docker)   echo "     docker-compose up -d" ;;
        pm2)      echo "     pm2 restart merid-trader" ;;
    esac
    echo "  3. Check logs for [RISK-MODE] and [RISK-CONFIG] messages"
    echo "  4. Verify [GLOBAL-RISK-GUARD] appears in first trading cycle"
    echo ""
    echo "Rollback (if needed):"
    echo "  export USE_TOPN_ALLOCATOR=false"
    echo "  <restart service>"
    echo ""
else
    echo ""
    echo -e "${RED}===============================================================${NC}"
    echo -e "${RED}✗ PRE-FLIGHT CHECK FAILED${NC}"
    echo -e "${RED}===============================================================${NC}"
    echo ""
    echo "Do not restart until checks pass."
    exit 1
fi
