#!/usr/bin/env python3

import requests

def debug_basic_functionality():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== Debug Basic Functionality ===')
    
    # Test 1: Start trial
    print('1. Starting trial...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'   Start response: {start_resp.status_code}')
    if start_resp.status_code != 200:
        print(f'   Start error: {start_resp.text}')
        return
    
    # Test 2: Check trial status
    print('2. Checking trial status...')
    status_resp = requests.get(f'{base_url}/status')
    print(f'   Status response: {status_resp.status_code}')
    if status_resp.status_code == 200:
        data = status_resp.json()
        trial_status = data.get('status', {}).get('status', 'unknown')
        print(f'   Trial status: {trial_status}')
    
    # Test 3: Try single decision
    print('3. Testing single decision...')
    decision_resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': 'Debug test'
    })
    print(f'   Decision response: {decision_resp.status_code}')
    if decision_resp.status_code != 200:
        print(f'   Decision error: {decision_resp.text}')
    
    # Test 4: Try with different model
    print('4. Testing with arbitrage_analyst_v2...')
    decision_resp2 = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'arbitrage_analyst_v2',
        'human_decision': 'hold',
        'decision_reason': 'Debug test 2'
    })
    print(f'   Decision response: {decision_resp2.status_code}')
    if decision_resp2.status_code != 200:
        print(f'   Decision error: {decision_resp2.text}')
    
    print('=== Debug Complete ===')

if __name__ == '__main__':
    debug_basic_functionality()
