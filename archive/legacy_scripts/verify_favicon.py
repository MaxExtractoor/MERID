import requests

# Test favicon endpoint
r = requests.get('http://127.0.0.1:8011/favicon.ico')
print('=== FAVICON VERIFICATION ===')
print(f'Status: {r.status_code}')
print(f'Content-Type: {r.headers.get("content-type", "Not specified")}')
print(f'Content-Length: {len(r.content)} bytes')
print(f'Header check: {r.content[:4].hex()} (should be 00000100)')

# Test analytics dashboard
r2 = requests.get('http://127.0.0.1:8011/analytics/dashboard')
print(f'\n=== DASHBOARD VERIFICATION ===')
print(f'Dashboard status: {r2.status_code}')
print(f'Trading Volume present: {"Trading Volume" in r2.text}')
print(f'Favicon link present: {"favicon.ico" in r2.text}')
icon_tag = '<link rel="icon"'
print(f'Favicon link tag: {icon_tag in r2.text}')
