import requests

# Clear registry first by checking what we have
response = requests.get('http://127.0.0.1:8001/api/v1/reality/assertions', timeout=5)
print('Current assertions:', len(response.json().get('assertions', [])))

# Bootstrap
response = requests.post('http://127.0.0.1:8001/api/v1/reality/bootstrap', timeout=5)
print('Bootstrap Response:', response.json())

# Check all domains
domains = ['system', 'execution', 'governance', 'treasury']
for domain in domains:
    response = requests.get(f'http://127.0.0.1:8001/api/v1/reality/assertions/domain/{domain}', timeout=5)
    data = response.json()
    print(f'{domain}: {data["count"]} assertions')
