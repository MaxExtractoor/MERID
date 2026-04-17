"""Validate response shapes for all Overview page endpoints."""
import httpx
import json

BASE = "http://127.0.0.1:8011"

def check(name, url, required_keys, nested_checks=None):
    try:
        r = httpx.get(BASE + url, timeout=5)
        if r.status_code != 200:
            print(f"FAIL [{r.status_code}] {name}: {url}")
            return
        data = r.json()
        missing = [k for k in required_keys if k not in data]
        if missing:
            print(f"FAIL {name}: missing keys {missing}")
            print(f"  Got keys: {list(data.keys())}")
        else:
            print(f"OK   {name}")
        if nested_checks:
            for desc, check_fn in nested_checks.items():
                ok, msg = check_fn(data)
                if not ok:
                    print(f"  WARN {desc}: {msg}")
    except Exception as e:
        print(f"ERR  {name}: {e}")

# 1. SystemHealth - used by SystemHealthCard
check("SystemHealth", "/api/system/health",
    ["status", "timestamp", "incident_flag", "services"],
    {"services_are_objects": lambda d: (
        all(isinstance(v, dict) and "status" in v for v in d.get("services", {}).values()),
        f"services values: {[type(v).__name__ for v in d.get('services', {}).values()][:3]}"
    )})

# 2. PnL Summary - used by PnLCard
# Frontend expects: today_pnl, today_pnl_pct, mtm_pnl, max_drawdown, max_drawdown_pct, limit_daily_loss, limit_utilization_pct
check("PnLSummary", "/api/risk/pnl-summary",
    ["today_pnl", "today_pnl_pct", "limit_utilization_pct"])

# 3. Trading Summary - used by TradingOperationsCard
# Frontend expects: active_strategies, paused_strategies, venues_connected, venues, notional_deployed, notional_capacity, utilization_pct
check("TradingSummary", "/api/trading/summary",
    ["active_strategies", "venues_connected", "venues"])

# 4. Prime Status - used by PrimeStatusCard
# Frontend expects: mode, market_data_connected, narrative_available, data_feeds
check("PrimeStatus", "/api/prime/status",
    ["mode", "market_data_connected", "data_feeds"])

# 5. Agent Summary - used by AgentStatusCard
# Frontend expects: agents (array), summary.total, summary.healthy, summary.paused, summary.unhealthy
check("AgentSummary", "/api/agents/summary",
    ["agents", "summary"],
    {"summary_has_counts": lambda d: (
        all(k in d.get("summary", {}) for k in ["total", "healthy"]),
        f"summary keys: {list(d.get('summary', {}).keys())}"
    ),
    "agents_have_fields": lambda d: (
        len(d.get("agents", [])) == 0 or all(
            "name" in a and "status" in a for a in d["agents"][:2]
        ),
        f"agent keys: {list(d['agents'][0].keys()) if d.get('agents') else 'empty'}"
    )})

# 6. Risk Protections - used by RiskProtectionCard
check("RiskProtections", "/api/risk/protections",
    ["circuit_breaker", "lockdown", "risk_limits"],
    {"circuit_has_state": lambda d: (
        "state" in d.get("circuit_breaker", {}),
        f"circuit_breaker keys: {list(d.get('circuit_breaker', {}).keys())}"
    )})

# 7. Risk Exposure - used by ExposureBar
check("RiskExposure", "/api/risk/exposure",
    ["total_exposure", "buying_power"])

# 8. Portfolio Summary - used by Overview main
check("PortfolioSummary", "/api/portfolio/summary",
    [])  # Just check it returns valid JSON

# 9. Agent Activity - used by AgentActivityPanel
check("AgentActivity", "/api/agents/activity",
    ["agents"])

# 10. Recent Orders - used by Overview recentActivity
check("RecentOrders", "/api/orders/recent",
    ["orders"])

# 11. Live Prices - used by Overview watchlist
check("LivePrices", "/api/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD",
    [])

# 12. Prediction Markets - used by PredictionMarketsPanel
check("PredictionMarkets", "/api/v1/us-compliant/prediction-markets",
    ["markets"])
