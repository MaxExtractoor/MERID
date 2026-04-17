"""Scan orphaned web/api routers and summarise their routes."""
import re
from pathlib import Path

api_dir = Path(r"c:\Dev\MERID\web\api")

CANDIDATES = [
    "agents_health.py", "agents_real.py", "consensus_api.py", "dev_chat.py",
    "markets_data.py", "modes.py", "observability.py", "orders_api.py",
    "risk_metrics.py", "risk_metrics_api.py", "swarm_routes.py",
    "ui_audit.py", "websocket_health.py", "ws_dedicated_streams.py",
    "ws_events.py", "ws_kafka_bridge.py", "ws_paper.py", "ws_trade_events.py",
]

PREFIX_RE = re.compile(r'prefix\s*=\s*["\']([^"\']+)["\']')
ROUTE_RE  = re.compile(r'@router\.(get|post|put|delete|patch|websocket)\(["\']([^"\']+)["\']')

for fn in CANDIDATES:
    p = api_dir / fn
    if not p.exists():
        continue
    content = p.read_text(encoding="utf-8", errors="ignore")
    pfx_m = PREFIX_RE.search(content)
    pfx = pfx_m.group(1) if pfx_m else "(no prefix)"
    routes = ROUTE_RE.findall(content)
    route_str = ", ".join(f"{m}{r}" for m, r in routes[:4])
    if len(routes) > 4:
        route_str += f" ... (+{len(routes)-4})"
    print(f"{fn}")
    print(f"  prefix : {pfx}")
    print(f"  routes : {route_str or '(none)'}")
    print()
