"""Probe the specific endpoints that showed EMPTY in the E2E audit."""
import requests, json, sys

BASE = "http://localhost:8011"

# These are the endpoints that showed [EMPTY] in the previous audit run
ENDPOINTS = [
    "/api/v1/kalshi/orders",
    "/api/v1/kalshi/positions",
    "/api/v1/kalshi/risk/events",
    "/api/v1/kalshi/swarm/critic/history",
    "/api/v1/logs/stats",
    "/api/v1/loop/guard/verdicts",
    "/api/v1/operator/decisions/recent",
    "/api/v1/risk/agents",
    "/api/v1/risk/alerts",
    "/api/v1/risk/staleness",
    "/api/v1/sentiment/hashtags/signals",
    "/api/v1/system/fresh-start",
    # Also check these critical UI panels
    "/api/v1/kalshi-grid/matrix",
    "/api/v1/kalshi-grid/performance/calibration",
    "/api/v1/kalshi-grid/performance/agents",
    "/api/v1/prediction/consensus/summary",
    "/api/v1/prediction/consensus/teams",
    "/api/v1/prediction/consensus/leaderboard",
    "/api/v1/prediction/consensus/debates",
    "/api/v1/prediction/consensus/opinions",
    "/api/v1/notifications/telegram/log",
    "/api/v1/kalshi/sentiment/lane-snapshot",
    "/api/v1/kalshi/swarm/execution/stats",
    "/api/v1/kalshi/swarm/recalibration",
    "/debates/alerts",
    "/debates/correlation",
]

for path in ENDPOINTS:
    try:
        r = requests.get(f"{BASE}{path}", timeout=15)
        data = r.json() if r.status_code == 200 else None
        # Determine emptiness
        tag = "OK"
        if r.status_code != 200:
            tag = f"HTTP-{r.status_code}"
        elif data is not None:
            if isinstance(data, list) and len(data) == 0:
                tag = "EMPTY-LIST"
            elif isinstance(data, dict):
                # Check for meaningful data
                all_empty = True
                for k, v in data.items():
                    if v not in ([], {}, 0, 0.0, None, "", False, "unknown"):
                        all_empty = False
                        break
                if all_empty:
                    tag = "EMPTY-DICT"
                # Also check for nested emptiness in key fields
                for key in ("items", "data", "results", "messages", "agents", "rows", "debates", "opinions", "events", "alerts", "verdicts", "decisions"):
                    val = data.get(key)
                    if val is not None and (val == [] or val == {}):
                        tag = f"EMPTY({key}=[])"
                        break
        
        trunc = json.dumps(data)[:250] if data else str(r.text[:100])
        print(f"  [{tag:18s}] {path}")
        print(f"      {trunc}")
        print()
    except Exception as exc:
        print(f"  [ERROR             ] {path}")
        print(f"      {exc}")
        print()
