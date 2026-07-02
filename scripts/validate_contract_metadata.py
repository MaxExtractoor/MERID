#!/usr/bin/env python3
"""
Validate Kalshi contract metadata → ContractState mapping.

This script dumps market metadata for a sample of markets per asset and
cross-checks against how ContractState is populated.

Usage:
    python scripts/validate_contract_metadata.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Dict, List

# Add merid to path
sys.path.insert(0, 'c:\\Dev\\MERID')

from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.client import KalshiClient


async def dump_market_metadata(catalog: KalshiMarketCatalog) -> List[Dict]:
    """
    Dump market metadata for a sample of markets per asset.
    
    Returns:
        List of market metadata dictionaries
    """
    print("=" * 80)
    print("MARKET METADATA DUMP")
    print("=" * 80)
    
    all_markets = catalog.get_all_markets()
    series_tickers = kalshi_agent_grid_catalog_series_tickers()
    
    metadata_list = []
    
    for series in series_tickers:
        series_markets = [m for m in all_markets if m.series_ticker == series]
        
        if not series_markets:
            print(f"\n{series}: No markets found")
            continue
        
        # Sample first 2 markets per series
        sample_markets = series_markets[:2]
        
        print(f"\n{series} ({len(series_markets)} total, sampling {len(sample_markets)})")
        
        for market in sample_markets:
            metadata = {
                "market_id": market.market_id,
                "series_ticker": market.series_ticker,
                "strike": getattr(market, 'strike_price', 'N/A'),
                "close_time": getattr(market, 'close_time', 'N/A'),
                "title": getattr(market, 'title', 'N/A'),
                "subtitle": getattr(market, 'subtitle', 'N/A'),
                "category": getattr(market, 'category', 'N/A'),
            }
            
            metadata_list.append(metadata)
            
            print(f"\n  Market: {market.market_id}")
            print(f"    Series ticker: {market.series_ticker}")
            print(f"    Strike: {metadata['strike']}")
            print(f"    Close time: {metadata['close_time']}")
            print(f"    Title: {metadata['title']}")
            print(f"    Subtitle: {metadata['subtitle']}")
            print(f"    Category: {metadata['category']}")
    
    return metadata_list


def validate_contractstate_mapping(metadata_list: List[Dict]):
    """
    Validate ContractState mapping against market metadata.
    
    Checks for:
    - Strike extraction correctness
    - Time to expiry calculation
    - Side semantics (Up/Down, Yes/No)
    """
    print("\n" + "=" * 80)
    print("CONTRACTSTATE MAPPING VALIDATION")
    print("=" * 80)
    
    for metadata in metadata_list:
        market_id = metadata["market_id"]
        series_ticker = metadata["series_ticker"]
        strike = metadata["strike"]
        close_time = metadata["close_time"]
        title = metadata["title"]
        subtitle = metadata["subtitle"]
        
        print(f"\nValidating: {market_id}")
        
        # Check 1: Strike extraction
        # Current implementation uses spot_price as placeholder
        # This is a PRODUCTION BUG TARGET
        print(f"  [STRIKE] Metadata strike: {strike}")
        print(f"  [STRIKE] Current implementation: uses spot_price as placeholder")
        print(f"  [STRIKE] BUG: Need to extract actual strike from market metadata")
        
        # Check 2: Time to expiry calculation
        if close_time:
            now = datetime.now(timezone.utc)
            time_to_expiry = (close_time - now).total_seconds()
            print(f"  [TIME] Close time: {close_time}")
            print(f"  [TIME] Current time: {now}")
            print(f"  [TIME] Time to expiry: {time_to_expiry:.1f}s")
            
            if time_to_expiry < 0:
                print(f"  [TIME] BUG: Negative time_to_expiry - clock mismatch")
            elif time_to_expiry > 900:
                print(f"  [TIME] WARN: time_to_expiry > 900s - possible clock mismatch")
        
        # Check 3: Side semantics
        # Kalshi uses "Up"/"Down" in title, but we model as "yes"/"no"
        # Need to verify mapping is correct
        print(f"  [SIDE] Title: {title}")
        print(f"  [SIDE] Subtitle: {subtitle}")
        
        if "Up" in title:
            print(f"  [SIDE] Kalshi: Up contract")
            print(f"  [SIDE] Our model: side='yes' (should win if spot > strike)")
            print(f"  [SIDE] BUG: Verify this mapping is correct for all assets")
        elif "Down" in title:
            print(f"  [SIDE] Kalshi: Down contract")
            print(f"  [SIDE] Our model: side='no' (should win if spot < strike)")
            print(f"  [SIDE] BUG: Verify this mapping is correct for all assets")
        else:
            print(f"  [SIDE] WARN: Cannot determine side from title")
        
        # Check 4: Asset extraction
        asset = series_ticker.replace("KX", "").replace("15M", "")
        print(f"  [ASSET] Series ticker: {series_ticker}")
        print(f"  [ASSET] Extracted asset: {asset}")
        print(f"  [ASSET] BUG: Verify asset extraction is correct for all series")


async def main():
    """Main validation routine."""
    print("\n" + "=" * 80)
    print("KALSHI CONTRACT METADATA VALIDATION")
    print("=" * 80)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    
    try:
        # Initialize catalog and client
        client = KalshiClient()
        catalog = KalshiMarketCatalog(client)
        
        # Refresh catalog
        print(f"\nRefreshing catalog...")
        await catalog.refresh()
        
        # Dump market metadata
        metadata_list = await dump_market_metadata(catalog)
        
        # Validate ContractState mapping
        validate_contractstate_mapping(metadata_list)
        
        # Summary
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"\nTotal markets sampled: {len(metadata_list)}")
        print("\nCRITICAL BUGS IDENTIFIED:")
        print("  1. Strike extraction: Using spot_price as placeholder (NEEDS FIX)")
        print("  2. Side semantics: Need to verify Up/Down → yes/no mapping")
        print("  3. Time to expiry: Clock mismatch detection in place")
        print("  4. Asset extraction: Need to verify for all series tickers")
        
        print("\nRECOMMENDED ACTIONS:")
        print("  1. Extract actual strike from market metadata (not spot_price)")
        print("  2. Verify Up/Down → yes/no mapping for all assets")
        print("  3. Test time_to_expiry calculation with known markets")
        print("  4. Add unit tests for ContractState creation")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ VALIDATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
