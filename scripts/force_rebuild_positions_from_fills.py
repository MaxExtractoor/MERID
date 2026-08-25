#!/usr/bin/env python3
"""Force rebuild position cache from fills ledger to recover thesis_side and entry prices.

This script fixes the issue where positions synced from REST API have:
- avg_price_cents=None (invalid entry price)
- thesis_side='unknown' (cannot determine YES/NO side)

The fills ledger is the canonical source of truth for executed trades and contains
the correct side and price information from fill events.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def main():
    """Force rebuild position cache from fills ledger."""
    print("[FORCE-REBUILD] Starting position cache rebuild from fills ledger...")
    
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        cache = get_position_cache()
        ledger = get_fills_ledger()
        
        # Log current position state before rebuild
        print(f"\n[FORCE-REBUILD] Current position cache state:")
        positions = cache.get_all_positions()
        for market_id, pos in positions.items():
            print(f"  - {market_id}: contracts={pos.contracts} avg_price={pos.avg_price_cents} thesis_side={pos.thesis_side}")
        
        # Test REST sync with calculated entry prices
        print(f"\n[FORCE-REBUILD] Testing REST sync with calculated entry prices...")
        # Simulate REST API response with total_traded_dollars and position_fp
        # This tests the new calculation logic
        test_rest_positions = []
        if positions:
            for market_id, pos in positions.items():
                if pos.contracts > 0:
                    # Create a mock REST position with total_traded_dollars and position_fp
                    # If we have avg_price_cents, reverse-calculate total_traded_dollars
                    if pos.avg_price_cents:
                        total_traded = (pos.avg_price_cents / 100) * pos.contracts
                        test_rest_positions.append({
                            "market_id": market_id,
                            "position_fp": str(pos.contracts),
                            "total_traded_dollars": str(total_traded),
                            "side": pos.side or "yes",
                            "contracts": pos.contracts
                        })
                        print(f"  - Mock REST data for {market_id}: total_traded=${total_traded:.2f}, position_fp={pos.contracts}")
        
        if test_rest_positions:
            print(f"[FORCE-REBUILD] Syncing from mock REST data ({len(test_rest_positions)} positions)...")
            await cache.sync_from_rest(test_rest_positions, force=True)
            
            # Log position state after REST sync
            print(f"\n[FORCE-REBUILD] Position cache state after REST sync:")
            positions = cache.get_all_positions()
            for market_id, pos in positions.items():
                print(f"  - {market_id}: contracts={pos.contracts} avg_price={pos.avg_price_cents} thesis_side={pos.thesis_side} entry_state={pos.entry_price_state}")
        else:
            print(f"[FORCE-REBUILD] No positions to test REST sync")
        
        # Force health check and auto-fix invalid positions
        print(f"\n[FORCE-REBUILD] Triggering health check and auto-fix...")
        fixed_count = cache.force_health_check_and_fix()
        print(f"[FORCE-REBUILD] Health check complete. Valid positions: {fixed_count}")
        
        # Log position state after fix
        print(f"\n[FORCE-REBUILD] Position cache state after auto-fix:")
        positions = cache.get_all_positions()
        for market_id, pos in positions.items():
            print(f"  - {market_id}: contracts={pos.contracts} avg_price={pos.avg_price_cents} thesis_side={pos.thesis_side}")
        
        print(f"\n[FORCE-REBUILD] Auto-fix complete. {len(positions)} positions in cache.")
        
        # Trigger sync with PositionMonitor to ensure positions are monitored
        print(f"\n[FORCE-REBUILD] Syncing with PositionMonitor...")
        try:
            from merid.position_management.position_monitor import get_position_monitor
            monitor = get_position_monitor()
            
            # Add rebuilt positions to monitor
            for market_id, pos in positions.items():
                if pos.contracts > 0 and pos.avg_price_cents is not None and pos.thesis_side != 'unknown':
                    from merid.position_management.position import Position, PositionSide, TrailingType
                    from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker
                    
                    expiry_ts = parse_expiry_from_ticker(market_id)
                    side = PositionSide.YES if pos.thesis_side == 'yes' else PositionSide.NO
                    
                    position = Position(
                        position_id=market_id,
                        market_id=market_id,
                        side=side,
                        contracts=pos.contracts,
                        avg_entry_price_cents=pos.avg_price_cents,
                        expiry_timestamp=expiry_ts,
                        trailing_type=TrailingType.NONE,
                    )
                    
                    monitor.add_position(position)
                    print(f"  - Added {market_id} to PositionMonitor")
            
            print(f"[FORCE-REBUILD] PositionMonitor sync complete.")
        except Exception as monitor_err:
            print(f"[FORCE-REBUILD] Warning: Failed to sync with PositionMonitor: {monitor_err}")
        
        return 0
        
    except Exception as e:
        print(f"[FORCE-REBUILD] ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
