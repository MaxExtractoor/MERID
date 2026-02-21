import websocket
import json

def test_whale_websocket():
    """Test whale WebSocket with token."""
    try:
        # Connect with a test token
        token = "test-token-123"
        ws_url = f"ws://127.0.0.1:8011/ws/whales?token={token}"
        
        print(f"🐋 Connecting to: {ws_url}")
        ws = websocket.create_connection(ws_url)
        
        # Wait for welcome message
        result = ws.recv()
        message = json.loads(result)
        
        print(f"✅ Connected successfully!")
        print(f"📨 Received: {message}")
        
        # Close connection
        ws.close()
        return True
        
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        return False

if __name__ == "__main__":
    print("🐋 WHALE WEBSOCKET TEST")
    print("=" * 40)
    
    success = test_whale_websocket()
    
    print("\n" + "=" * 40)
    if success:
        print("✅ WebSocket test PASSED")
    else:
        print("❌ WebSocket test FAILED")
