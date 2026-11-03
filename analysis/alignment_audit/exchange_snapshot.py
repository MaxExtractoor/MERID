"""Read-only fresh exchange snapshot: balance, open orders, positions.

GET-only — no order placement, cancellation, transfers, or ledger writes.
"""
import asyncio, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config

async def main():
    cfg = get_kalshi_config()
    c = KalshiVenueClient(cfg)
    out = {}
    try:
        bal = await c._request_with_resilience("GET", "/portfolio/balance",
                                             operation_name="ro_balance")
        out["balance"] = bal.data if bal.success else {"error": str(bal.error)}

        for status in ("resting",):
            r = await c._request_with_resilience(
                "GET", "/portfolio/orders",
                params={"status": status, "limit": 200},
                operation_name="ro_orders")
            out[f"orders_{status}"] = r.data if r.success else {"error": str(r.error)}

        r = await c._request_with_resilience(
            "GET", "/portfolio/positions", params={"limit": 200},
            operation_name="ro_positions")
        out["positions"] = r.data if r.success else {"error": str(r.error)}
    finally:
        await c.close()
    print(json.dumps(out, indent=2, default=str))

asyncio.run(main())
