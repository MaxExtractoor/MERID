import requests
import json

print('🔍 TESTING ACTUAL DASHBOARD ACCESS')
print('=' * 50)

try:
    # Test the actual dashboard endpoint that works
    response = requests.get('http://127.0.0.1:8001/dashboard/fixed', timeout=5)
    print(f'Dashboard Fixed: {response.status_code}')
    
    if response.status_code == 200:
        content = response.text
        print(f'Dashboard content length: {len(content)} characters')
        print('First 500 characters:')
        print(content[:500])
        print('...')
    
    # Test local venue validation status
    response = requests.get('http://127.0.0.1:8001/api/v1/localvenue/validation-status', timeout=5)
    print(f'\nLocal Venue Validation Status: {response.status_code}')
    
    if response.status_code == 200:
        data = response.json()
        print(f'  Overall Status: {data.get("overall_status", "unknown")}')
        print(f'  Current Phase: {data.get("current_phase", "unknown")}')
        print(f'  Phases: {len(data.get("phases", []))}')
    
    # Test reality status (even though it errors)
    response = requests.get('http://127.0.0.1:8001/api/v1/reality/status', timeout=5)
    print(f'\nReality Status: {response.status_code}')
    
    if response.status_code == 500:
        print('  Reality system has critical errors (as seen in logs)')
    
    print('\n🌐 ACTUAL ACCESS URLS:')
    print('  Dashboard: http://127.0.0.1:8001/dashboard/fixed')
    print('  Local Venue APIs: http://127.0.0.1:8001/api/v1/localvenue/*')
    print('  API Docs: http://127.0.0.1:8001/docs')
    
except Exception as e:
    print(f'ERROR: {e}')
