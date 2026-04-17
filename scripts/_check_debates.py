"""Check what data the debate/consensus endpoints actually return."""
import requests, json

BASE = "http://localhost:8011"

endpoints = {
    "debates": "/api/v1/prediction/consensus/debates",
    "opinions": "/api/v1/prediction/consensus/opinions",
    "summary": "/api/v1/prediction/consensus/summary",
    "metrics": "/api/v1/prediction/consensus/debate-metrics",
    "teams": "/api/v1/prediction/consensus/teams",
    "leaderboard": "/api/v1/prediction/consensus/leaderboard",
    "brier": "/api/v1/prediction/metrics",
    "calibration": "/api/v1/kalshi-grid/performance/calibration",
    "perf_agents": "/api/v1/kalshi-grid/performance/agents",
    "perf_summary": "/api/v1/kalshi-grid/performance/summary",
    "forecasters": "/api/v1/kalshi/metrics/forecasters",
    "matrix": "/api/v1/kalshi-grid/matrix",
    "grid_agents": "/api/v1/kalshi-grid/agents",
    "telegram_log": "/api/v1/notifications/telegram/log",
    "critic_history": "/api/v1/kalshi/swarm/critic/history",
    "exec_stats": "/api/v1/kalshi/swarm/execution/stats",
}

for name, ep in endpoints.items():
    try:
        r = requests.get(f"{BASE}{ep}", timeout=30)
        d = r.json()
        # count meaningful data
        snippet = json.dumps(d)[:200]
        print(f"  {name:20s} {r.status_code}  {snippet}")
    except Exception as e:
        print(f"  {name:20s} FAIL  {e}")
