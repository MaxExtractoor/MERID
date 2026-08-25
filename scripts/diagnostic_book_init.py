#!/usr/bin/env python3
"""
Diagnostic script to check book_initialized state for all Kalshi markets.
This helps diagnose why orders are being rejected with BOOK_NOT_INITIALIZED.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

logger = get_logger(__name__)

def main():
    store = get_kalshi_market_state_store()
    
    # Get all tickers in the store
    all_states = store._states if hasattr(store, '_states') else {}
    
    logger.info("=" * 80)
    logger.info("BOOK INITIALIZATION DIAGNOSTIC")
    logger.info("=" * 80)
    logger.info(f"Total markets in store: {len(all_states)}")
    
    # Group by asset (BTC, ETH, SOL, XRP, DOGE)
    assets = {}
    for ticker, state in all_states.items():
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if asset in ticker.upper():
                if asset not in assets:
                    assets[asset] = []
                assets[asset].append((ticker, state))
                break
    
    # Check each asset
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        logger.info(f"\n{'=' * 80}")
        logger.info(f"ASSET: {asset}")
        logger.info(f"{'=' * 80}")
        
        if asset not in assets or not assets[asset]:
            logger.warning(f"No markets found for {asset}")
            continue
        
        initialized_count = 0
        total_count = len(assets[asset])
        
        for ticker, state in assets[asset]:
            logger.info(f"\nTicker: {ticker}")
            logger.info(f"  book_initialized: {state.book_initialized}")
            logger.info(f"  executable: {state.executable}")
            logger.info(f"  data_source: {state.data_source}")
            logger.info(f"  best_bid_cents: {state.best_bid_cents}")
            logger.info(f"  best_ask_cents: {state.best_ask_cents}")
            logger.info(f"  mid_cents: {state.mid_cents}")
            logger.info(f"  last_book_update_ts: {state.last_book_update_ts}")
            logger.info(f"  last_rest_update_ts: {state.last_rest_update_ts}")
            logger.info(f"  status: {state.status}")
            
            if state.book_initialized:
                initialized_count += 1
        
        logger.info(f"\n{asset} Summary: {initialized_count}/{total_count} markets initialized")
        
        if initialized_count < total_count:
            logger.warning(f"⚠️  {asset} has {total_count - initialized_count} uninitialized markets!")
        else:
            logger.info(f"✓ All {asset} markets initialized")
    
    # Overall summary
    logger.info(f"\n{'=' * 80}")
    logger.info("OVERALL SUMMARY")
    logger.info(f"{'=' * 80}")
    
    total_markets = sum(len(assets.get(asset, [])) for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    total_initialized = sum(
        sum(1 for _, state in assets.get(asset, []) if state.book_initialized)
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    )
    
    logger.info(f"Total 15m crypto markets: {total_markets}")
    logger.info(f"Initialized markets: {total_initialized}")
    logger.info(f"Uninitialized markets: {total_markets - total_initialized}")
    
    if total_initialized < total_markets:
        logger.error(f"❌ CRITICAL: {total_markets - total_initialized} markets are NOT initialized!")
        logger.error("This will cause ORDER-BLOCKED with reason=BOOK_NOT_INITIALIZED")
        return 1
    else:
        logger.info("✓ All markets initialized - book initialization is NOT the issue")
        return 0

if __name__ == "__main__":
    sys.exit(main())
