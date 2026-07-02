"""
Active vs truly live probe.

This diagnostic proves whether your "active" market is actually live on Kalshi,
using only REST and close_ts.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.client import get_kalshi_client
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def compute_open_close_from_close_ts(close_ts: int) -> tuple[datetime, datetime]:
    """Compute open_time_utc and close_time_utc solely from close_ts."""
    close_time = datetime.fromtimestamp(close_ts, tz=timezone.utc)
    open_time = close_time - timedelta(minutes=15)
    return open_time, close_time


def classify_market_status(open_time: datetime, close_time: datetime, now: datetime) -> str:
    """Classify market as LIVE, RECENT, FUTURE, or OLD."""
    if open_time <= now < close_time:
        return "LIVE"
    elif now < open_time:
        return "FUTURE"
    elif now >= close_time and (now - close_time) <= timedelta(minutes=5):
        return "RECENT"
    else:
        return "OLD"


async def check_active_vs_truly_live() -> Dict[str, Any]:
    """
    Check active vs truly live markets using REST and close_ts.
    
    Returns:
        Dict with diagnostic results including:
        - Per-asset comparison of prod_active_market vs ts_live_market
        - REST status for both markets
        - Match status and comments
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get catalog
    catalog = get_market_catalog()
    await catalog.refresh()
    
    # Get Kalshi client for REST queries
    kalshi_client = get_kalshi_client()
    
    results = {
        "timestamp": now_utc.isoformat(),
        "assets": {},
        "summary": {
            "total_assets": len(ACTIVE_CRYPTO_ASSETS),
            "matches": 0,
            "mismatches": 0,
            "prod_picking_closed": 0,
            "ts_picking_closed": 0
        }
    }
    
    for asset in ACTIVE_CRYPTO_ASSETS:
        asset_result = {
            "prod_active_market": None,
            "prod_status": None,
            "prod_close_ts": None,
            "prod_status_from_close_ts": None,
            "ts_live_market": None,
            "ts_status": None,
            "ts_close_ts": None,
            "ts_status_from_close_ts": None,
            "match": False,
            "comment": ""
        }
        
        # Get all markets for this asset
        markets = catalog.get_markets_by_asset(asset, timeframe="15m")
        
        # Find TS-based live market
        ts_live_market = None
        ts_live_close_ts = None
        ts_market_statuses = []  # Track all market statuses for debugging
        for market in markets:
            close_ts = getattr(market, 'close_ts', None)
            market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
            if close_ts:
                open_time, close_time = compute_open_close_from_close_ts(close_ts)
                status = classify_market_status(open_time, close_time, now_utc)
                ts_market_statuses.append({
                    "market_id": market_id,
                    "close_ts": close_ts,
                    "open_time": open_time.isoformat(),
                    "close_time": close_time.isoformat(),
                    "status": status
                })
                if status == "LIVE":
                    if market_id:
                        ts_live_market = market_id
                        ts_live_close_ts = close_ts
                        asset_result["ts_status_from_close_ts"] = status
                        break
        
        # Add debug info about market statuses
        asset_result["ts_market_status_debug"] = ts_market_statuses[:5]  # Limit to first 5 for brevity
        
        # Get catalog's active market (production logic)
        active_markets = catalog.get_active_markets()
        prod_active_market = None
        prod_close_ts = None
        for market in active_markets:
            if hasattr(market, 'asset') and market.asset.lower() == asset.lower():
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                if market_id:
                    prod_active_market = market_id
                    prod_close_ts = getattr(market, 'close_ts', None)
                    if prod_close_ts:
                        open_time, close_time = compute_open_close_from_close_ts(prod_close_ts)
                        asset_result["prod_status_from_close_ts"] = classify_market_status(open_time, close_time, now_utc)
                break
        
        asset_result["prod_active_market"] = prod_active_market
        asset_result["prod_close_ts"] = prod_close_ts
        asset_result["ts_live_market"] = ts_live_market
        asset_result["ts_close_ts"] = ts_live_close_ts
        
        # Query REST for status if we have market IDs
        if prod_active_market:
            try:
                market_info = await kalshi_client.get_market(prod_active_market)
                # market_info is an EventMarket object, not a dict
                if market_info:
                    asset_result["prod_status"] = getattr(market_info, 'status', 'unknown')
                else:
                    asset_result["prod_status"] = 'unknown'
                if asset_result["prod_status"] in ['closed', 'settled', 'expired']:
                    results["summary"]["prod_picking_closed"] += 1
            except Exception as e:
                asset_result["prod_status"] = f"ERROR: {str(e)}"
        
        if ts_live_market:
            try:
                market_info = await kalshi_client.get_market(ts_live_market)
                # market_info is an EventMarket object, not a dict
                if market_info:
                    asset_result["ts_status"] = getattr(market_info, 'status', 'unknown')
                else:
                    asset_result["ts_status"] = 'unknown'
                if asset_result["ts_status"] in ['closed', 'settled', 'expired']:
                    results["summary"]["ts_picking_closed"] += 1
            except Exception as e:
                asset_result["ts_status"] = f"ERROR: {str(e)}"
        
        # Check match
        asset_result["match"] = (prod_active_market == ts_live_market)
        
        if asset_result["match"]:
            results["summary"]["matches"] += 1
            asset_result["comment"] = "Production and TS-based selection match"
        else:
            results["summary"]["mismatches"] += 1
            if prod_active_market and ts_live_market:
                asset_result["comment"] = f"Production picking {prod_active_market}, TS-based picking {ts_live_market}"
            elif prod_active_market and not ts_live_market:
                asset_result["comment"] = f"Production picking {prod_active_market}, TS-based found no live market"
            elif not prod_active_market and ts_live_market:
                asset_result["comment"] = f"Production found no active market, TS-based picking {ts_live_market}"
            else:
                asset_result["comment"] = "Neither production nor TS-based found a market"
        
        results["assets"][asset] = asset_result
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_active_vs_truly_live())
    print(json.dumps(result, indent=2))
