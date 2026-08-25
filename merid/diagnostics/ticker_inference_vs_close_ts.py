"""
Ticker inference vs close_ts authority check.

This diagnostic explicitly demonstrates where ticker-based inference diverges
from Kalshi epoch truth (close_ts).
"""

import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def parse_close_time_from_ticker(ticker: str) -> datetime:
    """
    Parse close time from ticker using the canonical YYMONDD-HHMM-ET parser.

    CRITICAL FIX (2026-08-03): delegates to parse_kalshi_15m_window_end_utc.
    The previous hand-rolled parse (DD=first two digits, HHMM=next, UTC,
    current-year assumed) was off by ~26 days and 4-5h vs Kalshi close_ts truth.
    """
    from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_window_end_utc
    return parse_kalshi_15m_window_end_utc(ticker)


def compute_close_time_from_ts(close_ts: int) -> datetime:
    """
    Compute close time from close_ts (Kalshi epoch truth).
    """
    return datetime.fromtimestamp(close_ts, tz=timezone.utc)


async def check_ticker_inference_vs_close_ts() -> Dict[str, Any]:
    """
    Check ticker inference vs close_ts authority.
    
    Returns:
        Dict with diagnostic results including:
        - Per-market comparison of ticker-parsed vs close_ts-based times
        - Delta between the two methods
        - Summary statistics on divergence
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get catalog
    catalog = get_market_catalog()
    await catalog.refresh()
    
    results = {
        "timestamp": now_utc.isoformat(),
        "markets": [],
        "summary": {
            "total_markets": 0,
            "delta_zero": 0,
            "delta_gt_1s": 0,
            "delta_gt_60s": 0,
            "delta_gt_300s": 0,
            "parse_failures": 0,
            "largest_deltas": []
        }
    }
    
    # Get ALL 15m markets for our crypto assets (not just active ones)
    # This allows us to evaluate ticker inference across the full catalog
    all_markets = catalog.get_markets_by_timeframe("15m")
    
    # Filter to our crypto assets
    all_markets = [
        m for m in all_markets 
        if hasattr(m, 'asset') and m.asset in [a.upper() for a in ACTIVE_CRYPTO_ASSETS]
    ]
    
    # DEBUG: Log what we got using logger instead of print
    logger.info(f"[TICKER-INFERENCE] get_markets_by_timeframe returned {len(all_markets)} markets")
    if all_markets:
        sample = all_markets[0]
        logger.info(f"[TICKER-INFERENCE] Sample market type: {type(sample)}")
        logger.info(f"[TICKER-INFERENCE] Sample market has close_ts: {hasattr(sample, 'close_ts')}")
        logger.info(f"[TICKER-INFERENCE] Sample market close_ts value: {getattr(sample, 'close_ts', 'NO_ATTR')}")
        logger.info(f"[TICKER-INFERENCE] Sample market asset: {getattr(sample, 'asset', 'NO_ATTR')}")
    
    logger.info(f"[TICKER-INFERENCE] After filtering to crypto assets: {len(all_markets)} markets")
    
    deltas = []
    
    for market in all_markets:
        market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
        if not market_id:
            continue
        
        close_ts = getattr(market, 'close_ts', None)
        
        # If close_ts is not available, use ticker parsing as fallback
        # This handles cases where Kalshi API doesn't return close_ts
        if not close_ts:
            close_time_from_ticker = parse_close_time_from_ticker(market_id)
            if close_time_from_ticker:
                results["markets"].append({
                    "market_id": market_id,
                    "close_ts": None,
                    "close_time_from_ts": None,
                    "close_time_from_ticker": close_time_from_ticker.isoformat(),
                    "delta_seconds": None,
                    "parse_failed": False,
                    "note": "close_ts not available, using ticker parsing only"
                })
                results["summary"]["total_markets"] += 1
            continue
        
        # Compute close time from close_ts (truth)
        close_time_from_ts = compute_close_time_from_ts(close_ts)
        
        # Compute close time from ticker (inference)
        close_time_from_ticker = parse_close_time_from_ticker(market_id)
        
        if close_time_from_ticker is None:
            results["summary"]["parse_failures"] += 1
            results["markets"].append({
                "market_id": market_id,
                "close_ts": close_ts,
                "close_time_from_ts": close_time_from_ts.isoformat(),
                "close_time_from_ticker": None,
                "delta_seconds": None,
                "parse_failed": True
            })
            continue
        
        # Compute delta
        delta = close_time_from_ts - close_time_from_ticker
        delta_seconds = abs(delta.total_seconds())
        
        deltas.append((market_id, delta_seconds, delta))
        
        # Categorize delta
        if delta_seconds == 0:
            results["summary"]["delta_zero"] += 1
        elif delta_seconds > 1:
            results["summary"]["delta_gt_1s"] += 1
        elif delta_seconds > 60:
            results["summary"]["delta_gt_60s"] += 1
        elif delta_seconds > 300:
            results["summary"]["delta_gt_300s"] += 1
        
        results["markets"].append({
            "market_id": market_id,
            "close_ts": close_ts,
            "close_time_from_ts": close_time_from_ts.isoformat(),
            "close_time_from_ticker": close_time_from_ticker.isoformat(),
            "delta_seconds": delta_seconds,
            "delta_direction": "ts_later" if delta.total_seconds() > 0 else "ticker_later",
            "parse_failed": False
        })
        
        results["summary"]["total_markets"] += 1
    
    # Get largest deltas
    deltas.sort(key=lambda x: x[1], reverse=True)
    results["summary"]["largest_deltas"] = [
        {"market_id": m, "delta_seconds": d, "delta_direction": "ts_later" if delta.total_seconds() > 0 else "ticker_later"}
        for m, d, delta in deltas[:10]
    ]
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_ticker_inference_vs_close_ts())
    print(json.dumps(result, indent=2))
