"""
Catalog vs WebSocket subscriptions vs Market Data consistency probe.

This diagnostic verifies that catalog active markets, WS subscriptions, and
market-state orderbooks are all tracking the same set of tickers.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Set
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


async def check_catalog_ws_md_consistency() -> Dict[str, Any]:
    """
    Check consistency between catalog, WS subscriptions, and market state.
    
    Returns:
        Dict with diagnostic results including:
        - Per-asset comparison of catalog_active_ids, ws_sub_ids, md_state_ids
        - Differences between each layer
        - Last MD update ages
        - Any hard errors (mismatches or stale MD)
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get catalog
    catalog = get_market_catalog()
    await catalog.refresh()
    
    # Get market state store (singleton from running server)
    state_store = get_kalshi_market_state_store()
    
    # Get all tracked tickers from market state store
    all_md_tickers = state_store.tickers()
    all_md_states = state_store.get_all()
    
    results = {
        "timestamp": now_utc.isoformat(),
        "assets": {},
        "summary": {
            "total_assets": len(ACTIVE_CRYPTO_ASSETS),
            "catalog_ws_mismatches": 0,
            "ws_md_mismatches": 0,
            "catalog_md_mismatches": 0,
            "stale_md_errors": 0
        }
    }
    
    for asset in ACTIVE_CRYPTO_ASSETS:
        asset_result = {
            "catalog_active_ids": [],
            "ws_sub_ids": [],
            "md_state_ids": [],
            "diff_catalog_vs_ws": [],
            "diff_ws_vs_md": [],
            "diff_catalog_vs_md": [],
            "md_states": {},
            "errors": []
        }
        
        # Get catalog active markets for this asset
        active_markets = catalog.get_active_markets()
        for market in active_markets:
            if hasattr(market, 'asset') and market.asset.lower() == asset.lower():
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                if market_id:
                    asset_result["catalog_active_ids"].append(market_id)
        
        # Get WS subscribed tickers for this asset (from market state store)
        # The market state store contains all tickers that WS is subscribed to
        for ticker in all_md_tickers:
            if asset.upper() in ticker:
                asset_result["ws_sub_ids"].append(ticker)
        
        # Get market state entries for this asset
        for ticker in asset_result["ws_sub_ids"]:
            state = all_md_states.get(ticker)
            if state:
                asset_result["md_state_ids"].append(ticker)
                
                # Calculate MD age
                last_update = None
                if hasattr(state, 'last_book_update_ts') and state.last_book_update_ts:
                    last_update = state.last_book_update_ts
                elif hasattr(state, 'last_update_ts') and state.last_update_ts:
                    last_update = state.last_update_ts
                
                md_age = None
                if last_update:
                    # last_update_ts uses time.monotonic(), so calculate age as time.monotonic() - last_update
                    # time.monotonic() returns seconds since an arbitrary epoch (usually system boot)
                    md_age = time.monotonic() - last_update
                
                asset_result["md_states"][ticker] = {
                    "book_initialized": state.book_initialized if hasattr(state, 'book_initialized') else False,
                    "yes_bid": state.yes_bid if hasattr(state, 'yes_bid') else None,
                    "yes_ask": state.yes_ask if hasattr(state, 'yes_ask') else None,
                    "no_bid": state.no_bid if hasattr(state, 'no_bid') else None,
                    "no_ask": state.no_ask if hasattr(state, 'no_ask') else None,
                    "last_update_ts": last_update,
                    "md_age_seconds": md_age
                }
                
                # Flag stale MD (> 60 seconds)
                if md_age and md_age > 60:
                    asset_result["errors"].append(f"Stale MD for {ticker}: {md_age:.1f}s old")
                    results["summary"]["stale_md_errors"] += 1
        
        # Compute differences
        catalog_set = set(asset_result["catalog_active_ids"])
        ws_set = set(asset_result["ws_sub_ids"])
        md_set = set(asset_result["md_state_ids"])
        
        asset_result["diff_catalog_vs_ws"] = list(catalog_set.symmetric_difference(ws_set))
        asset_result["diff_ws_vs_md"] = list(ws_set.symmetric_difference(md_set))
        asset_result["diff_catalog_vs_md"] = list(catalog_set.symmetric_difference(md_set))
        
        # Count mismatches
        if asset_result["diff_catalog_vs_ws"]:
            results["summary"]["catalog_ws_mismatches"] += 1
        if asset_result["diff_ws_vs_md"]:
            results["summary"]["ws_md_mismatches"] += 1
        if asset_result["diff_catalog_vs_md"]:
            results["summary"]["catalog_md_mismatches"] += 1
        
        results["assets"][asset] = asset_result
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_catalog_ws_md_consistency())
    print(json.dumps(result, indent=2))
