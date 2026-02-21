import requests
import os

# Test favicon endpoint details
r = requests.get('http://127.0.0.1:8011/favicon.ico')
print('=== FAVICON ANALYSIS ===')
print(f'Status: {r.status_code}')
print(f'Content-Type: {r.headers.get("content-type", "Not specified")}')
print(f'Content-Length: {len(r.content)} bytes')
print(f'Cache-Control: {r.headers.get("cache-control", "Not specified")}')

# Check file exists and size
favicon_path = 'c:/Dev/MERID/favicon.ico'
if os.path.exists(favicon_path):
    file_size = os.path.getsize(favicon_path)
    print(f'File size: {file_size} bytes')
    print(f'File location: {favicon_path}')
else:
    print('File not found')

# Verify it's a valid ICO (should start with specific bytes)
with open(favicon_path, 'rb') as f:
    header = f.read(4)
    print(f'File header: {header.hex()} (should be 00000100 for valid ICO)')

print('\n=== ANALYTICS DASHBOARD CHECK ===')
r2 = requests.get('http://127.0.0.1:8011/analytics/dashboard')
print(f'Dashboard status: {r2.status_code}')
print(f'Trading Volume present: {"Trading Volume" in r2.text}')
print(f'Favicon link in HTML: {"favicon" in r2.text.lower()}')
