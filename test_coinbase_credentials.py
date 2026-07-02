"""
Quick test script to verify Coinbase Exchange API credentials
"""
import asyncio
import time
import base64
import hmac
import requests

def get_coinbase_credentials():
    """Get Coinbase Exchange API credentials from environment."""
    try:
        from merid.coinbase_env import coinbase_api_key, coinbase_api_secret
        api_key = coinbase_api_key()
        api_secret = coinbase_api_secret()
        return api_key, api_secret
    except Exception as e:
        print(f"Failed to get Coinbase credentials: {e}")
        return None, None

def generate_coinbase_signature(timestamp: str, method: str, request_path: str, body: str, api_secret: str) -> str:
    """Generate Coinbase Exchange API HMAC signature."""
    message = timestamp + method + request_path + body
    secret_bytes = base64.b64decode(api_secret)
    signature = hmac.new(
        secret_bytes,
        message.encode('utf-8'),
        digestmod='sha256'
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

async def test_authenticated_ohlc():
    """Test authenticated OHLC fetch from Coinbase Exchange API."""
    api_key, api_secret = get_coinbase_credentials()
    
    if not api_key or not api_secret:
        print("❌ No Coinbase credentials found")
        print("   Expected environment variables:")
        print("   - MERID_COINBASE_API_KEY or COINBASE_API_KEY")
        print("   - MERID_COINBASE_API_SECRET or COINBASE_API_SECRET")
        return False
    
    print(f"✅ Credentials found:")
    print(f"   API Key: {api_key[:10]}...{api_key[-4:]}")
    print(f"   API Secret: {api_secret[:10]}...{api_secret[-4:]}")
    
    # Test with BTC-USD candles endpoint
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        'granularity': '300',  # 5 minutes
        'limit': 1
    }
    
    timestamp = str(int(time.time()))
    request_path = "/products/BTC-USD/candles?granularity=300&limit=1"
    signature = generate_coinbase_signature(timestamp, "GET", request_path, "", api_secret)
    
    headers = {
        'CB-ACCESS-KEY': api_key,
        'CB-ACCESS-SIGN': signature,
        'CB-ACCESS-TIMESTAMP': timestamp,
        'Content-Type': 'application/json'
    }
    
    print(f"\n🔍 Testing authenticated request to Coinbase Exchange API...")
    print(f"   URL: {url}")
    print(f"   Method: GET")
    print(f"   Path: {request_path}")
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10.0)
        
        print(f"\n📡 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Authenticated request successful!")
            print(f"   Data points returned: {len(data)}")
            if data and len(data) > 0:
                candle = data[0]
                print(f"   Candle format: [timestamp, low, high, open, close, volume]")
                print(f"   Sample candle: {candle}")
                print(f"   OHLC values:")
                print(f"     Open: ${candle[3]:.2f}")
                print(f"     High: ${candle[2]:.2f}")
                print(f"     Low: ${candle[1]:.2f}")
                print(f"     Close: ${candle[4]:.2f}")
            return True
        else:
            print(f"❌ Authenticated request failed")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return False
            
    except Exception as e:
        print(f"❌ Request error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Coinbase Exchange API Credentials Test")
    print("=" * 60)
    print()
    
    result = asyncio.run(test_authenticated_ohlc())
    
    print()
    print("=" * 60)
    if result:
        print("✅ TEST PASSED: Credentials are valid and working")
    else:
        print("❌ TEST FAILED: Credentials missing or invalid")
    print("=" * 60)
