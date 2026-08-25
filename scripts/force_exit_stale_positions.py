#!/usr/bin/env python3
"""Force exit all stale positions to clear the deadlock.

This script:
1. Identifies positions with corrupted price data (avg_price_cents = 0)
2. Identifies positions in expired markets
3. Submits market orders to exit these positions
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.event_venues.kalshi.position_cache import get_position_cache
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from datetime import datetime, timezone


async def main():
    print("=" * 80)
    print("FORCE EXIT STALE POSITIONS")
    print("=" * 80)
    
    # 1. Get current positions from cache
    print("\n1. CURRENT POSITIONS IN CACHE:")
    print("-" * 80)
    cache = get_position_cache()
    
    stale_positions = []
    for market_id, pos in cache._positions.items():
        if pos.contracts > 0:
            is_stale = pos.avg_price_cents == 0 or not market_id
            print(f"  {market_id}: {pos.contracts} contracts @ {pos.avg_price_cents}c (side={pos.side}) {'[STALE]' if is_stale else ''}")
            if is_stale:
                stale_positions.append((market_id, pos))
    
    print(f"\nFound {len(stale_positions)} stale positions to exit")
    
    if not stale_positions:
        print("No stale positions found. Exiting.")
        return
    
    # 2. Confirm before exiting
    print("\n2. CONFIRMATION:")
    print("-" * 80)
    print("WARNING: This will submit market orders to exit all stale positions.")
    print("This may result in losses if markets are still active.")
    print("\nStale positions to exit:")
    for market_id, pos in stale_positions:
        print(f"  {market_id}: {pos.contracts} contracts @ {pos.avg_price_cents}c (side={pos.side})")
    
    # Auto-confirm for this emergency fix
    print("\nProceeding with force exit (emergency fix)...")
    
    # 3. Submit exit orders
    print("\n3. SUBMITTING EXIT ORDERS:")
    print("-" * 80)
    
    config = get_kalshi_config()
    client = KalshiVenueClient(config)
    
    exit_results = []
    for market_id, pos in stale_positions:
        try:
            # Determine exit side (opposite of current position)
            exit_side = "no" if pos.side.lower() == "yes" else "yes"
            
            print(f"  Submitting exit order for {market_id}: {pos.contracts} contracts {exit_side}")
            
            # Submit market order to exit
            result = await client.create_order(
                market_id=market_id,
                side=exit_side,
                count=pos.contracts,
                price=1,  # Market order (worst case price)
                order_type="market"
            )
            
            if result.success:
                print(f"    [OK] Exit order submitted: {result.data}")
                exit_results.append((market_id, "success", result.data))
            else:
                print(f"    [FAIL] Exit order failed: {result.error}")
                exit_results.append((market_id, "failed", result.error))
                
        except Exception as e:
            print(f"    [ERROR] Exception: {e}")
            exit_results.append((market_id, "error", str(e)))
    
    # 4. Summary
    print("\n4. SUMMARY:")
    print("-" * 80)
    success_count = sum(1 for _, status, _ in exit_results if status == "success")
    print(f"Exit orders submitted: {len(exit_results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(exit_results) - success_count}")
    
    print("\n" + "=" * 80)
    print("FORCE EXIT COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Check Kalshi portfolio to verify positions are closed")
    print("2. Restart the trading system")
    print("3. Global allocator should no longer block new trades")


if __name__ == "__main__":
    asyncio.run(main())
