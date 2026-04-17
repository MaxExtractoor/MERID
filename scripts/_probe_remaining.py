"""Probe only the endpoints that are still showing EMPTY."""
import requests, json

BASE = "http://localhost:8011"
ENDPOINTS = [
    "/api/v1/kalshi/orders",
    "/api/v1/kalshi/positions",
    "/api/v1/kalshi/risk/events",
    "/api/v1/kalshi/swarm/critic/history",
    "/api/v1/logs/stats",
    "/api/v1/loop/guard/verdicts",
    "/api/v1/operator/decisions/recent",
    "/api/v1/risk/alerts",
    "/debates/alerts",
]

for path in ENDPOINTS:
    try:
        r = requests.get(f"{BASE}{path}", timeout=20)
        data = r.json() if r.status_code == 200 else None
        tag = f"HTTP-{r.status_code}" if r.status_code != 200 else "OK"
        if data is not None:
            if isinstance(data, list) and len(data) == 0:
                tag = "EMPTY-LIST"
            elif isinstance(data, dict):
                for key in ("orders", "positions", "events", "critiques", "verdicts", "decisions", "alerts"):
                    val = data.get(key)
                    if val is not None and (val == [] or val == {}):
                        tag = f"EMPTY({key})"
                        break
        trunc = json.dumps(data)[:300] if data else r.text[:100]
        print(f"[{tag:18s}] {path}")
        print(f"  {trunc}")
        print()
    except Exception as exc:
        print(f"[ERROR             ] {path}")
        print(f"  {exc}")
        print()
