#!/usr/bin/env python3
"""
End-to-end one market trace for each asset.

This script picks one live 15m market per asset and traces it through:
Series/market discovery → ContractState creation → UnifiedEdgeComputer inputs → 
[SIGNAL] log → [RISK-DECISION] → [ORDER-SUBMIT] → [FILL] / no-fill

Usage:
    python scripts/trace_one_market.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Add merid to path
sys.path.insert(0, 'c:\\Dev\\MERID')

from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.client import KalshiClient


async def select_one_market_per_asset(catalog: KalshiMarketCatalog) -> Dict[str, Dict]:
    """
    Select one live 15m market per asset for tracing.
    
    Returns:
        Dict mapping asset to market metadata
    """
    print("=" * 80)
    print("SELECTING ONE MARKET PER ASSET FOR TRACING")
    print("=" * 80)
    
    all_markets = catalog.get_all_markets()
    series_tickers = kalshi_agent_grid_catalog_series_tickers()
    
    selected_markets = {}
    
    for series in series_tickers:
        asset = series.replace("KX", "").replace("15M", "")
        series_markets = [m for m in all_markets if m.series_ticker == series]
        
        if not series_markets:
            print(f"\n{asset}: No markets found")
            continue
        
        # Select the first market with a close time in the future
        now = datetime.now(timezone.utc)
        future_markets = [
            m for m in series_markets
            if hasattr(m, 'close_time') and m.close_time and m.close_time > now
        ]
        
        if future_markets:
            selected = future_markets[0]
        else:
            # Fallback to first market
            selected = series_markets[0]
        
        selected_markets[asset] = {
            "market_id": selected.market_id,
            "series_ticker": selected.series_ticker,
            "strike": getattr(selected, 'strike_price', 'N/A'),
            "close_time": getattr(selected, 'close_time', 'N/A'),
            "title": getattr(selected, 'title', 'N/A'),
            "subtitle": getattr(selected, 'subtitle', 'N/A'),
            "category": getattr(selected, 'category', 'N/A'),
        }
        
        print(f"\n{asset}:")
        print(f"  Market ID: {selected.market_id}")
        print(f"  Series ticker: {selected.series_ticker}")
        print(f"  Strike: {selected_markets[asset]['strike']}")
        print(f"  Close time: {selected_markets[asset]['close_time']}")
        print(f"  Title: {selected_markets[asset]['title']}")
    
    return selected_markets


async def trace_market_pipeline(selected_markets: Dict[str, Dict]):
    """
    Trace selected markets through the pipeline.
    
    This simulates the pipeline without actually executing trades.
    """
    print("\n" + "=" * 80)
    print("TRACING MARKET PIPELINE")
    print("=" * 80)
    
    for asset, market_info in selected_markets.items():
        print(f"\n{'=' * 80}")
        print(f"TRACING: {asset}")
        print(f"{'=' * 80}")
        
        market_id = market_info["market_id"]
        series_ticker = market_info["series_ticker"]
        strike = market_info["strike"]
        close_time = market_info["close_time"]
        title = market_info["title"]
        
        # Step 1: Series/market discovery
        print(f"\n[STEP 1] SERIES/MARKET DISCOVERY")
        print(f"  Market ID: {market_id}")
        print(f"  Series ticker: {series_ticker}")
        print(f"  Status: ✅ Found in catalog")
        
        # Step 2: ContractState creation
        print(f"\n[STEP 2] CONTRACTSTATE CREATION")
        print(f"  Asset: {asset}")
        print(f"  Strike: {strike}")
        print(f"  Side: {'yes' if 'Up' in title else 'no'}")
        print(f"  BUG: Strike extraction uses spot_price as placeholder")
        print(f"  BUG: Need to extract actual strike from market metadata")
        
        # Step 3: Time to expiry calculation
        print(f"\n[STEP 3] TIME TO EXPIRY")
        if close_time:
            now = datetime.now(timezone.utc)
            time_to_expiry = (close_time - now).total_seconds()
            print(f"  Close time: {close_time}")
            print(f"  Current time: {now}")
            print(f"  Time to expiry: {time_to_expiry:.1f}s")
            
            if time_to_expiry < 0:
                print(f"  ❌ BUG: Negative time_to_expiry - clock mismatch")
            elif time_to_expiry > 900:
                print(f"  ⚠️  WARN: time_to_expiry > 900s - possible clock mismatch")
            else:
                print(f"  ✅ OK: time_to_expiry in valid range")
        else:
            print(f"  ❌ BUG: No close time available")
        
        # Step 4: UnifiedEdgeComputer inputs
        print(f"\n[STEP 4] UNIFIED EDGE COMPUTER INPUTS")
        print(f"  Spot reference: TODO - need CFB proxy")
        print(f"  Order book snapshot: TODO - need market state")
        print(f"  BUG: Spot reference is composite, not CFB proxy")
        print(f"  BUG: Order book may be None (slippage adjustment disabled)")
        
        # Step 5: Edge computation (simulated)
        print(f"\n[STEP 5] EDGE COMPUTATION (SIMULATED)")
        print(f"  Model win prob: TODO - depends on spot vs strike")
        print(f"  Market implied prob: TODO - depends on contract price")
        print(f"  Raw edge: TODO - q - π")
        print(f"  Risk-adjusted edge: TODO - edge / σ")
        print(f"  Slippage-adjusted edge: TODO - edge - slippage")
        print(f"  BUG: Calibration parameters are placeholders")
        
        # Step 6: Signal generation
        print(f"\n[STEP 6] SIGNAL GENERATION")
        print(f"  [SIGNAL] log: TODO - would log edge, confidence, etc.")
        print(f"  unified_edge_used: true (if MERID_UNIFIED_EDGE_ENABLED=true)")
        print(f"  calibration_version: placeholder (blocked in production)")
        
        # Step 7: Risk decision
        print(f"\n[STEP 7] RISK DECISION")
        print(f"  [RISK-DECISION] log: TODO - would log risk check result")
        print(f"  Per-asset cap: TODO - check against asset cap")
        print(f"  Group cap: TODO - check against correlation group cap")
        
        # Step 8: Order submission
        print(f"\n[STEP 8] ORDER SUBMISSION")
        print(f"  [ORDER-SUBMIT] log: TODO - would log order details")
        print(f"  BUG: Strike extraction affects order price")
        
        # Step 9: Fill / no-fill
        print(f"\n[STEP 9] FILL / NO-FILL")
        print(f"  [FILL] log: TODO - would log fill if executed")
        print(f"  BUG: Poor edge timing may cause no-fill")
        
        print(f"\n{'=' * 80}")
        print(f"TRACE COMPLETE: {asset}")
        print(f"{'=' * 80}")


async def main():
    """Main trace routine."""
    print("\n" + "=" * 80)
    print("END-TO-END ONE MARKET TRACE")
    print("=" * 80)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    
    try:
        # Initialize catalog and client
        client = KalshiClient()
        catalog = KalshiMarketCatalog(client)
        
        # Refresh catalog
        print(f"\nRefreshing catalog...")
        await catalog.refresh()
        
        # Select one market per asset
        selected_markets = await select_one_market_per_asset(catalog)
        
        # Trace pipeline
        await trace_market_pipeline(selected_markets)
        
        # Summary
        print("\n" + "=" * 80)
        print("TRACE SUMMARY")
        print("=" * 80)
        print(f"\nTotal assets traced: {len(selected_markets)}")
        print("\nCRITICAL BUGS IDENTIFIED:")
        print("  1. Strike extraction: Using spot_price as placeholder (NEEDS FIX)")
        print("  2. Spot reference: Composite, not CFB proxy (NEEDS FIX)")
        print("  3. Order book: May be None (slippage adjustment disabled)")
        print("  4. Calibration: Parameters are placeholders (BLOCKED IN PRODUCTION)")
        print("  5. Time to expiry: Clock mismatch detection in place")
        
        print("\nRECOMMENDED ACTIONS:")
        print("  1. Extract actual strike from market metadata")
        print("  2. Implement CFB proxy for spot reference")
        print("  3. Ensure order book is always available")
        print("  4. Fit calibration parameters from historical data")
        print("  5. Test time_to_expiry with known markets")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ TRACE FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
