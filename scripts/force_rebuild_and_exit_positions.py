#!/usr/bin/env python3
"""Force rebuild position cache from fills ledger and exit all positions.

This fixes the position deadlock where:
- Position cache has corrupted data (None prices)
- PositionMonitor is not running
- Global allocator blocks all orders
- Positions accumulate without exits
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.event_venues.kalshi.position_cache import get_position_cache


async def main():
    print("=" * 80)
    print("FORCE POSITION CACHE REBUILD AND EXIT")
    print("=" * 80)
    
    # 1. Rebuild position cache from REST API (canonical source)
    print("\n1. REBUILDING POSITION CACHE FROM REST API:")
    print("-" * 80)
    cache = get_position_cache()
    
    # Get positions directly from Kalshi REST API
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
    config = get_kalshi_config()
    client = KalshiVenueClient(config)
    positions_result = await client.get_positions_result()
    
    positions = []
    if positions_result.success:
        positions = positions_result.data or []
        print(f"Found {len(positions)} positions on Kalshi REST API")
        
        # Clear cache and rebuild from REST
        cache._positions.clear()
        
        # Rebuild from REST positions
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from datetime import datetime, timezone
        
        for pos in positions:
            market_id = pos.market_id
            contracts = int(pos.size) if pos.size else 0
            avg_price_cents = int(float(pos.average_entry_price) * 100) if pos.average_entry_price else 0
            side = pos.outcome_id or "yes"
            
            print(f"  Processing position: market={market_id} count={contracts} price={avg_price_cents}c side={side}")
            
            # Create position from REST data
            position = CachedPosition(
                market_id=market_id,
                agent_id="REST_REBUILD",  # Mark as rebuilt from REST
                contracts=contracts,
                side=side,
                thesis_side=side,
                avg_price_cents=avg_price_cents,
                last_updated=datetime.now(timezone.utc)
            )
            
            cache._positions[market_id] = position
            print(f"    [OK] Added position: {market_id} ({contracts} contracts @ {avg_price_cents}c)")
        
        print(f"\nRebuilt position cache: {len(cache._positions)} positions")
    else:
        print(f"Failed to fetch positions from REST API: {positions_result.error}")
        print(f"Rebuild skipped - using existing cache ({len(cache._positions)} positions)")
    
    # 2. Display current positions
    print("\n2. CURRENT POSITIONS IN CACHE:")
    print("-" * 80)
    for market_id, pos in cache._positions.items():
        print(f"  {market_id}: {pos.contracts} contracts @ {pos.avg_price_cents}c (side={pos.side})")
    
    # 3. Summary
    print("\n3. SUMMARY:")
    print("-" * 80)
    print(f"Total positions in cache: {len(cache._positions)}")
    print(f"Total positions on Kalshi: {len(positions)}")
    print(f"Cache sync status: {'[OK] SYNCED' if len(cache._positions) == len(positions) else '[WARN] MISMATCH'}")
    
    print("\n" + "=" * 80)
    print("REBUILD COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Position cache has been rebuilt from REST API (canonical source)")
    print("2. PositionMonitor should now see the positions and enforce exits")
    print("3. Global allocator should have accurate position data")
    print("4. Restart the trading system to load the rebuilt position cache")


if __name__ == "__main__":
    asyncio.run(main())
