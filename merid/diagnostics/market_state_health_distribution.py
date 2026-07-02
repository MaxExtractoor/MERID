"""
Market state age distribution probe.

This diagnostic checks how many markets across the store have stale or
never-initialized orderbooks, providing a histogram of market data health.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import defaultdict
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


async def check_market_state_health_distribution() -> Dict[str, Any]:
    """
    Check market state health distribution across all markets.
    
    Returns:
        Dict with diagnostic results including:
        - Per-asset market counts and health distribution
        - Histogram of MD age buckets
        - Overall statistics
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get market state store (singleton from running server)
    state_store = get_kalshi_market_state_store()
    all_md_states = state_store.get_all()
    
    results = {
        "timestamp": now_utc.isoformat(),
        "total_markets": len(all_md_states),
        "assets": {},
        "overall_histogram": {
            "total_markets": 0,
            "book_init_false": 0,
            "md_age_0_30s": 0,
            "md_age_30_60s": 0,
            "md_age_60_300s": 0,
            "md_age_gt_300s": 0,
            "md_age_unknown": 0
        }
    }
    
    # Group by asset
    asset_markets = defaultdict(list)
    for ticker, state in all_md_states.items():
        # Determine asset from ticker
        asset = None
        for a in ACTIVE_CRYPTO_ASSETS:
            if a.upper() in ticker:
                asset = a
                break
        if asset:
            asset_markets[asset].append((ticker, state))
    
    # Analyze each asset
    for asset in ACTIVE_CRYPTO_ASSETS:
        asset_result = {
            "total_markets": 0,
            "book_init_false": 0,
            "md_age_0_30s": 0,
            "md_age_30_60s": 0,
            "md_age_60_300s": 0,
            "md_age_gt_300s": 0,
            "md_age_unknown": 0,
            "markets": []
        }
        
        markets = asset_markets.get(asset, [])
        for ticker, state in markets:
            asset_result["total_markets"] += 1
            results["overall_histogram"]["total_markets"] += 1
            
            # Get book initialization status
            book_init = state.book_initialized if hasattr(state, 'book_initialized') else False
            if not book_init:
                asset_result["book_init_false"] += 1
                results["overall_histogram"]["book_init_false"] += 1
            
            # Get last update time
            last_update = None
            if hasattr(state, 'last_book_update_ts') and state.last_book_update_ts:
                last_update = state.last_book_update_ts
            elif hasattr(state, 'last_update_ts') and state.last_update_ts:
                last_update = state.last_update_ts
            
            md_age = None
            if last_update:
                # last_update_ts uses time.monotonic(), so calculate age as time.monotonic() - last_update
                md_age = time.monotonic() - last_update
            
            # Categorize by age
            if md_age is None:
                asset_result["md_age_unknown"] += 1
                results["overall_histogram"]["md_age_unknown"] += 1
            elif md_age <= 30:
                asset_result["md_age_0_30s"] += 1
                results["overall_histogram"]["md_age_0_30s"] += 1
            elif md_age <= 60:
                asset_result["md_age_30_60s"] += 1
                results["overall_histogram"]["md_age_30_60s"] += 1
            elif md_age <= 300:
                asset_result["md_age_60_300s"] += 1
                results["overall_histogram"]["md_age_60_300s"] += 1
            else:
                asset_result["md_age_gt_300s"] += 1
                results["overall_histogram"]["md_age_gt_300s"] += 1
            
            # Add market detail
            asset_result["markets"].append({
                "market_id": ticker,
                "book_initialized": book_init,
                "yes_bid": state.yes_bid if hasattr(state, 'yes_bid') else None,
                "yes_ask": state.yes_ask if hasattr(state, 'yes_ask') else None,
                "last_update_ts": last_update,
                "md_age_seconds": md_age
            })
        
        results["assets"][asset] = asset_result
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_market_state_health_distribution())
    print(json.dumps(result, indent=2))
