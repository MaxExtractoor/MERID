"""Test all endpoints needed by the Overview page."""
import httpx
import json

BASE = "http://127.0.0.1:8011"

# All endpoints the Overview page and its components call
endpoints = [
    # api.ts service (used by useDashboard hooks)
    ("GET", "/api/system/health", "SystemHealthCard"),
    ("GET", "/api/risk/pnl-summary", "PnLCard (via api.ts fetchJSON /risk/pnl-summary)"),
    ("GET", "/api/trading/summary", "TradingOperationsCard (via api.ts fetchJSON /trading/summary)"),
    ("GET", "/api/prime/status", "PrimeStatusCard (via api.ts fetchJSON /prime/status)"),
    ("GET", "/api/agents/summary", "AgentStatusCard (via api.ts fetchJSON /agents/summary)"),
    ("GET", "/api/risk/protections", "RiskProtectionCard"),
    ("GET", "/api/risk/exposure", "ExposureBar"),
    ("GET", "/api/portfolio/summary", "Overview loadData (via api.ts fetchJSON /portfolio/summary)"),
    ("GET", "/api/agents/activity", "AgentActivityPanel (via api.ts fetchJSON /agents/activity)"),
    ("GET", "/api/orders/recent", "Overview recentActivity (via api.ts fetchJSON /orders/recent)"),
    ("GET", "/api/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD", "Overview watchlist (via api.ts fetchJSON /prices/live)"),
    ("GET", "/api/v1/us-compliant/prediction-markets", "PredictionMarketsPanel"),
]

print(f"{'STATUS':8s} {'CODE':5s} {'ENDPOINT':55s} CONSUMER")
print("-" * 130)

for method, path, consumer in endpoints:
    try:
        url = BASE + path
        if method == "GET":
            r = httpx.get(url, timeout=5)
        else:
            r = httpx.post(url, timeout=5)
        
        status = "OK" if r.status_code == 200 else "FAIL"
        print(f"{status:8s} {r.status_code:<5d} {path:55s} {consumer}")
        
        if r.status_code != 200:
            print(f"         Response: {r.text[:200]}")
    except Exception as e:
        print(f"{'ERROR':8s} {'---':5s} {path:55s} {consumer}")
        print(f"         Exception: {e}")
