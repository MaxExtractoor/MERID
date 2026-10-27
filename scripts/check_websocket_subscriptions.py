#!/usr/bin/env python3
"""
Check WebSocket subscription status for Kalshi 15m crypto markets.
This script connects to the running server's WebSocket service to verify
that all critical markets are being subscribed to and receiving data.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


async def check_websocket_subscriptions():
    """Check WebSocket subscription status."""
    print("="*80)
    print("WEBSOCKET SUBSCRIPTION CHECK")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc)}")
    print()
    
    # Get catalog
    catalog = get_market_catalog()
    await catalog.refresh()
    
    # Get market state store (singleton from running server)
    state_store = get_kalshi_market_state_store()
    
    # Get all tracked tickers
    all_tickers = state_store.tickers()
    print(f"Total tickers in market state store: {len(all_tickers)}")
    print(f"Tickers: {all_tickers}")
    print()
    
    # Check each asset
    results = {}
    for asset in ACTIVE_CRYPTO_ASSETS:
        markets = catalog.get_markets_by_asset(asset, timeframe="15m")
        if not markets:
            results[asset] = {"status": "NO_MARKETS", "tickers": []}
            print(f"{asset}: ❌ No markets found")
            continue
        
        asset_tickers = []
        for market in markets:
            market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
            if market_id:
                asset_tickers.append(market_id)
        
        # Check if these tickers are in the state store
        tracked_tickers = [t for t in asset_tickers if t in all_tickers]
        
        if len(tracked_tickers) == len(asset_tickers):
            results[asset] = {"status": "SUBSCRIBED", "tickers": tracked_tickers}
            print(f"{asset}: ✅ All {len(tracked_tickers)} markets subscribed")
            for ticker in tracked_tickers:
                state = state_store.get_all().get(ticker)
                if state:
                    print(f"  - {ticker}: yes_bid={state.yes_bid}, yes_ask={state.yes_ask}, book_init={state.book_initialized}")
                else:
                    print(f"  - {ticker}: ❌ No state")
        else:
            results[asset] = {"status": "PARTIAL", "tickers": tracked_tickers, "missing": len(asset_tickers) - len(tracked_tickers)}
            print(f"{asset}: ⚠️ {len(tracked_tickers)}/{len(asset_tickers)} markets subscribed")
            print(f"  Tracked: {tracked_tickers}")
            print(f"  Missing: {len(asset_tickers) - len(tracked_tickers)}")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    subscribed = sum(1 for r in results.values() if r["status"] == "SUBSCRIBED")
    partial = sum(1 for r in results.values() if r["status"] == "PARTIAL")
    no_markets = sum(1 for r in results.values() if r["status"] == "NO_MARKETS")
    
    print(f"Fully subscribed: {subscribed}/5")
    print(f"Partially subscribed: {partial}/5")
    print(f"No markets: {no_markets}/5")
    
    return results


if __name__ == "__main__":
    asyncio.run(check_websocket_subscriptions())
