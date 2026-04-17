import requests

base_url = "http://localhost:8000/api/v1/institutional"
endpoints = [
    '/systems/status',
    '/intents', 
    '/vault/status',
    '/shadow/status',
    '/risk/summary',
    '/lockdown/status',
    '/metrics'
]

print("Testing Institutional Endpoints:")
print("=" * 60)

for endpoint in endpoints:
    try:
        r = requests.get(f"{base_url}{endpoint}", timeout=5)
        status = "✅" if r.status_code == 200 else "❌"
        print(f"{status} {endpoint}: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"   Keys: {list(data.keys())[:5]}")
    except Exception as e:
        print(f"❌ {endpoint}: ERROR - {e}")

print()
