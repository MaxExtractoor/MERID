"""Diagnose which API calls cause fallback data in the frontend.
Tests through the Vite proxy (port 5173) to match exactly what the browser sees.
Checks response shapes against what components actually destructure.
"""
import httpx
import json
import sys

PROXY = "http://127.0.0.1:5173"
DIRECT = "http://127.0.0.1:8011"

# Test via proxy first
try:
    r = httpx.get(f"{PROXY}/api/system/health", timeout=5)
    BASE = PROXY
    print(f"Using PROXY at {PROXY}")
except:
    BASE = DIRECT
    print(f"Proxy unavailable, using DIRECT at {DIRECT}")

def check(name, path, required_keys, nested_checks=None):
    """Check endpoint returns 200 and has required keys."""
    try:
        r = httpx.get(f"{BASE}{path}", timeout=5)
        if r.status_code != 200:
            print(f"  FAIL [{r.status_code}] {name}: {path}")
            return False
        data = r.json()
        missing = [k for k in required_keys if k not in data]
        if missing:
            print(f"  FAIL {name}: missing keys {missing}")
            print(f"       got: {list(data.keys())[:10]}")
            return False
        if nested_checks:
            for parent_key, child_keys in nested_checks.items():
                if parent_key in data and isinstance(data[parent_key], dict):
                    child_missing = [k for k in child_keys if k not in data[parent_key]]
                    if child_missing:
                        print(f"  FAIL {name}: {parent_key} missing {child_missing}")
                        return False
        print(f"  OK   {name}")
        return True
    except Exception as e:
        print(f"  ERR  {name}: {e}")
        return False

ok = 0
fail = 0

def t(name, path, keys, nested=None):
    global ok, fail
    if check(name, path, keys, nested):
        ok += 1
    else:
        fail += 1

print("\n=== OVERVIEW PAGE ===")
t("SystemHealth", "/api/system/health", ["status", "timestamp", "environment", "incident_flag", "services"])
t("PnLSummary", "/api/risk/pnl-summary", ["today_pnl", "today_pnl_pct", "mtm_pnl", "max_drawdown_pct", "limit_utilization_pct", "limit_daily_loss"])
t("TradingSummary", "/api/trading/summary", ["active_strategies", "paused_strategies", "venues_connected", "venues", "notional_deployed", "notional_capacity", "utilization_pct"])
t("PrimeStatus", "/api/prime/status", ["mode", "market_data_connected", "narrative_available", "data_feeds"])
t("AgentsSummary", "/api/agents/summary", ["agents", "summary"], {"summary": ["total", "healthy", "paused", "unhealthy"]})
t("RiskProtections", "/api/risk/protections", ["circuit_breaker", "lockdown", "risk_limits", "recent_events", "timestamp"],
  {"circuit_breaker": ["state", "error_count", "threshold", "window_seconds", "cooldown_seconds"],
   "lockdown": ["trading_suite_enabled", "global_mode", "spectator_mode"],
   "risk_limits": ["max_daily_loss_usd", "current_daily_pnl", "daily_loss_utilization_pct", "max_open_orders", "current_open_orders"]})
t("RiskExposure", "/api/risk/exposure", ["total_exposure", "total_exposure_pct", "buying_power", "open_orders_count", "by_symbol"])
t("PortfolioSummary", "/api/portfolio/summary", ["equity"])
t("RecentOrders", "/api/orders/recent", ["orders"])
t("LivePrices", "/api/prices/live?symbols=BTC-USD,ETH-USD", ["prices"])

print("\n=== WALLET PAGE ===")
t("WalletBalances", "/api/v1/wallet/balances", ["balances", "transactions", "total_value_usd"])

print("\n=== TREASURY PAGE ===")
t("TreasuryOverview", "/api/v1/treasury/overview", ["total_value_usd", "balances", "proposals", "funding_rounds", "governance_stats"])

print("\n=== POSITIONS PAGE ===")
t("PortfolioSummary", "/api/v1/trading/portfolio/summary", [])

print("\n=== ORDERS PAGE ===")
t("OpenOrders", "/api/v1/trading/orders/open", [])

print("\n=== RESEARCH PAGE ===")
t("MarketsAll", "/api/v1/markets/all", ["markets"])

print("\n=== PREDICTION MARKETS PAGE ===")
t("PredictionMarkets", "/api/v1/us-compliant/prediction-markets", ["markets"])

print("\n=== SOCIAL FEED PAGE ===")
t("SocialFeed", "/api/v1/social/feed", ["posts"])

print("\n=== OPERATOR PAGE ===")
t("Orchestrator", "/api/v1/orchestrator/summary", [])
t("ConsensusStatus", "/api/v1/consensus/status", [])
t("ConsensusPlans", "/api/v1/consensus/plans", ["plans"])
t("ConsensusMetrics", "/api/v1/consensus/metrics", [])
t("ConsensusOpinions", "/api/v1/consensus/opinions?limit=30", ["opinions"])
t("Explainability", "/api/v1/explainability/decisions", ["decisions"])
t("ReflectionSummary", "/api/v1/reflection/summary", [])
t("QuadraticFunding", "/api/v1/quadratic-funding/proposals", [])

print("\n=== RISK & HEALTH PAGE ===")
t("HaltStatus", "/api/v1/risk/halt-status", ["halted"])
t("Staleness", "/api/v1/risk/staleness", ["stale", "feeds"])
t("RiskMetricsAgents", "/api/v1/risk-metrics/agents", ["agents"])
t("DataFreshness", "/api/v1/data/freshness", ["feeds"])

print("\n=== BOTS/AGENTS PAGE ===")
t("SwarmStatus", "/api/v1/swarm/status", ["status", "total_agents"])
t("ArbScanner", "/api/v1/arbitrage/scanner", ["scanning"])

print("\n=== MINING PAGE ===")
t("MiningOverview", "/api/v1/mining/overview", ["rigs", "pools", "stats"])

print("\n=== INSTITUTIONAL PAGE ===")
t("InstitutionalOverview", "/api/v1/institutional/overview", ["accounts", "reports", "audit_logs", "stats"])

print("\n=== PLUGINS PAGE ===")
t("PluginsList", "/api/v1/plugins/list", ["plugins"])

print("\n=== ANALYTICS PAGE ===")
t("AnalyticsOverview", "/api/v1/analytics/overview", ["daily_pnl"])

print("\n=== SETTINGS PAGE ===")
t("UserSettings", "/api/v1/user/settings", ["theme", "notifications", "trading"])

print("\n=== LOGS PAGE ===")
t("Notifications", "/api/v1/notifications", ["notifications"])
t("TelegramLog", "/api/v1/notifications/telegram/log", ["messages"])

print(f"\n{'='*50}")
print(f"RESULTS: {ok} OK, {fail} FAIL out of {ok+fail}")
print(f"{'='*50}")
