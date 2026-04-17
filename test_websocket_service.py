#!/usr/bin/env python3
"""
Simple test script for Kalshi WebSocket service
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_websocket_service():
    """Test WebSocket service initialization and basic functionality"""
    print("Testing Kalshi WebSocket Service...")
    
    try:
        from merid.event_venues.kalshi.websocket_service import get_websocket_service, start_websocket_service
        from merid.event_venues.kalshi.models import KalshiConfig
        
        print("✅ Imports successful")
        
        # Get configuration
        config = KalshiConfig()
        print(f"✅ Config loaded - Demo mode: {config.use_demo}")
        print(f"✅ API key: {config.api_key[:8] + '...' if config.api_key else 'None'}")
        print(f"✅ WebSocket URL: {config.ws_url}")
        
        # Start service
        print("🚀 Starting WebSocket service...")
        service = start_websocket_service()
        
        # Wait a moment for startup
        await asyncio.sleep(2)
        
        # Get stats
        stats = service.get_stats()
        print(f"📊 Service stats: {stats}")
        
        # Test subscription
        print("📡 Testing market subscription...")
        success = service.subscribe_market("KXBTC-24DEC-ABOVE-60000", "test")
        print(f"✅ Subscription success: {success}")
        
        # Wait for connection
        await asyncio.sleep(3)
        
        # Get updated stats
        stats = service.get_stats()
        print(f"📊 Updated stats: {stats}")
        
        # Test orderbook
        orderbook = service.get_orderbook("KXBTC-24DEC-ABOVE-60000")
        print(f"📖 Orderbook available: {orderbook is not None}")
        if orderbook:
            print(f"📖 Orderbook initialized: {orderbook.get('initialized', False)}")
        
        print("✅ Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = asyncio.run(test_websocket_service())
    sys.exit(0 if success else 1)
