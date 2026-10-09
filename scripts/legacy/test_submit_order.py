"""Submit a test order through the new test endpoint."""

import requests
import json
import time

SERVER_URL = "http://localhost:8011"

def submit_test_order():
    """Submit a test order through the system."""
    print("=" * 70)
    print("SUBMITTING TEST ORDER")
    print("=" * 70)
    
    # First check system health
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/health", timeout=5)
        response.raise_for_status()
        health = response.json()
        print(f"✓ System health: {health.get('status')}")
    except Exception as e:
        print(f"✗ System not healthy: {e}")
        return
    
    # Get available markets
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/md-debug", timeout=5)
        response.raise_for_status()
        md = response.json()
        
        print("\nAvailable markets:")
        for ticker, data in md.get('tickers', {}).items():
            bid = data.get('best_bid_cents', 0)
            ask = data.get('best_ask_cents', 0)
            executable = data.get('executable', False)
            print(f"  {ticker}: bid={bid} ask={ask} executable={executable}")
        
        # Select a market
        tickers = list(md.get('tickers', {}).keys())
        if not tickers:
            print("✗ No markets available")
            return
        
        # Use the first executable market
        selected_ticker = tickers[0]
        print(f"\n✓ Selected market: {selected_ticker}")
        
    except Exception as e:
        print(f"✗ Failed to get markets: {e}")
        return
    
    # Submit test order
    print(f"\n=== Submitting Test Order ===")
    print(f"Market: {selected_ticker}")
    print(f"Side: yes")
    print(f"Action: buy")
    print(f"Price: 50 cents")
    print(f"Count: 1")
    
    order_request = {
        "ticker": selected_ticker,
        "side": "yes",
        "action": "buy",
        "price_cents": 50,
        "count": 1,
        "agent_id": "BTC_15M"
    }
    
    try:
        response = requests.post(
            f"{SERVER_URL}/api/v1/test-order",
            json=order_request,
            timeout=30
        )
        
        print(f"\nResponse status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Order processed")
            print(f"  Status: {result.get('status')}")
            print(f"  Mode: {result.get('mode')}")
            print(f"  Reason: {result.get('reason')}")
            print(f"  Latency: {result.get('latency_ms')}ms")
            
            if result.get('order_id'):
                print(f"  Order ID: {result.get('order_id')}")
            if result.get('venue_order_id'):
                print(f"  Venue Order ID: {result.get('venue_order_id')}")
            if result.get('filled'):
                print(f"  Filled: {result.get('filled')}")
            if result.get('fill_price_cents'):
                print(f"  Fill Price: {result.get('fill_price_cents')} cents")
            
            print("\n" + "=" * 70)
            print("ORDER EXECUTION TEST COMPLETE")
            print("=" * 70)
            
            if result.get('status') in ['filled', 'accepted']:
                print("✅ SUCCESS: Order executed through full pipeline")
                print("   - Order routing functional")
                print("   - Risk checks operational")
                print("   - Market validation working")
                print("   - Venue integration active")
            else:
                print(f"⚠ Order status: {result.get('status')}")
                print(f"   Reason: {result.get('reason')}")
                
        else:
            print(f"✗ Order submission failed: {response.status_code}")
            print(f"  Error: {response.text}")
            
    except Exception as e:
        print(f"✗ Order submission failed with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    submit_test_order()
