import requests
import json

# Test all prediction market endpoints
endpoints = [
    "/api/v1/institutional/predictions/markets?limit=3",
    "/api/v1/institutional/predictions/drift?limit=3", 
    "/api/v1/institutional/predictions/arbitrage?limit=3"
]

print("=== PREDICTION MARKETS API COMPREHENSIVE TEST ===")
base_url = "http://127.0.0.1:8011"

for endpoint in endpoints:
    try:
        response = requests.get(f"{base_url}{endpoint}")
        data = response.json()
        
        print(f"\n--- {endpoint} ---")
        print(f"Status: {response.status_code}")
        print(f"Response Keys: {list(data.keys())}")
        
        if 'markets' in data:
            print(f"Markets: {len(data['markets'])}")
            if data['markets']:
                market = data['markets'][0]
                print(f"Sample: {market['question'][:50]}...")
        
        if 'signals' in data:
            print(f"Signals: {len(data['signals'])}")
            
        if 'status' in data:
            status = data['status']
            if isinstance(status, dict):
                print(f"Running: {status.get('running', 'unknown')}")
                print(f"Total Markets: {status.get('total_markets', 'unknown')}")
                
    except Exception as e:
        print(f"ERROR: {e}")

print("\n=== WEBSOCKET HANDSHAKE TEST ===")
try:
    # Test WebSocket handshake
    import websocket
    ws = websocket.create_connection("ws://127.0.0.1:8011/ws")
    print("WebSocket connected successfully!")
    
    # Try to receive a message (with timeout)
    ws.settimeout(2.0)
    try:
        message = ws.recv()
        print(f"Received: {message[:100]}...")
    except:
        print("No immediate message (normal for event stream)")
    
    ws.close()
    print("WebSocket test completed")
    
except ImportError:
    print("WebSocket client not available - install: pip install websocket-client")
except Exception as e:
    print(f"WebSocket connection failed: {e}")
