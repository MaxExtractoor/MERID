import requests

def test_polymarket_api():
    """Test if Polymarket API is accessible."""
    try:
        url = "https://gamma-api.polymarket.com/markets?limit=10&active=true"
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Markets: {len(data)}")
            if data:
                print("Sample market:", data[0].get('question', 'N/A'))
        else:
            print("Error:", resp.text)
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_polymarket_api()
