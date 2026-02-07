import requests

endpoints = [
    '/api/v1/institutional/predictions/drift',
    '/api/v1/institutional/predictions/arbitrage',
    '/api/v1/institutional/predictions/urgent',
    '/api/v1/live/predictions/markets'
]

for endpoint in endpoints:
    try:
        r = requests.get(f'http://localhost:8000{endpoint}')
        print(f"\n{endpoint}")
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"Keys: {list(data.keys())}")
            if 'signals' in data:
                print(f"Signals count: {len(data.get('signals', []))}")
            if 'opportunities' in data:
                print(f"Opportunities count: {len(data.get('opportunities', []))}")
            if 'markets' in data:
                print(f"Markets count: {len(data.get('markets', []))}")
    except Exception as e:
        print(f"\n{endpoint}")
        print(f"Error: {e}")
