"""
Test script for whale detection system
"""

import asyncio
import json
import time
from datetime import datetime

# Test whale event creation
def create_test_whale_event():
    """Create a test whale event for development."""
    return {
        "type": "whale",
        "mint": "TestMintAddress123456789",
        "owner": "TestOwnerAddress987654321",
        "amount": 150000.0,
        "timestamp": datetime.utcnow().isoformat(),
        "threshold": 100000
    }

def test_whale_event_storage():
    """Test whale event storage in PredictionMarketAggregator."""
    try:
        from monitoring.prediction_markets import get_prediction_aggregator, record_whale_event, get_whale_events
        
        # Get aggregator
        aggregator = get_prediction_aggregator()
        print(f"✅ Got aggregator with {len(aggregator._all_markets)} markets")
        
        # Create test whale event
        test_event = create_test_whale_event()
        print(f"✅ Created test whale event: {test_event['amount']} tokens")
        
        # Record whale event
        record_whale_event(aggregator, test_event)
        print(f"✅ Recorded whale event")
        
        # Get whale events
        events = get_whale_events(aggregator, limit=5)
        print(f"✅ Retrieved {len(events)} whale events")
        
        if events:
            latest = events[0]
            print(f"✅ Latest whale event: {latest['amount']} tokens from {latest['owner'][:8]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing whale event storage: {e}")
        return False

def test_whale_api_endpoint():
    """Test whale events HTTP API endpoint."""
    try:
        import requests
        
        # Test the whale events endpoint
        response = requests.get("http://127.0.0.1:8011/api/v1/institutional/predictions/whales?limit=5")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Whale API endpoint working: {data['count']} events")
            if data['whales']:
                print(f"✅ Sample whale: {data['whales'][0]['amount']} tokens")
            return True
        else:
            print(f"❌ Whale API returned status: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing whale API: {e}")
        return False

def test_whale_websocket_endpoint():
    """Test whale WebSocket endpoint (without authentication)."""
    try:
        import websocket
        
        # Try to connect without token (should fail with auth error)
        ws = websocket.create_connection("ws://127.0.0.1:8011/ws/whales")
        print("❌ WebSocket connected without token (should fail)")
        return False
        
    except Exception as e:
        if "401" in str(e) or "1008" in str(e) or "authentication" in str(e).lower():
            print("✅ WebSocket correctly requires authentication")
            return True
        else:
            print(f"❌ Unexpected WebSocket error: {e}")
            return False

async def main():
    """Run all whale detection tests."""
    print("🐋 WHALE DETECTION SYSTEM TESTS")
    print("=" * 50)
    
    # Test 1: Whale event storage
    print("\n1. Testing whale event storage...")
    storage_ok = test_whale_event_storage()
    
    # Test 2: Whale API endpoint
    print("\n2. Testing whale API endpoint...")
    api_ok = test_whale_api_endpoint()
    
    # Test 3: WebSocket authentication
    print("\n3. Testing WebSocket authentication...")
    ws_ok = test_whale_websocket_endpoint()
    
    # Summary
    print("\n" + "=" * 50)
    print("🐋 TEST SUMMARY:")
    print(f"  Whale Event Storage: {'✅ PASS' if storage_ok else '❌ FAIL'}")
    print(f"  Whale API Endpoint: {'✅ PASS' if api_ok else '❌ FAIL'}")
    print(f"  WebSocket Auth: {'✅ PASS' if ws_ok else '❌ FAIL'}")
    
    overall = storage_ok and api_ok and ws_ok
    print(f"\n🎯 Overall Status: {'✅ ALL TESTS PASSED' if overall else '❌ SOME TESTS FAILED'}")
    
    if overall:
        print("\n🚀 Whale detection system is ready for production!")
        print("\n📋 Next steps:")
        print("   1. Configure SOLANA_WS_URL in .env")
        print("   2. Set WHALE_MINT_ADDRESS for token monitoring")
        print("   3. Adjust WHALE_THRESHOLD for your needs")
        print("   4. Implement JWT authentication for WebSocket")
        print("   5. Test with real Solana WebSocket connection")
    else:
        print("\n🔧 Fix failing tests before production deployment")

if __name__ == "__main__":
    asyncio.run(main())
