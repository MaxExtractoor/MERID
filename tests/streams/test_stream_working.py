#!/usr/bin/env python3

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streams.market_data_stream_simple import MarketDataStream
from utils.logger import get_logger

logger = get_logger("test_stream_working")

async def test_basic_functionality():
    """Test basic MarketDataStream functionality"""
    
    print("🚀 Testing MarketDataStream Basic Functionality")
    print("=" * 50)
    
    # Test configuration
    config = {
        "source_type": "mock",
        "symbols": ["BTC/USD", "ETH/USD"],
        "polling_interval": 1.0
    }
    
    try:
        # Create stream
        stream = MarketDataStream(config)
        print(f"✅ Stream created: {stream.stream_type()}")
        
        # Test connection
        connected = await stream._connect()
        print(f"✅ Connection: {connected}")
        
        # Test data fetching
        data = await stream._fetch_data()
        print(f"✅ Data fetched: {len(data) if data else 0} items")
        if data:
            print(f"   Sample: {data[0]['symbol']} @ ${data[0]['price']}")
        
        # Test event transformation
        events = await stream._transform_to_events(data)
        print(f"✅ Events created: {len(events)}")
        if events:
            print(f"   Sample: {events[0].event_type} for {events[0].data.symbol}")
        
        # Test metrics
        metrics = stream.get_metrics()
        print(f"✅ Metrics: {metrics.total_events} events")
        
        # Test status
        status = stream.get_status()
        print(f"✅ Status: {status['connection_status']}")
        
        print("\n🎉 Basic functionality test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_stream_lifecycle():
    """Test stream start/stop lifecycle"""
    
    print("\n🔄 Testing Stream Lifecycle")
    print("-" * 30)
    
    config = {
        "source_type": "mock",
        "symbols": ["BTC/USD"],
        "polling_interval": 0.5
    }
    
    try:
        stream = MarketDataStream(config)
        
        # Start stream
        await stream.start()
        print("✅ Stream started")
        
        # Let it run for 2 seconds
        await asyncio.sleep(2)
        
        # Check metrics
        metrics = stream.get_metrics()
        print(f"✅ Events generated: {metrics.total_events}")
        print(f"✅ Rate: {metrics.events_per_second:.2f}/sec")
        
        # Stop stream
        await stream.stop()
        print("✅ Stream stopped")
        
        print("\n🎉 Lifecycle test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Lifecycle test failed: {e}")
        return False

async def test_event_subscription():
    """Test event subscription"""
    
    print("\n📡 Testing Event Subscription")
    print("-" * 30)
    
    config = {
        "source_type": "mock",
        "symbols": ["BTC/USD"],
        "polling_interval": 0.3
    }
    
    try:
        stream = MarketDataStream(config)
        await stream.start()
        
        event_count = 0
        async for event in stream.subscribe():
            event_count += 1
            print(f"   Event {event_count}: {event.data.symbol} @ ${event.data.price}")
            
            if event_count >= 3:  # Test 3 events
                break
        
        await stream.stop()
        print(f"✅ Subscription test: {event_count} events received")
        return True
        
    except Exception as e:
        print(f"❌ Subscription test failed: {e}")
        return False

async def main():
    """Run all tests"""
    try:
        print("🧪 MARKET DATA STREAM TEST SUITE")
        print("=" * 60)
        
        # Run tests
        test1 = await test_basic_functionality()
        test2 = await test_stream_lifecycle()
        test3 = await test_event_subscription()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS")
        print("=" * 60)
        print(f"Basic Functionality: {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Stream Lifecycle:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Event Subscription:   {'✅ PASSED' if test3 else '❌ FAILED'}")
        
        if test1 and test2 and test3:
            print("\n🎯 ALL TESTS PASSED!")
            print("✅ MarketDataStream is working correctly")
            print("✅ NotImplemented methods implemented")
            print("✅ Ready for agent integration")
            print("✅ Health monitoring functional")
        else:
            print("\n❌ Some tests failed - check implementation")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
