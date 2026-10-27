#!/usr/bin/env python3
"""Diagnose position deadlock - why exits aren't triggering."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.event_venues.kalshi.position_cache import get_position_cache
from merid.position_management.position_monitor import get_position_monitor


async def main():
    print("=" * 80)
    print("POSITION DEADLOCK DIAGNOSTIC")
    print("=" * 80)
    
    # Check position cache
    print("\n1. POSITION CACHE STATE:")
    print("-" * 80)
    cache = get_position_cache()
    positions = cache.get_all_positions(validate_freshness=False)
    
    print(f"Total positions in cache: {len(positions)}")
    for market_id, pos in positions.items():
        print(f"\n  Market: {market_id}")
        print(f"    Contracts: {pos.contracts}")
        print(f"    Side: {pos.side}")
        print(f"    Thesis Side: {pos.thesis_side}")
        print(f"    Avg Price: {pos.avg_price_cents}")
        print(f"    Entry Price State: {pos.entry_price_state}")
        print(f"    Notional: ${pos.notional_usd}")
        print(f"    Unrealized PnL: ${pos.unrealized_pnl_usd}")
        print(f"    TP Price: {pos.take_profit_price_cents}")
        print(f"    SL Price: {pos.stop_loss_price_cents}")
        print(f"    Last Updated: {pos.last_updated}")
    
    # Check position monitor
    print("\n2. POSITION MONITOR STATE:")
    print("-" * 80)
    try:
        monitor = get_position_monitor()
        print(f"PositionMonitor exists: {monitor is not None}")
        if monitor:
            print(f"Running: {monitor._running}")
            print(f"Open positions: {len(monitor._open_positions)}")
            for pos_id, pos in monitor._open_positions.items():
                print(f"\n  Position ID: {pos_id}")
                print(f"    Market: {pos.market_id}")
                print(f"    Size: {pos.size}")
                print(f"    Side: {pos.side}")
                print(f"    Entry Price: {pos.avg_entry_price_cents}")
                print(f"    Current Price: {pos.current_price_cents}")
                print(f"    Unrealized PnL: {pos.unrealized_pnl_cents}c")
                print(f"    R-Multiple: {pos.r_multiple}")
                print(f"    TP Price: {pos.take_profit_price_cents}")
                print(f"    SL Price: {pos.stop_loss_price_cents}")
                print(f"    Exit Triggered: {pos.exit_triggered}")
                print(f"    Exit Reason: {pos.exit_reason}")
    except Exception as e:
        print(f"Error getting PositionMonitor: {e}")
    
    # Check exit conditions
    print("\n3. EXIT CONDITION CHECK:")
    print("-" * 80)
    if monitor and monitor._open_positions:
        for pos_id, pos in monitor._open_positions.items():
            print(f"\n  Position: {pos_id[:8]}")
            print(f"    Market: {pos.market_id}")
            print(f"    Current Price: {pos.current_price_cents}c")
            print(f"    Entry Price: {pos.avg_entry_price_cents}c")
            print(f"    PnL: {pos.unrealized_pnl_cents}c")
            print(f"    R-Multiple: {pos.r_multiple}")
            print(f"    Exit Triggered: {pos.exit_triggered}")
            print(f"    Exit Reason: {pos.exit_reason}")
            
            # Check if should trigger 99c exit
            if pos.should_trigger_auto_exit_99c(pos.current_price_cents):
                print(f"    ⚠️  SHOULD TRIGGER 99C EXIT")
            else:
                print(f"    ✓  No 99c exit trigger")
            
            # Check TP
            if pos.take_profit_price_cents:
                if pos.side.value == "yes" and pos.current_price_cents >= pos.take_profit_price_cents:
                    print(f"    ⚠️  SHOULD TRIGGER TP EXIT")
                elif pos.side.value == "no" and pos.current_price_cents <= pos.take_profit_price_cents:
                    print(f"    ⚠️  SHOULD TRIGGER TP EXIT")
                else:
                    print(f"    ✓  No TP trigger")
            
            # Check SL
            if pos.stop_loss_price_cents:
                if pos.side.value == "yes" and pos.current_price_cents <= pos.stop_loss_price_cents:
                    print(f"    ⚠️  SHOULD TRIGGER SL EXIT")
                elif pos.side.value == "no" and pos.current_price_cents >= pos.stop_loss_price_cents:
                    print(f"    ⚠️  SHOULD TRIGGER SL EXIT")
                else:
                    print(f"    ✓  No SL trigger")


if __name__ == "__main__":
    asyncio.run(main())
