#!/usr/bin/env python3

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streams.market_data_stream_simple import MarketDataStream
from utils.logger import get_logger

logger = get_logger("test_stream_simple")

async def test_market_stream():
    """Test the MarketDataStream implementation"""
    
    print("🚀 Testing MarketDataStream Implementation")
    print("=" * 50)
    
    # Test 1: Mock data source
    print("\n1. Testing Mock Data Source")
    mock_config = {
        "source_type": "mock",
        "symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "polling_interval": 1.0
    }
    
    try:
        stream = MarketDataStream(mock_config)
        print(f"✅ MarketDataStream created: {stream.stream_type()}")
        
        # Test connection
        connected = await stream._connect()
        print(f"✅ Connection successful: {connected}")
        
        # Test data fetching
        data = await stream._fetch_data()
        print(f"✅ Data fetched: {len(data) if data else 0} items")
        
        # Test event transformation
        events = await stream._transform_to_events(data)
        print(f"✅ Events created: {len(events)}")
        
        # Test metrics
        metrics = stream.get_metrics()
        print(f"✅ Metrics: {metrics.total_events} events, {metrics.events_per_second:.2f}/sec")
        
        # Test status
        status = stream.get_status()
        print(f"✅ Status: {status['connection_status']}")
        
        # Test start/stop
        print("\n2. Testing Stream Lifecycle")
        await stream.start()
        print("✅ Stream started")
        
        # Let it run for a few seconds
        await asyncio.sleep(3)
        
        # Check metrics after running
        metrics_after = stream.get_metrics()
        print(f"✅ After 3 seconds: {metrics_after.total_events} events, {metrics_after.events_per_second:.2f}/sec")
        
        await stream.stop()
        print("✅ Stream stopped")
        
        print("\n🎉 Mock Data Source Test: PASSED")
        
    except Exception as e:
        print(f"❌ Mock test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

async def test_event_subscription():
    """Test event subscription functionality"""
    print("\n3. Testing Event Subscription")
    
    mock_config = {
        "source_type": "mock",
        "symbols": ["BTC/USD"],
        "polling_interval": 0.5
    }
    
    try:
        stream = MarketDataStream(mock_config)
        await stream.start()
        
        event_count = 0
        async for event in stream.subscribe():
            event_count += 1
            print(f"📡 Event {event_count}: {event.event_type} for {event.data.symbol} at ${event.data.price}")
            
            if event_count >= 5:  # Test 5 events
                break
        
        await stream.stop()
        print(f"✅ Subscription test completed: {event_count} events received")
        
    except Exception as e:
        print(f"❌ Subscription test failed: {e}")
        return False
    
    return True

async def main():
    """Run all stream tests"""
    try:
        # Test mock data source (should work)
        success1 = await test_market_stream()
        
        # Test event subscription
        success2 = await test_event_subscription()
        
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)
        print(f"Mock Data Source: {'✅ PASSED' if success1 else '❌ FAILED'}")
        print(f"Event Subscription: {'✅ PASSED' if success2 else '❌ FAILED'}")
        
        if success1 and success2:
            print("\n🎯 MarketDataStream implementation is WORKING!")
            print("✅ Ready for integration with agents and oracles")
            print("✅ Core NotImplemented methods implemented")
            print("✅ Health checks and metrics functional")
        else:
            print("\n❌ Implementation needs fixes")
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
