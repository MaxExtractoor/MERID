#!/usr/bin/env python3
"""
Check market state population from the running server.
This script checks if WebSocket data is actually flowing into the market state store.
"""

import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def check_market_state_population():
    """Check market state population from running server."""
    print("="*80)
    print("MARKET STATE POPULATION CHECK")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc)}")
    print()
    
    # Get market state store (singleton from running server)
    state_store = get_kalshi_market_state_store()
    
    # Get all tracked tickers
    all_tickers = state_store.tickers()
    print(f"Total tickers in market state store: {len(all_tickers)}")
    print(f"Tickers: {all_tickers}")
    print()
    
    # Check each ticker's state
    results = {}
    for ticker in all_tickers:
        state = state_store.get_all().get(ticker)
        if not state:
            results[ticker] = {"status": "NO_STATE"}
            print(f"{ticker}: ❌ No state object")
            continue
        
        # Check if orderbook is populated
        has_yes_bid = state.yes_bid is not None and state.yes_bid > 0
        has_yes_ask = state.yes_ask is not None and state.yes_ask > 0
        has_no_bid = state.no_bid is not None and state.no_bid > 0
        has_no_ask = state.no_ask is not None and state.no_ask > 0
        book_initialized = state.book_initialized
        
        # Check last update times
        last_book_update = state.last_book_update_ts if hasattr(state, 'last_book_update_ts') else None
        last_trade_update = state.last_trade_ts if hasattr(state, 'last_trade_ts') else None
        
        if book_initialized and (has_yes_bid or has_no_bid):
            results[ticker] = {
                "status": "POPULATED",
                "yes_bid": state.yes_bid,
                "yes_ask": state.yes_ask,
                "no_bid": state.no_bid,
                "no_ask": state.no_ask,
                "last_book_update": last_book_update,
                "last_trade_update": last_trade_update
            }
            print(f"{ticker}: ✅ Orderbook populated")
            print(f"  YES: bid={state.yes_bid}, ask={state.yes_ask}")
            print(f"  NO:  bid={state.no_bid}, ask={state.no_ask}")
            if last_book_update:
                age = time.time() - last_book_update
                print(f"  Last book update: {age:.1f}s ago")
            if last_trade_update:
                age = time.time() - last_trade_update
                print(f"  Last trade: {age:.1f}s ago")
        else:
            results[ticker] = {
                "status": "NOT_POPULATED",
                "yes_bid": state.yes_bid,
                "yes_ask": state.yes_ask,
                "no_bid": state.no_bid,
                "no_ask": state.no_ask,
                "book_initialized": book_initialized
            }
            print(f"{ticker}: ❌ Orderbook not populated")
            print(f"  YES: bid={state.yes_bid}, ask={state.yes_ask}")
            print(f"  NO:  bid={state.no_bid}, ask={state.no_ask}")
            print(f"  Book initialized: {book_initialized}")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    populated = sum(1 for r in results.values() if r["status"] == "POPULATED")
    not_populated = sum(1 for r in results.values() if r["status"] == "NOT_POPULATED")
    no_state = sum(1 for r in results.values() if r["status"] == "NO_STATE")
    
    print(f"Populated with orderbook data: {populated}/{len(all_tickers)}")
    print(f"Not populated: {not_populated}/{len(all_tickers)}")
    print(f"No state object: {no_state}/{len(all_tickers)}")
    
    return results


if __name__ == "__main__":
    check_market_state_population()
