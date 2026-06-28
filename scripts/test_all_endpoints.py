"""Test all frontend API endpoints against running backend."""
import requests
import json
import time

BASE = "http://127.0.0.1:8011"
# CRITICAL FIX: Increased timeout for production stability
TIMEOUT = 30.0  # Increased from default timeout

endpoints = [
    # constants.ts endpoints
    "/api/v1/portfolio/summary",
    "/api/v1/positions",
    "/api/v1/positions/summary",
    "/api/v1/orders",
    "/api/v1/orders/summary",
    "/api/v1/fills",
    "/api/trading/summary",
    "/api/v1/agents",
    "/api/agents/summary",
    "/api/v1/charters",
    "/api/v1/us-compliant/prediction-markets",
    "/api/v1/prediction-markets/positions",
    "/api/v1/risk/metrics",
    "/api/risk/pnl-summary",
    "/api/risk/exposure",
    "/api/risk/limits",
    "/api/risk/protections",
    "/api/v1/system/health",
    "/api/system/health",
    "/api/system/version",
    "/api/system/components",
    "/api/prime/status",
    "/api/v1/api/status",
    "/api/v1/research/backtest/results",
    "/api/v1/logs",
    # Additional endpoints found in components
    "/api/v1/pipeline/pnl?range=24h",
    "/api/metrics/radar?category=all",
    "/api/metrics/heatmap",
    "/api/metrics/breach_log?limit=20",
    "/api/metrics/latency?window=300",
    "/api/v1/swarm/status",
    "/api/v1/agents/health",
    "/api/v1/explainability/decisions",
    "/api/v1/wallet/balances",
    "/api/v1/consensus/history",
    "/api/v1/consensus/current",
    "/api/v1/logs/stats",
    "/api/v1/blockchain/health",
    "/api/v1/signals/sentiment",
    "/api/v1/market/data/freshness",
    "/api/v1/institutional/predictions/whales",
    # Operator/monitoring endpoints
    "/api/v1/operator/summary",
    "/api/v1/operator/feeds",
    "/api/v1/operator/activity",
    "/api/v1/monitoring/status",
    "/api/v1/monitoring/metrics",
    # Social
    "/api/v1/social/feed",
    "/api/v1/social/sentiment",
    # Trading
    "/api/v1/trading/status",
    "/api/v1/trading/history",
    "/api/v1/trading/positions",
    # Overview
    "/api/v1/overview/stats",
    "/api/v1/dashboard/summary",
    # Predictions
    "/api/v1/predictions/markets",
    "/api/v1/prediction-markets/markets",
    # Dev swarm
    "/api/dev-swarm/readiness",
    "/api/dev-swarm/readiness/slo",
    "/api/dev-swarm/codebase-drift",
    # Brier
    "/api/v1/brier/metrics",
    # Drawdown
    "/api/v1/drawdown/history",
    # Misc
    "/healthz",
    "/readyz",
]

ok = []
fail = []
for ep in endpoints:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=TIMEOUT)
        status = r.status_code
        short = ep[:60]
        if status < 400:
            ok.append(ep)
            print(f"  OK  {status} {short}")
        else:
            fail.append((ep, status))
            print(f" FAIL {status} {short}")
    except Exception as e:
        fail.append((ep, str(e)[:40]))
        print(f" ERR  --- {ep[:60]}  {str(e)[:40]}")

print(f"\n=== SUMMARY: {len(ok)} OK, {len(fail)} FAIL ===")
if fail:
    print("\nFailing endpoints:")
    for ep, st in fail:
        print(f"  {st:>5}  {ep}")
