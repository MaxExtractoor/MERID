"""Check for route-level conflicts between registered and orphaned routers."""
import re
from pathlib import Path

api_dir = Path(r"c:\Dev\MERID\web\api")
PREFIX_RE = re.compile(r'prefix\s*=\s*["\']([^"\']+)["\']')
ROUTE_RE  = re.compile(r'@router\.(get|post|put|delete|patch|websocket)\(["\']([^"\']+)["\']')


def get_routes(fn):
    p = api_dir / fn
    if not p.exists():
        return None, []
    content = p.read_text(encoding="utf-8", errors="ignore")
    pfx_m = PREFIX_RE.search(content)
    pfx = pfx_m.group(1) if pfx_m else ""
    routes = [(m, pfx + r) for m, r in ROUTE_RE.findall(content)]
    return pfx, routes


# Check pairs that share the same prefix
PAIRS = [
    ("modes.py",          "trading_mode.py"),
    ("markets_data.py",   "market_data.py"),
    ("risk_metrics_api.py", "risk.py"),
    ("swarm_routes.py",   "swarm.py"),
    ("consensus_api.py",  "consensus.py"),
    ("agents_real.py",    "agents.py"),
]

for orphan, registered in PAIRS:
    _, o_routes = get_routes(orphan)
    _, r_routes = get_routes(registered)
    o_set = {r for _, r in o_routes}
    r_set = {r for _, r in r_routes}
    conflicts = o_set & r_set
    print(f"\n{orphan} vs {registered}")
    print(f"  Orphan routes   : {sorted(o_set)[:6]}")
    print(f"  Registered routes: {sorted(r_set)[:6]}")
    if conflicts:
        print(f"  *** CONFLICTS: {sorted(conflicts)}")
    else:
        print(f"  OK — no overlapping paths")
