import requests

r = requests.get('http://localhost:8000/api/v1/reality/status')
data = r.json()

print(f"Blind: {data['system_state']['is_blind']}")
print(f"Reason: {data['system_state']['blind_reason']}")
print(f"Valid: {data['system_state']['registry_status']['valid_pct']:.1f}%")
print(f"Expired: {data['system_state']['registry_status']['expired_pct']:.1f}%")
print(f"Total assertions: {data['system_state']['registry_status']['total_assertions']}")
