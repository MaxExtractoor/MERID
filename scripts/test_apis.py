import requests

# Test institutional APIs
apis = [
    '/api/v1/institutional/predictions/markets?limit=20',
    '/api/v1/institutional/predictions/drift?limit=10', 
    '/api/v1/institutional/predictions/arbitrage?limit=10'
]

for api in apis:
    try:
        r = requests.get(f'http://127.0.0.1:8011{api}')
        print(f'{api}: {r.status_code}')
        if r.status_code == 200:
            data = r.json()
            data_type = len(data) if isinstance(data, list) else "object"
            print(f'  Data items: {data_type}')
        else:
            print(f'  Error: {r.text[:100]}')
    except Exception as e:
        print(f'{api}: ERROR - {e}')
