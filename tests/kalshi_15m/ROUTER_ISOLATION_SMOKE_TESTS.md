# Router Isolation Smoke Tests

This document provides curl commands to verify router isolation for the kalshi_crypto_15m_v2 profile.

## Prerequisites

- Set environment variable: `export MERID_PROFILE=kalshi_crypto_15m_v2`
- Start the MERID API server: `python -m uvicorn web.main:app --host 0.0.0.0 --port 8000`

## Allowed Routers (kalshi_crypto_15m_v2)

These routers should be accessible:

```bash
# Core routers
curl -s http://localhost:8000/ | head -20
curl -s http://localhost:8000/api/v1/health
curl -s http://localhost:8000/api/v1/system/status

# Kalshi venue routers
curl -s http://localhost:8000/api/v1/kalshi/markets
curl -s http://localhost:8000/api/v1/kalshi-grid/agents
curl -s http://localhost:8000/api/v1/kalshi-grid/agents/BTC_15M
curl -s http://localhost:8000/api/v1/kalshi-metrics/brier-scores

# Portfolio/Risk routers
curl -s http://localhost:8000/api/v1/portfolio/positions
curl -s http://localhost:8000/api/v1/risk/exposure

# Health/Ops routers
curl -s http://localhost:8000/api/v1/health
curl -s http://localhost:8000/api/v1/operator/status
curl -s http://localhost:8000/api/v1/metrics
curl -s http://localhost:8000/api/v1/dashboard/data

# Trading/Agents routers
curl -s http://localhost:8000/api/v1/trading-mode
curl -s http://localhost:8000/api/v1/agents/health
curl -s http://localhost:8000/api/v1/crypto-lanes/status

# Prediction routers
curl -s http://localhost:8000/api/v1/prediction/signals
curl -s http://localhost:8000/api/v1/prediction/markets
curl -s http://localhost:8000/api/v1/prediction/consensus
```

## Forbidden Routers (kalshi_crypto_15m_v2)

These routers should return 404 Not Found:

```bash
# Swarm routers
curl -s http://localhost:8000/api/v1/swarm/status
curl -s http://localhost:8000/api/v1/swarm/agents

# Sentiment routers
curl -s http://localhost:8000/api/v1/sentiment/status
curl -s http://localhost:8000/api/v1/sentiment/volatility

# Debate routers
curl -s http://localhost:8000/api/v1/debate/data
curl -s http://localhost:8000/api/v1/debate/health

# Governance routers
curl -s http://localhost:8000/api/v1/governance/votes
curl -s http://localhost:8000/api/v1/governance/proposals

# Trading routers (general)
curl -s http://localhost:8000/api/v1/trading/orders
curl -s http://localhost:8000/api/v1/trading/positions

# Betting routers
curl -s http://localhost:8000/api/v1/betting/events
curl -s http://localhost:8000/api/v1/betting/orders

# Wallet routers
curl -s http://localhost:8000/api/v1/wallet/balance
curl -s http://localhost:8000/api/v1/wallet/transactions

# Treasury routers
curl -s http://localhost:8000/api/v1/treasury/balance
curl -s http://localhost:8000/api/v1/treasury/allocations

# Recovery routers
curl -s http://localhost:8000/api/v1/recovery/status
curl -s http://localhost:8000/api/v1/recovery/backup

# Sniping routers
curl -s http://localhost:8000/api/v1/sniping/opportunities
curl -s http://localhost:8000/api/v1/sniping/orders

# Cost models routers
curl -s http://localhost:8000/api/v1/cost-models/fees
curl -s http://localhost:8000/api/v1/cost-models/gas

# Time exploit routers
curl -s http://localhost:8000/api/v1/time-exploit/opportunities

# Institutional routers
curl -s http://localhost:8000/api/v1/institutional/orders
curl -s http://localhost:8000/api/v1/institutional/positions

# Quadratic funding routers
curl -s http://localhost:8000/api/v1/quadratic-funding/projects
curl -s http://localhost:8000/api/v1/quadratic-funding/donations

# Plugins routers
curl -s http://localhost:8000/api/v1/plugins/list
curl -s http://localhost:8000/api/v1/plugins/enable

# Backup routers
curl -s http://localhost:8000/api/v1/backup/create
curl -s http://localhost:8000/api/v1/backup/restore

# Archive routers
curl -s http://localhost:8000/api/v1/archive/markets
curl -s http://localhost:8000/api/v1/archive/trades

# Paper trading routers
curl -s http://localhost:8000/api/v1/paper-trading/positions
curl -s http://localhost:8000/api/v1/paper-trading/orders

# Trading suite routers
curl -s http://localhost:8000/api/v1/trading-suite/strategies
curl -s http://localhost:8000/api/v1/trading-suite/backtest

# Arbitrage routers
curl -s http://localhost:8000/api/v1/arbitrage/opportunities
curl -s http://localhost:8000/api/v1/arbitrage/orders

# Referrals routers
curl -s http://localhost:8000/api/v1/referrals/code
curl -s http://localhost:8000/api/v1/referrals/stats

# Mining routers
curl -s http://localhost:8000/api/v1/mining/status
curl -s http://localhost:8000/api/v1/mining/rewards

# Offline routers
curl -s http://localhost:8000/api/v1/offline/data
curl -s http://localhost:8000/api/v1/offline/sync

# Notifications routers
curl -s http://localhost:8000/api/v1/notifications/list
curl -s http://localhost:8000/api/v1/notifications/send

# Schemas routers
curl -s http://localhost:8000/api/v1/schemas/agent
curl -s http://localhost:8000/api/v1/schemas/market
```

## Verification Script

Run this script to verify router isolation:

```bash
#!/bin/bash
# router_isolation_check.sh

FORBIDDEN_COUNT=0
ALLOWED_COUNT=0

echo "Checking forbidden routers (should return 404)..."
for endpoint in \
    "/api/v1/swarm/status" \
    "/api/v1/sentiment/status" \
    "/api/v1/debate/data" \
    "/api/v1/governance/votes" \
    "/api/v1/trading/orders" \
    "/api/v1/betting/events" \
    "/api/v1/wallet/balance" \
    "/api/v1/treasury/balance" \
    "/api/v1/recovery/status" \
    "/api/v1/sniping/opportunities" \
    "/api/v1/cost-models/fees" \
    "/api/v1/time-exploit/opportunities" \
    "/api/v1/institutional/orders" \
    "/api/v1/quadratic-funding/projects" \
    "/api/v1/plugins/list" \
    "/api/v1/backup/create" \
    "/api/v1/archive/markets" \
    "/api/v1/paper-trading/positions" \
    "/api/v1/trading-suite/strategies" \
    "/api/v1/arbitrage/opportunities" \
    "/api/v1/referrals/code" \
    "/api/v1/mining/status" \
    "/api/v1/offline/data" \
    "/api/v1/notifications/list" \
    "/api/v1/schemas/agent"
do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000$endpoint)
    if [ "$STATUS" = "404" ]; then
        echo "✓ $endpoint - 404 (correct)"
        ((FORBIDDEN_COUNT++))
    else
        echo "✗ $endpoint - $STATUS (should be 404)"
    fi
done

echo ""
echo "Checking allowed routers (should return 200)..."
for endpoint in \
    "/api/v1/health" \
    "/api/v1/kalshi/markets" \
    "/api/v1/kalshi-grid/agents" \
    "/api/v1/portfolio/positions" \
    "/api/v1/risk/exposure" \
    "/api/v1/operator/status" \
    "/api/v1/trading-mode"
do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000$endpoint)
    if [ "$STATUS" = "200" ] || [ "$STATUS" = "401" ]; then
        echo "✓ $endpoint - $STATUS (correct)"
        ((ALLOWED_COUNT++))
    else
        echo "✗ $endpoint - $STATUS (should be 200 or 401)"
    fi
done

echo ""
echo "Forbidden routers blocked: $FORBIDDEN_COUNT/26"
echo "Allowed routers accessible: $ALLOWED_COUNT/7"

if [ "$FORBIDDEN_COUNT" -eq 26 ] && [ "$ALLOWED_COUNT" -ge 5 ]; then
    echo "✅ Router isolation verified"
    exit 0
else
    echo "❌ Router isolation failed"
    exit 1
fi
```

## Expected Results

For `kalshi_crypto_15m_v2` profile:
- All 26 forbidden routers should return 404 Not Found
- At least 5-7 allowed routers should return 200 OK (or 401 if auth required)

For `full` profile:
- All routers (including forbidden ones) should be accessible
- No 404 errors for legacy routers
