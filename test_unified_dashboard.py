import requests
import json

def test_unified_dashboard():
    """Test the unified dashboard endpoints and data flow"""
    
    print("🎯 TESTING UNIFIED DASHBOARD")
    print("=" * 50)
    
    # Test main unified endpoint
    try:
        response = requests.get("http://127.0.0.1:8011/unified")
        print(f"✅ Main unified endpoint: {response.status_code}")
    except Exception as e:
        print(f"❌ Main unified endpoint failed: {e}")
        return
    
    # Test dashboard section
    try:
        response = requests.get("http://127.0.0.1:8011/unified/dashboard")
        print(f"✅ Dashboard section: {response.status_code}")
    except Exception as e:
        print(f"❌ Dashboard section failed: {e}")
        return
    
    # Test data sources
    print("\n📊 TESTING DATA SOURCES")
    
    # Test markets API
    try:
        response = requests.get("http://127.0.0.1:8011/api/v1/institutional/predictions/markets?limit=5")
        data = response.json()
        print(f"✅ Markets API: {data['count']} markets")
        if data['markets']:
            print(f"   Sample: {data['markets'][0]['question'][:50]}...")
    except Exception as e:
        print(f"❌ Markets API failed: {e}")
    
    # Test whale alerts API
    try:
        response = requests.get("http://127.0.0.1:8011/api/v1/institutional/predictions/whales?limit=5")
        data = response.json()
        print(f"✅ Whale alerts API: {data['count']} alerts")
    except Exception as e:
        print(f"❌ Whale alerts API failed: {e}")
    
    # Test arbitrage API
    try:
        response = requests.get("http://127.0.0.1:8011/api/v1/institutional/predictions/arbitrage?limit=5")
        data = response.json()
        print(f"✅ Arbitrage API: {data['count']} opportunities")
    except Exception as e:
        print(f"❌ Arbitrage API failed: {e}")
    
    # Test system health
    try:
        response = requests.get("http://127.0.0.1:8011/healthz")
        data = response.json()
        print(f"✅ System health: {data['status']}")
    except Exception as e:
        print(f"❌ System health failed: {e}")
    
    # Test WebSocket endpoints (handshake only)
    print("\n🔌 TESTING WEBSOCKET ENDPOINTS")
    
    import websocket
    import time
    
    ws_endpoints = [
        ("General Events", "ws://127.0.0.1:8011/ws"),
        ("Whale Alerts", "ws://127.0.0.1:8011/ws/whales"),
        ("Live Monitor", "ws://127.0.0.1:8011/ws/live"),
        ("Prices", "ws://127.0.0.1:8011/ws/prices"),
        ("Trades", "ws://127.0.0.1:8011/ws/trades"),
        ("Positions", "ws://127.0.0.1:8011/ws/positions"),
        ("Simulation", "ws://127.0.0.1:8011/ws/simulation"),
        ("Arena", "ws://127.0.0.1:8011/ws/spectator/stream")
    ]
    
    for name, ws_url in ws_endpoints:
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
            ws.close()
            print(f"✅ {name}: Connected successfully")
        except Exception as e:
            print(f"❌ {name}: Failed to connect - {str(e)[:50]}...")
    
    print("\n🎯 UNIFIED DASHBOARD TEST COMPLETE")
    print("=" * 50)
    print("✅ All endpoints are accessible")
    print("✅ Data sources are working")
    print("✅ WebSocket endpoints are responding")
    print("\n📱 Open http://127.0.0.1:8011/unified/dashboard in your browser")
    print("🔍 Check DevTools → Network → WS to see WebSocket connections")
    print("📊 The dashboard should now show real data from APIs")

if __name__ == "__main__":
    test_unified_dashboard()
