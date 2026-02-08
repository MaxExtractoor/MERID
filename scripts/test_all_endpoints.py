"""Test ALL frontend API endpoints against the running backend."""
import httpx
import sys

BASE = "http://127.0.0.1:8011"

# Map: (module, method, path, description)
ALL_ENDPOINTS = [
    # === WALLET ===
    ("Wallet", "GET", "/api/v1/wallet/balances", "Wallet.tsx main data"),
    ("Wallet", "GET", "/api/v1/wallet/status", "wallet status"),
    ("Wallet", "GET", "/api/v1/wallet/keys", "wallet keys"),
    ("Wallet", "GET", "/api/v1/wallet/vaults", "wallet vaults"),
    ("Wallet", "GET", "/api/v1/wallet/limits", "wallet limits"),

    # === TREASURY ===
    ("Treasury", "GET", "/api/v1/treasury/overview", "Treasury.tsx main data"),

    # === LIVE TRADING (Trade Floor uses pipeline endpoints) ===
    ("LiveTrading", "GET", "/api/v1/pipeline/summary", "DomainControlPanel"),
    ("LiveTrading", "GET", "/api/v1/pipeline/venues", "VenueHealthGrid, ModeControlPanel"),
    ("LiveTrading", "GET", "/api/v1/pipeline/leaderboard", "StrategyLeaderboard"),

    # === POSITIONS ===
    ("Positions", "GET", "/api/v1/trading/portfolio/summary", "Positions.tsx main data"),

    # === ORDERS ===
    ("Orders", "GET", "/api/v1/trading/orders/open", "Orders.tsx main data"),

    # === RESEARCH (uses intelligence endpoints) ===
    ("Research", "GET", "/api/v1/markets/all", "useMarketsData"),

    # === PREDICTION MARKETS ===
    ("PredictionMarkets", "GET", "/api/v1/us-compliant/prediction-markets", "PredictionMarketsPanel"),

    # === REWARDS ===
    ("Rewards", "GET", "/api/v1/rewards/summary", "Rewards.tsx summary"),
    ("Rewards", "GET", "/api/v1/rewards/leaderboard?limit=20", "Rewards.tsx leaderboard"),
    ("Rewards", "GET", "/api/v1/rewards/quests?season=1", "Rewards.tsx quests"),

    # === SOCIAL FEED ===
    ("SocialFeed", "GET", "/api/v1/social/feed", "Social.tsx feed"),

    # === OPERATOR ===
    ("Operator", "GET", "/api/v1/orchestrator/summary", "OrchestratorPanel"),
    ("Operator", "GET", "/api/v1/consensus/status", "ConsensusBoard, ConsensusPanel"),
    ("Operator", "GET", "/api/v1/consensus/plans", "ConsensusBoard"),
    ("Operator", "GET", "/api/v1/consensus/metrics", "ConsensusPanel"),
    ("Operator", "GET", "/api/v1/consensus/votes", "ConsensusPanel"),
    ("Operator", "GET", "/api/v1/consensus/opinions?limit=30", "DebateTimeline"),
    ("Operator", "GET", "/api/v1/explainability/decisions", "ExplainabilityTimeline"),
    ("Operator", "GET", "/api/v1/reflection/summary", "ReflectionPanel"),
    ("Operator", "GET", "/api/v1/reflection/reflections?limit=20", "ReflectionPanel"),
    ("Operator", "GET", "/api/v1/quadratic-funding/proposals", "QuadraticFundingPanel"),
    ("Operator", "GET", "/api/v1/quadratic-funding/rounds/summary?limit=10", "QuadraticFundingPanel"),

    # === RISK & HEALTH ===
    ("RiskHealth", "GET", "/api/v1/risk/halt-status", "TradingHaltBanner"),
    ("RiskHealth", "GET", "/api/v1/risk/staleness", "TradingHaltBanner"),
    ("RiskHealth", "GET", "/api/v1/risk-metrics/agents", "AgentPerformanceTable, AgentStatusPanel"),
    ("RiskHealth", "GET", "/api/v1/data/freshness", "DataFreshnessPanel"),

    # === BOTS/AGENTS ===
    ("BotsAgents", "GET", "/api/v1/swarm/status", "SwarmPanel"),
    ("BotsAgents", "GET", "/api/v1/arbitrage/opportunities", "ArbitragePanel"),
    ("BotsAgents", "GET", "/api/v1/arbitrage/scanner", "ArbScannerPanel"),

    # === DEV SWARM ===
    ("DevSwarm", "GET", "/api/dev-swarm/tasks", "DevSwarm tasks"),
    ("DevSwarm", "GET", "/api/dev-swarm/stats", "DevSwarm stats"),

    # === MINING ===
    ("Mining", "GET", "/api/v1/mining/overview", "Mining.tsx main data"),
    ("Mining", "GET", "/api/v1/mining/status", "Mining status"),

    # === INSTITUTIONAL ===
    ("Institutional", "GET", "/api/v1/institutional/overview", "Institutional.tsx main data"),

    # === PLUGINS ===
    ("Plugins", "GET", "/api/v1/plugins/list", "Plugins.tsx main data"),

    # === API DASHBOARD (no direct frontend calls found, uses system endpoints) ===

    # === ANALYTICS ===
    ("Analytics", "GET", "/api/v1/analytics/overview", "AnalyticsCharts"),

    # === SETTINGS ===
    ("Settings", "GET", "/api/v1/user/settings", "Settings.tsx main data"),

    # === SYSTEM HEALTH ===
    ("SystemHealth", "GET", "/api/system/health", "Health.tsx main data"),

    # === LOGS ===
    ("Logs", "GET", "/api/v1/notifications", "NotificationPanel"),
    ("Logs", "GET", "/api/v1/notifications/telegram/log", "TelegramLogViewer"),

    # === ADDITIONAL COMPONENTS ===
    ("Components", "GET", "/api/v1/betting/overview", "Betting.tsx"),
    ("Components", "GET", "/api/v1/blockchain/compliance", "CompliancePanel"),
    ("Components", "GET", "/api/v1/blockchain/health", "OnChainHealthPanel"),
    ("Components", "GET", "/api/v1/signals/alerts/history", "AlertHistoryPanel"),
    ("Components", "GET", "/api/v1/simulation/status", "SimulationControlPanel"),
    ("Components", "GET", "/api/v1/paper-trading/portfolio/default", "PaperTradingPanel"),
]

ok_count = 0
fail_count = 0
results_by_module = {}

for module, method, path, desc in ALL_ENDPOINTS:
    try:
        url = BASE + path
        if method == "GET":
            r = httpx.get(url, timeout=5)
        else:
            r = httpx.post(url, timeout=5)
        
        status = "OK" if r.status_code == 200 else "FAIL"
        code = r.status_code
    except Exception as e:
        status = "ERR"
        code = 0
    
    if status == "OK":
        ok_count += 1
    else:
        fail_count += 1
    
    results_by_module.setdefault(module, []).append((status, code, path, desc))

# Print results grouped by module
for module, results in results_by_module.items():
    all_ok = all(r[0] == "OK" for r in results)
    marker = "PASS" if all_ok else "FAIL"
    print(f"\n{'='*60}")
    print(f"[{marker}] {module}")
    print(f"{'='*60}")
    for status, code, path, desc in results:
        icon = "OK" if status == "OK" else "XX"
        print(f"  {icon} [{code:3d}] {path:55s} {desc}")

print(f"\n{'='*60}")
print(f"TOTAL: {ok_count} OK, {fail_count} FAIL out of {ok_count + fail_count}")
print(f"{'='*60}")
