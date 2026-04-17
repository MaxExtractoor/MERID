"""Test ALL frontend API endpoints - compact output."""
import httpx

BASE = "http://127.0.0.1:8011"

ALL_ENDPOINTS = [
    ("Wallet", "GET", "/api/v1/wallet/balances"),
    ("Wallet", "GET", "/api/v1/wallet/status"),
    ("Treasury", "GET", "/api/v1/treasury/overview"),
    ("LiveTrading", "GET", "/api/v1/pipeline/summary"),
    ("LiveTrading", "GET", "/api/v1/pipeline/venues"),
    ("LiveTrading", "GET", "/api/v1/pipeline/leaderboard"),
    ("Positions", "GET", "/api/v1/trading/portfolio/summary"),
    ("Orders", "GET", "/api/v1/trading/orders/open"),
    ("Research", "GET", "/api/v1/markets/all"),
    ("PredictionMarkets", "GET", "/api/v1/us-compliant/prediction-markets"),
    ("Rewards", "GET", "/api/v1/rewards/summary"),
    ("SocialFeed", "GET", "/api/v1/social/feed"),
    ("Operator", "GET", "/api/v1/consensus/plans"),
    ("Operator", "GET", "/api/v1/consensus/metrics"),
    ("Operator", "GET", "/api/v1/consensus/opinions?limit=30"),
    ("Operator", "GET", "/api/v1/explainability/decisions"),
    ("RiskHealth", "GET", "/api/v1/risk/halt-status"),
    ("RiskHealth", "GET", "/api/v1/risk/staleness"),
    ("RiskHealth", "GET", "/api/v1/risk-metrics/agents"),
    ("RiskHealth", "GET", "/api/v1/data/freshness"),
    ("BotsAgents", "GET", "/api/v1/swarm/status"),
    ("BotsAgents", "GET", "/api/v1/arbitrage/scanner"),
    ("Mining", "GET", "/api/v1/mining/overview"),
    ("Institutional", "GET", "/api/v1/institutional/overview"),
    ("Plugins", "GET", "/api/v1/plugins/list"),
    ("Analytics", "GET", "/api/v1/analytics/overview"),
    ("Settings", "GET", "/api/v1/user/settings"),
    ("Logs", "GET", "/api/v1/notifications"),
    ("Logs", "GET", "/api/v1/notifications/telegram/log"),
    ("Components", "GET", "/api/v1/betting/overview"),
    ("Components", "GET", "/api/v1/paper-trading/portfolio/default"),
]

print("FAILING ENDPOINTS ONLY:")
print("-" * 70)
fails = []
for module, method, path in ALL_ENDPOINTS:
    try:
        r = httpx.get(BASE + path, timeout=5)
        if r.status_code != 200:
            fails.append((module, r.status_code, path))
            print(f"  [{r.status_code}] {module:20s} {path}")
    except Exception as e:
        fails.append((module, 0, path))
        print(f"  [ERR] {module:20s} {path}")

print(f"\n{len(fails)} endpoints need fixing")
