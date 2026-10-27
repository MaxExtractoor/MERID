#!/usr/bin/env python3
"""
Direct Kalshi API position checker.

This script bypasses all MERID internals and queries the Kalshi API directly
to verify what positions actually exist on the account. This is for debugging
position sync issues and ensuring the system is tracking positions correctly.
"""

import asyncio
import json
from datetime import datetime, timezone
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config


async def check_positions():
    """Query Kalshi API directly for positions."""
    print("=" * 80)
    print(f"KALSHI API POSITION CHECK - {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    
    try:
        config = get_kalshi_config()
        client = KalshiVenueClient(config)
        
        print(f"\nConnecting to Kalshi API...")
        print(f"Base URL: {config.base_url}")
        print(f"Environment: {config.env}")
        
        await client.connect()
        print("✓ Connected successfully")
        
        print(f"\nFetching positions from /portfolio/positions endpoint...")
        result = await client.get_positions_result()
        
        if result.success:
            positions = result.data
            print(f"✓ API returned {len(positions)} positions")
            
            if positions:
                print(f"\n{'='*80}")
                print("POSITION DETAILS:")
                print(f"{'='*80}")
                
                for i, pos in enumerate(positions, 1):
                    print(f"\nPosition {i}:")
                    print(f"  Market ID: {pos.market_id}")
                    print(f"  Side: {pos.outcome_id}")
                    print(f"  Size: {pos.size}")
                    print(f"  Avg Entry Price: ${pos.average_entry_price}")
                    print(f"  Unrealized PnL: ${pos.unrealized_pnl if pos.unrealized_pnl else 'N/A'}")
                    print(f"  Realized PnL: ${pos.realized_pnl if pos.realized_pnl else 'N/A'}")
                print(f"\n{'='*80}")
            else:
                print("⚠ No positions returned from API")
        else:
            print(f"✗ API call failed: {result.error}")
            
        # Also check balance
        print(f"\nFetching balance...")
        balance_result = await client.get_balance_result()
        if balance_result.success:
            balance = balance_result.data
            print(f"✓ Balance: ${balance.get('USD', 0):.2f} (locked: ${balance.get('locked', 0):.2f})")
        else:
            print(f"✗ Balance fetch failed: {balance_result.error}")
            
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*80}")
    print(f"CHECK COMPLETE - {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(check_positions())
