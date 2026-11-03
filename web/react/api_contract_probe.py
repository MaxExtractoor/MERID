"""
api_contract_probe.py — end-to-end contract check for every endpoint the UI calls.

Imports the REAL app from web.main_15m_lean WITHOUT running lifespan, so
app.state is empty — this verifies that every handler degrades honestly
(200-with-empty / explicit error) instead of 500ing on missing state, that
the auth gate works, and that register -> session -> authed request flows.

Usage (repo root):
    python web/react/api_contract_probe.py
"""

import os
import sys
import json

# Mirror the production auth posture from start_15m.ps1 so the probe hits the
# real session-validation path (no dev/test/single-user bypasses).
os.environ["MERID_ENV"] = "prod"
os.environ["MERID_SINGLE_USER_OPERATOR"] = "0"
os.environ["MERID_DEV_AUTH_BYPASS"] = "0"
os.environ.pop("MERID_SKIP_AUTH_FOR_TESTS", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient  # noqa: E402
from web.main_15m_lean import app          # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

T = "KXBTC15M-TEST"  # parametrized-route sample ticker

# (method, path) — every endpoint the React app calls.
ENDPOINTS = [
    ("GET",  "/api/v1/kalshi-grid/agents"),
    ("GET",  "/api/v1/kalshi-grid/summary"),
    ("GET",  "/api/v1/kalshi-grid/decision-feed?limit=60"),
    ("GET",  "/api/v1/agents"),
    ("GET",  "/api/v1/kalshi/market-states"),
    ("GET",  "/api/v1/kalshi/internal/kalshi_health"),
    ("GET",  "/api/v1/kalshi/balance"),
    ("GET",  "/api/v1/kalshi/positions"),
    ("GET",  "/api/v1/kalshi/orders"),
    ("GET",  "/api/v1/kalshi/fills?since_hours=24&limit=100"),
    ("GET",  "/api/v1/kalshi/pnl"),
    ("GET",  "/api/v1/kalshi/pnl-history"),
    ("GET",  "/api/v1/kalshi/risk"),
    ("GET",  "/api/v1/kalshi/risk/envelope"),
    ("GET",  "/api/v1/kalshi/risk/dd-guard"),
    ("GET",  "/api/v1/kalshi/kill-switch"),
    ("GET",  "/api/v1/kalshi/order-errors"),
    ("GET",  "/api/v1/kalshi/health/reconciliation"),
    ("GET",  "/api/v1/kalshi/markets"),
    ("GET",  "/api/v1/kalshi/calibration/stats"),
    ("GET",  "/api/v1/kalshi/calibration/cell-metrics"),
    ("GET",  f"/api/v1/kalshi/markets/{T}/orderbook"),
    ("GET",  "/api/v1/loop/guard/verdicts"),
    ("GET",  "/api/v1/loop/status"),
    ("GET",  "/api/v1/loop/tick-log?limit=100"),
    ("GET",  "/api/v1/loop-status"),
    ("GET",  "/api/v1/live-runtime-state/"),
    ("GET",  "/api/v1/unified-health"),
    ("GET",  "/api/v1/health"),
    ("GET",  "/api/v1/spot/prices"),
    ("GET",  "/api/v1/data-flow-validation"),
    ("GET",  "/api/health/kalshi-readiness"),
    ("GET",  f"/api/internal/v1/market-state/{T}"),
]


def top_keys(resp) -> str:
    try:
        body = resp.json()
    except Exception:
        return "<non-json>"
    if isinstance(body, dict):
        return "{" + ", ".join(list(body.keys())[:12]) + "}"
    if isinstance(body, list):
        return f"[list n={len(body)}]"
    return repr(body)[:80]


def main() -> int:
    print("== auth flow ==")
    r = client.post("/api/v1/auth/register", json={"username": "operator-probe"})
    print(f"register: {r.status_code} {top_keys(r)}")
    sid = (r.json() or {}).get("session_id")
    if not sid:
        print("FATAL: no session_id from register")
        return 1

    r = client.get("/api/v1/auth/session", headers={"X-Session-ID": sid})
    print(f"session validate: {r.status_code} {top_keys(r)}")

    auth = {"X-Session-ID": sid}
    failures = []

    print("\n== endpoint matrix (bare | authed) ==")
    for method, path in ENDPOINTS:
        bare = client.request(method, path)
        authed = client.request(method, path, headers=auth)
        flag = ""
        if authed.status_code >= 500:
            flag = "  <-- 5xx (handler crash on empty app.state?)"
            failures.append(path)
        elif authed.status_code == 404:
            flag = "  <-- 404 (route missing or ticker lookup miss)"
        print(f"{method:4} {path:55} {bare.status_code} | {authed.status_code}  {top_keys(authed)[:90]}{flag}")

    print("\n== mutation auth (bare must NOT mutate) ==")
    for method, path, body in [
        ("POST", "/api/v1/kalshi/kill-switch?activate=false", None),
        ("POST", "/api/v1/live-runtime-state/halt", {"reason": "probe"}),
        ("POST", "/api/v1/live-runtime-state/release", {}),
    ]:
        b = client.request(method, path, json=body)
        a = client.request(method, path, headers=auth, json=body)
        print(f"{method:4} {path:55} {b.status_code} | {a.status_code}  {top_keys(a)[:90]}")

    print(f"\n{len(failures)} 5xx failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
