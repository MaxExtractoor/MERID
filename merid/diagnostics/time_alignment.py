"""
Time alignment and active window probe.

This diagnostic checks whether the process notion of "now" and Kalshi's market times
are aligned, and quantifies any skew + mis-selection.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def compute_open_close_from_close_ts(close_ts: int) -> tuple[datetime, datetime]:
    """
    Compute open_time_utc and close_time_utc solely from close_ts.
    
    For 15-minute markets, open is 15 minutes before close.
    """
    close_time = datetime.fromtimestamp(close_ts, tz=timezone.utc)
    open_time = close_time - timedelta(minutes=15)
    return open_time, close_time


def classify_market_status(open_time: datetime, close_time: datetime, now: datetime) -> str:
    """
    Classify market as LIVE, RECENT, FUTURE, or OLD based on time windows.
    """
    if open_time <= now < close_time:
        return "LIVE"
    elif now < open_time:
        return "FUTURE"
    elif now >= close_time and (now - close_time) <= timedelta(minutes=5):
        return "RECENT"
    else:
        return "OLD"


async def check_time_alignment_and_active_window() -> Dict[str, Any]:
    """
    Check time alignment and active window selection.
    
    Returns:
        Dict with diagnostic results including:
        - now_utc
        - server local time
        - Per-asset analysis of catalog active vs close_ts-based selection
        - Any mismatches or time skew detected
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get catalog
    catalog = get_market_catalog()
    await catalog.refresh()
    
    results = {
        "now_utc": now_utc.isoformat(),
        "server_local_time": datetime.now().isoformat(),
        "kalshi_server_time": None,  # Could fetch from Kalshi API if available
        "assets": {},
        "summary": {
            "total_assets": len(ACTIVE_CRYPTO_ASSETS),
            "catalog_vs_ts_matches": 0,
            "catalog_vs_ts_mismatches": 0,
            "time_skew_seconds": None
        }
    }
    
    for asset in ACTIVE_CRYPTO_ASSETS:
        asset_result = {
            "series": f"KX{asset.upper()}15M",
            "catalog_active_market": None,
            "catalog_active_close_ts": None,
            "catalog_active_status": None,
            "ts_live_market": None,
            "ts_live_close_ts": None,
            "ts_live_status": None,
            "match": False,
            "all_markets": []
        }
        
        # Get all markets for this asset
        markets = catalog.get_markets_by_asset(asset, timeframe="15m")
        
        for market in markets:
            market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
            if not market_id:
                continue
            
            close_ts = getattr(market, 'close_ts', None)
            if not close_ts:
                continue
            
            open_time, close_time = compute_open_close_from_close_ts(close_ts)
            status = classify_market_status(open_time, close_time, now_utc)
            
            market_info = {
                "market_id": market_id,
                "close_ts": close_ts,
                "open_time_utc": open_time.isoformat(),
                "close_time_utc": close_time.isoformat(),
                "status": status
            }
            
            asset_result["all_markets"].append(market_info)
            
            # Track TS-based live market
            if status == "LIVE":
                if asset_result["ts_live_market"] is None:
                    asset_result["ts_live_market"] = market_id
                    asset_result["ts_live_close_ts"] = close_ts
                    asset_result["ts_live_status"] = status
        
        # Get catalog's active market (using current logic)
        active_markets = catalog.get_active_markets()
        for market in active_markets:
            if hasattr(market, 'asset') and market.asset.lower() == asset.lower():
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                if market_id:
                    asset_result["catalog_active_market"] = market_id
                    asset_result["catalog_active_close_ts"] = getattr(market, 'close_ts', None)
                    if asset_result["catalog_active_close_ts"]:
                        open_time, close_time = compute_open_close_from_close_ts(asset_result["catalog_active_close_ts"])
                        asset_result["catalog_active_status"] = classify_market_status(open_time, close_time, now_utc)
                break
        
        # Check if catalog and TS-based selection match
        asset_result["match"] = (
            asset_result["catalog_active_market"] == asset_result["ts_live_market"]
        )
        
        if asset_result["match"]:
            results["summary"]["catalog_vs_ts_matches"] += 1
        else:
            results["summary"]["catalog_vs_ts_mismatches"] += 1
        
        results["assets"][asset] = asset_result
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_time_alignment_and_active_window())
    print(json.dumps(result, indent=2))
