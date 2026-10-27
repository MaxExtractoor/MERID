#!/usr/bin/env python3
"""
Check spot price feed from the running server.
This script checks if spot prices are being fetched and cached for all crypto assets.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.unified_spot_service import get_unified_spot_service
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


async def check_spot_price_feed():
    """Check spot price feed from running server."""
    print("="*80)
    print("SPOT PRICE FEED CHECK")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc)}")
    print()
    
    # Get spot service (singleton from running server)
    spot_service = get_unified_spot_service()
    
    # Check each asset
    results = {}
    for asset in ACTIVE_CRYPTO_ASSETS:
        try:
            spot_data = await spot_service.get_spot_price(asset)
            if spot_data:
                price = spot_data.get('price')
                source = spot_data.get('source')
                timestamp = spot_data.get('timestamp')
                
                if price:
                    results[asset] = {"status": "OK", "price": price, "source": source, "timestamp": timestamp}
                    print(f"{asset}: ✅ Price available")
                    print(f"  Price: ${price}")
                    print(f"  Source: {source}")
                    if timestamp:
                        print(f"  Timestamp: {timestamp}")
                else:
                    results[asset] = {"status": "NO_PRICE", "data": spot_data}
                    print(f"{asset}: ❌ No price in data")
                    print(f"  Data: {spot_data}")
            else:
                results[asset] = {"status": "NO_DATA"}
                print(f"{asset}: ❌ No spot data available")
        except Exception as e:
            results[asset] = {"status": "ERROR", "error": str(e)}
            print(f"{asset}: ❌ Error: {e}")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    ok = sum(1 for r in results.values() if r["status"] == "OK")
    no_price = sum(1 for r in results.values() if r["status"] == "NO_PRICE")
    no_data = sum(1 for r in results.values() if r["status"] == "NO_DATA")
    error = sum(1 for r in results.values() if r["status"] == "ERROR")
    
    print(f"Price available: {ok}/5")
    print(f"No price in data: {no_price}/5")
    print(f"No data available: {no_data}/5")
    print(f"Error: {error}/5")
    
    return results


if __name__ == "__main__":
    asyncio.run(check_spot_price_feed())
