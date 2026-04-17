"""Check orders_api.py for route conflicts with trading.py."""
import re
from pathlib import Path

api_dir = Path(r"c:\Dev\MERID\web\api")
PREFIX_RE = re.compile(r'prefix\s*=\s*["\']([^"\']+)["\']')
ROUTE_RE  = re.compile(r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']')


def routes(fn):
    c = (api_dir / fn).read_text(encoding="utf-8", errors="ignore")
    pfx_m = PREFIX_RE.search(c)
    pfx = pfx_m.group(1) if pfx_m else ""
    return {pfx + r for _, r in ROUTE_RE.findall(c)}


trading_routes = routes("trading.py")
orders_routes  = routes("orders_api.py")
conflicts = trading_routes & orders_routes

print("trading.py routes (sample):", sorted(trading_routes)[:6])
print("orders_api.py routes:", sorted(orders_routes))
print("CONFLICTS:", sorted(conflicts) if conflicts else "none")
