"""Quick audit script - test all frontend-consumed endpoints."""
import httpx

BASE = "http://127.0.0.1:8011"
endpoints = [
    "/api/v1/portfolio/summary",
    "/api/v1/positions",
    "/api/v1/positions/summary",
    "/api/v1/orders",
    "/api/v1/orders/summary",
    "/api/v1/orders/open",
    "/api/v1/fills",
    "/api/v1/agents",
    "/api/agents/summary",
    "/api/v1/risk/metrics",
    "/api/v1/system/health",
    "/api/system/health",
    "/api/system/version",
    "/api/system/components",
    "/api/v1/wallet/balances",
    "/api/v1/api/status",
    "/api/v1/logs",
    "/api/trading/summary",
    "/api/prime/status",
    "/api/risk/pnl-summary",
    "/api/risk/exposure",
    "/api/risk/limits",
    "/api/risk/protections",
    "/api/v1/risk/alerts",
    "/api/v1/blockchain/health",
    "/api/v1/signals/sentiment",
    "/api/v1/system/decisions/recent",
    "/api/operator/audit-trail",
    "/api/v1/us-compliant/prediction-markets",
    "/api/v1/prediction-markets/positions",
    "/api/v1/charters",
    "/api/v1/research/backtest/results",
    "/api/v1/trading-mode/spectator/live",
    "/api/v1/trading-mode/spectator/record",
    "/api/dev-swarm/status",
    "/api/dev-swarm/agents",
    "/api/operator/system/status",
    "/api/v1/consensus/recent",
    "/api/v1/consensus/debate/latest",
    "/api/v1/trade-floor/status",
    "/api/v1/trade-floor/active-trades",
    "/api/v1/trade-floor/signals",
]

ok = []
fail = []
for path in endpoints:
    try:
        r = httpx.get(f"{BASE}{path}", timeout=10)
        snippet = r.text[:100].replace("\n", " ")
        if r.status_code == 200:
            ok.append(path)
            print(f"  OK  {path}")
        else:
            fail.append((path, r.status_code))
            print(f" {r.status_code} {path}  ->  {snippet}")
    except Exception as e:
        fail.append((path, str(e)))
        print(f" ERR {path}  ->  {e}")

print(f"\n=== {len(ok)} OK, {len(fail)} FAILED ===")
for p, s in fail:
    print(f"  FAIL: {s} {p}")
