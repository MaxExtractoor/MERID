"""
Verify Kalshi orderbooks directly from API to debug empty orderbook warnings.

This script queries the Kalshi API directly for the 15m crypto markets
to determine if orderbooks are truly empty or if there's a parsing bug.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()


async def main():
    """Query Kalshi API for orderbook data on 15m crypto markets."""
    
    # Import Kalshi client using the same method as ws_bridge
    from merid.event_venues.kalshi import get_kalshi_client
    
    # Initialize Kalshi client
    client = get_kalshi_client()
    
    # Current 15m market IDs from server logs (0015 window - latest from catalog refresh)
    market_ids = [
        "KXBTC15M-26MAY260015-15",
        "KXETH15M-26MAY260015-15",
        "KXSOL15M-26MAY260015-15",
        "KXXRP15M-26MAY260015-15",
        "KXDOGE15M-26MAY260015-15"
    ]
    
    print("=" * 80)
    print("KALSHI ORDERBOOK VERIFICATION")
    print("=" * 80)
    
    for market_id in market_ids:
        print(f"\n{'=' * 80}")
        print(f"Market: {market_id}")
        print(f"{'=' * 80}")
        
        try:
            # Get market orderbook using the same method as ws_bridge
            orderbook = await client.get_orderbook(market_id)
            
            print(f"\nOrderbook type: {type(orderbook).__name__}")
            
            if orderbook:
                # Check for bids and asks
                bids = orderbook.bids if hasattr(orderbook, 'bids') else []
                asks = orderbook.asks if hasattr(orderbook, 'asks') else []
                
                print(f"\nBid counts:")
                print(f"  Bids: {len(bids) if bids else 0}")
                print(f"  Asks: {len(asks) if asks else 0}")
                
                if bids:
                    print(f"\n  First few bids: {bids[:3]}")
                if asks:
                    print(f"\n  First few asks: {asks[:3]}")
                
                # Check if empty
                total_levels = (len(bids) if bids else 0) + (len(asks) if asks else 0)
                if total_levels == 0:
                    print(f"  ⚠️  ORDERBOOK IS EMPTY")
                else:
                    print(f"  ✅ ORDERBOOK HAS DATA ({total_levels} total levels)")
            else:
                print(f"\n❌ ORDERBOOK IS None")
            
        except Exception as e:
            print(f"\n❌ ERROR fetching orderbook: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'=' * 80}")
    print("VERIFICATION COMPLETE")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
