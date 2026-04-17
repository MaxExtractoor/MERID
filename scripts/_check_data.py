"""Check which data endpoints return empty/missing data."""
import requests, json

BASE = "http://localhost:8011"
TIMEOUT = 30

ENDPOINTS = [
    # Sentiment
    "/api/v1/sentiment/assets",
    "/api/v1/sentiment/asset/BTC",
    "/api/v1/sentiment/hashtags/signals",
    "/api/v1/sentiment/monitor/status",
    "/api/v1/kalshi/sentiment/bundle/BTC",
    "/api/v1/kalshi/sentiment/lane-snapshot",
    "/api/v1/kalshi/mood/all",
    # Consensus / Debate
    "/api/v1/prediction/consensus/summary",
    "/api/v1/prediction/consensus/debates",
    "/api/v1/prediction/consensus/debate-metrics",
    "/api/v1/prediction/consensus/opinions",
    "/api/v1/prediction/consensus/teams",
    "/api/v1/prediction/consensus/leaderboard",
    "/api/v1/prediction/metrics",
    "/debates/alerts",
    "/debates/correlation",
    "/debates/health/overview",
    # Telegram
    "/api/v1/notifications/telegram/log",
    "/api/v1/notifications/status",
    # Swarm matrix
    "/api/v1/kalshi-grid/matrix",
    "/api/v1/kalshi-grid/agents",
    "/api/v1/kalshi-grid/status",
    "/api/v1/kalshi/swarm/critic/history",
    "/api/v1/kalshi/swarm/recalibration",
    "/api/v1/kalshi/swarm/execution/stats",
    # Calibration
    "/api/v1/kalshi-grid/performance/calibration",
    "/api/v1/kalshi-grid/performance/summary",
    "/api/v1/kalshi-grid/performance/agents",
    "/api/v1/kalshi/metrics/forecasters",
]

for ep in ENDPOINTS:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=TIMEOUT)
        data = r.json() if r.status_code == 200 else {}
        # Check if data is "empty"
        empty = False
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list) and len(v) == 0:
                    empty = True
                    break
                if isinstance(v, dict) and len(v) == 0:
                    empty = True
                    break
        elif isinstance(data, list) and len(data) == 0:
            empty = True
        
        snippet = json.dumps(data)[:150]
        flag = "EMPTY" if empty else "OK"
        if r.status_code != 200:
            flag = f"ERR-{r.status_code}"
        print(f"  [{flag:8s}] {r.status_code}  {ep}")
        if flag != "OK":
            print(f"           {snippet}")
    except Exception as e:
        print(f"  [TIMEOUT ] ---  {ep}")
