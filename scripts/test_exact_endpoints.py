"""Test the EXACT endpoints that each failing view uses."""
import requests
BASE = "http://127.0.0.1:8011"

# Endpoints used by the views the user reported as broken
tests = [
    # Overview.tsx direct fetches (no /v1 prefix!)
    ("/api/portfolio/summary", "Overview - portfolio"),
    ("/api/prices/live?symbols=BTC,ETH,SOL,AVAX", "Overview - live prices"),
    ("/api/orders/recent?limit=8", "Overview - recent orders"),
    ("/api/operator/equity-series?window=1d", "Overview - equity series"),
    ("/api/risk/exposure", "Overview - risk exposure"),
    # useDashboard hooks (via api service /api prefix)
    ("/api/system/health", "Dashboard - system health"),
    ("/api/risk/pnl-summary", "Dashboard - PnL"),
    ("/api/trading/summary", "Dashboard - trading"),
    ("/api/prime/status", "Dashboard - prime"),
    ("/api/agents/summary", "Dashboard - agents summary"),
    ("/api/risk/protections", "Dashboard - risk protections"),
    ("/api/agents/activity", "Dashboard - agent activity"),
    # Operator
    ("/api/operator/summary", "Operator - summary"),
    # Monitoring / Live Monitoring
    ("/api/v1/monitoring/status", "Monitoring - status"),
    ("/api/v1/monitoring/metrics", "Monitoring - metrics"),
    # Trading.tsx
    ("/api/v1/positions", "Trading - positions"),
    ("/api/v1/orders", "Trading - orders"),
    ("/api/v1/fills", "Trading - fills"),
    # Agents.tsx
    ("/api/v1/agents", "Agents - list"),
    ("/api/v1/agents/health", "Agents - health"),
    ("/api/v1/swarm/status", "Agents - swarm"),
    # Social
    ("/api/v1/social/feed", "Social - feed"),
    # Predictions
    ("/api/v1/us-compliant/prediction-markets", "Predictions - markets"),
    # Brier
    ("/api/v1/metrics/brier", "Brier - metrics"),
    # Consensus
    ("/api/v1/consensus/history", "Consensus - history"),
    ("/api/v1/consensus/current", "Consensus - current"),
    # Logs
    ("/api/v1/logs/stats", "Logs - stats"),
]

for ep, label in tests:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=5)
        s = "OK" if r.status_code < 400 else "FAIL"
        print(f"  {s:4s} {r.status_code} {label:35s} {ep}")
    except Exception as e:
        print(f"  TMO  --- {label:35s} {ep}  ({str(e)[:30]})")
