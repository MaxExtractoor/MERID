import requests
import json

# Test the markets API
response = requests.get("http://127.0.0.1:8011/api/v1/institutional/predictions/markets?limit=2")
data = response.json()

print("=== PREDICTION MARKETS API TEST ===")
print(f"Status: {response.status_code}")
print(f"Markets Count: {data['count']}")
print(f"Aggregator Status: {data['status']}")

if data['markets']:
    print("\n=== SAMPLE MARKET ===")
    market = data['markets'][0]
    print(f"Market ID: {market['market_id']}")
    print(f"Platform: {market['platform']}")
    print(f"Question: {market['question']}")
    print(f"Category: {market['category']}")
    print(f"Yes Price: {market['yes_price']}")
    print(f"No Price: {market['no_price']}")
    print(f"Implied Probability: {market['implied_probability']}")
else:
    print("No markets found")

print("\n=== FULL RESPONSE ===")
print(json.dumps(data, indent=2))
