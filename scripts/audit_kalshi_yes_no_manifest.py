#!/usr/bin/env python3
"""Build canonical YES/NO manifest for Kalshi crypto 15m markets.

This script pulls market data from Kalshi API and creates a truth table
mapping tickers to their YES/NO conditions. This is the foundation for
the wiring audit to ensure all layers agree on what YES/NO mean.

Usage::

    python scripts/audit_kalshi_yes_no_manifest.py --output data/kalshi_yes_no_manifest.json

The manifest includes:
- ticker: Kalshi market ticker
- event_text: Human-readable event description
- strike_price: Strike price if applicable
- yes_condition: What condition makes YES pay out
- no_condition: What condition makes NO pay out
- series_ticker: Series identifier (e.g., KXBTC15M)
- asset: Underlying asset (BTC, ETH, etc.)
- timeframe: Timeframe (15m, 1h, etc.)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports (cross-platform)
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir))

from merid.event_venues.kalshi.client import get_kalshi_client
from merid.event_venues.kalshi.market_filter import (
    extract_asset_from_ticker,
    _normalize_timeframe,
)
from utils.logger import get_logger

logger = get_logger("scripts.audit_kalshi_yes_no_manifest")


# Crypto 15m series tickers to audit
CRYPTO_15M_SERIES = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
]


def parse_yes_condition(market_data: Dict[str, Any]) -> str:
    """Extract YES payout condition from market data.
    
    Args:
        market_data: Raw market data from Kalshi API
        
    Returns:
        Human-readable YES condition description
    """
    # Try multiple fields where condition might be stored
    if "title" in market_data:
        title = market_data["title"]
        # Common patterns: "BTC > 100000", "BTC above 100000", etc.
        return title
    
    if "subtitle" in market_data:
        return market_data["subtitle"]
    
    if "market_question" in market_data:
        return market_data["market_question"]
    
    if "question" in market_data:
        return market_data["question"]
    
    # Fallback: construct from ticker
    ticker = market_data.get("ticker", "UNKNOWN")
    return f"Condition from ticker: {ticker}"


async def build_manifest(
    series_tickers: List[str],
    limit_per_series: int = 10,
) -> List[Dict[str, Any]]:
    """Build YES/NO manifest for given series.
    
    Args:
        series_tickers: List of series tickers to audit
        limit_per_series: Max markets per series (to avoid API rate limits)
        
    Returns:
        List of market manifest entries
    """
    from merid.event_venues.base import MarketFilter
    
    client = get_kalshi_client()
    if not client:
        logger.error("Kalshi client not available")
        return []

    manifest = []

    try:
        await client.connect()

        for series in series_tickers:
            logger.info(f"Auditing series: {series}")

            # Use list_markets_result with series_ticker filter
            filter_params = MarketFilter(
                search=series,  # This maps to series_ticker in API
                limit=limit_per_series,
                active_only=False,  # Get all markets, not just open
            )
            
            markets_result = await client.list_markets_result(filter_params)
            if not markets_result.success:
                logger.error(f"Failed to fetch markets for series {series}: {markets_result.error}")
                continue

            markets = markets_result.data
            if not markets:
                logger.warning(f"No markets found for series {series}")
                continue

            logger.info(f"Found {len(markets)} markets for {series}")

            for market in markets:
                # EventMarket is a dataclass with market_id, question, description, etc.
                # The ticker is typically in market_id or raw_data
                if hasattr(market, 'market_id'):
                    ticker = market.market_id
                    market_data = {
                        "ticker": market.market_id,
                        "title": getattr(market, 'question', 'N/A'),
                        "subtitle": getattr(market, 'description', ''),
                        "market_id": market.market_id,
                        "close_time": getattr(market, 'end_date', None),
                        "strike_price": None,  # Not in EventMarket base
                    }
                    # Try to get ticker from raw_data if available
                    if market.raw_data and isinstance(market.raw_data, dict):
                        ticker = market.raw_data.get("ticker", market.market_id)
                        market_data["ticker"] = ticker
                        market_data["title"] = market.raw_data.get("title", market.question)
                        market_data["subtitle"] = market.raw_data.get("subtitle", market.description)
                        market_data["strike_price"] = market.raw_data.get("strike_price")
                elif isinstance(market, dict):
                    # Fallback for dict-like objects
                    ticker = market.get("ticker", market.get("market_id"))
                    market_data = market
                else:
                    logger.warning(f"Unknown market type: {type(market)}")
                    continue
                
                if not ticker:
                    continue

                # Extract asset and timeframe
                try:
                    asset = extract_asset_from_ticker(ticker)
                except Exception:
                    asset = "UNKNOWN"
                
                try:
                    timeframe = _normalize_timeframe(ticker)
                except Exception:
                    timeframe = "UNKNOWN"

                # Parse YES condition from title/subtitle
                yes_condition = parse_yes_condition(market_data)

                # Infer NO condition (logical complement)
                no_condition = f"NOT ({yes_condition})"

                # Extract strike price if available
                strike_price = market_data.get("strike_price")

                entry = {
                    "ticker": ticker,
                    "event_text": market_data.get("title", market_data.get("subtitle", "N/A")),
                    "strike_price": strike_price,
                    "yes_condition": yes_condition,
                    "no_condition": no_condition,
                    "series_ticker": series,
                    "asset": asset,
                    "timeframe": timeframe,
                    "market_id": market_data.get("market_id"),
                    "expiry_date": market_data.get("close_time").isoformat() if market_data.get("close_time") else None,
                }

                manifest.append(entry)
                logger.info(f"Added {ticker}: {yes_condition}")

    except Exception as e:
        logger.error(f"Error building manifest: {e}", exc_info=True)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return manifest


async def main():
    parser = argparse.ArgumentParser(
        description="Build canonical YES/NO manifest for Kalshi crypto 15m markets"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="data/kalshi_yes_no_manifest.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max markets per series (default: 10)",
    )
    parser.add_argument(
        "--series",
        nargs="+",
        default=CRYPTO_15M_SERIES,
        help="Series tickers to audit (default: all crypto 15m)",
    )

    args = parser.parse_args()

    logger.info(f"Building YES/NO manifest for series: {args.series}")
    logger.info(f"Limit per series: {args.limit}")

    manifest = await build_manifest(args.series, args.limit)

    if not manifest:
        logger.error("No markets found in manifest")
        sys.exit(1)

    # Add metadata
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series_audited": args.series,
        "total_markets": len(manifest),
        "markets": manifest,
    }

    # Write output
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Wrote manifest to {args.output}")
    logger.info(f"Total markets: {len(manifest)}")

    # Print summary
    print("\n" + "=" * 80)
    print("YES/NO MANIFEST SUMMARY")
    print("=" * 80)
    for entry in manifest[:5]:  # Show first 5
        print(f"\nTicker: {entry['ticker']}")
        print(f"  Asset: {entry['asset']}, Timeframe: {entry['timeframe']}")
        print(f"  YES: {entry['yes_condition']}")
        print(f"  NO:  {entry['no_condition']}")

    if len(manifest) > 5:
        print(f"\n... and {len(manifest) - 5} more markets")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
