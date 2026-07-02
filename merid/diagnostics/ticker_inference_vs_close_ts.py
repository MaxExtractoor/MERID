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
    Parse close time from ticker using current parsing function.
    
    This is the existing ticker-based inference logic that may be flawed.
    """
    # Example ticker: KXBTC15M-26JUN141300-00
    # Format: SERIES-DDMONHHMM-SS
    
    try:
        # Extract the date/time part after the dash
        parts = ticker.split('-')
        if len(parts) < 2:
            return None
        
        dt_str = parts[1]  # e.g., "26JUN141300"
        
        # Parse day
        day = int(dt_str[:2])
        
        # Parse month
        month_str = dt_str[2:5].upper()
        month_map = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        month = month_map.get(month_str)
        
        # Parse time (HHMM)
        hour = int(dt_str[5:7])
        minute = int(dt_str[7:9])
        
        # Determine year (current year or next year if date has passed)
        now = datetime.now(timezone.utc)
        year = now.year
        
        # Create the datetime
        close_time = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
        
        # If this date is in the past, assume next year
        if close_time < now:
            close_time = close_time.replace(year=year + 1)
        
        return close_time
    except Exception as e:
        return None


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
