import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# Allow running this diagnostic script directly from the repo root.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Ensure settings are loaded from .env
os.environ.setdefault("MERID_RUNTIME_MODE", "15m_live")

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config


async def main():
    config = get_kalshi_config()
    client = KalshiVenueClient(config)

    print(f"=== Emergency Kalshi Query at {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Env: {config.env}, rest_url: {getattr(config, 'rest_base_url', None)}")

    # Open orders for the BTC market
    ticker = "KXBTC15M-26AUG121515-15"
    print(f"\n--- Open orders for {ticker} ---")
    orders_result = await client.get_open_orders_result(market_id=ticker)
    if orders_result.success:
        orders = orders_result.data or []
        print(f"Found {len(orders)} open orders")
        for o in orders:
            print(json.dumps({
                "order_id": getattr(o, "order_id", None),
                "client_order_id": getattr(o, "client_order_id", None),
                "side": getattr(o, "side", None),
                "action": getattr(o, "action", None),
                "price": getattr(o, "price", None),
                "size": getattr(o, "size", None),
                "status": getattr(o, "status", None),
                "tif": getattr(o, "time_in_force", None),
                "created_time": getattr(o, "created_time", None),
            }, indent=2, default=str))
    else:
        print(f"ERROR fetching open orders: {orders_result.error}")

    # All open orders
    print("\n--- All open orders ---")
    all_orders_result = await client.get_open_orders_result()
    if all_orders_result.success:
        all_orders = all_orders_result.data or []
        print(f"Found {len(all_orders)} total open orders")
        for o in all_orders:
            print(json.dumps({
                "order_id": getattr(o, "order_id", None),
                "client_order_id": getattr(o, "client_order_id", None),
                "ticker": getattr(o, "market_id", None),
                "side": getattr(o, "side", None),
                "action": getattr(o, "action", None),
                "price": getattr(o, "price", None),
                "size": getattr(o, "size", None),
                "status": getattr(o, "status", None),
            }, default=str))
    else:
        print(f"ERROR fetching all open orders: {all_orders_result.error}")

    # Positions
    print("\n--- Positions ---")
    positions_result = await client.get_positions_result()
    if positions_result.success:
        positions = positions_result.data or []
        print(f"Found {len(positions)} positions")
        for p in positions:
            raw = getattr(p, "raw_data", None) or {}
            print(json.dumps({
                "market_id": getattr(p, "market_id", None),
                "outcome_id": getattr(p, "outcome_id", None),
                "size": str(getattr(p, "size", None)),
                "average_entry_price": str(getattr(p, "average_entry_price", None)),
                "unrealized_pnl": str(getattr(p, "unrealized_pnl", None)),
                "raw_data": raw,
            }, indent=2, default=str))
    else:
        print(f"ERROR fetching positions: {positions_result.error}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
