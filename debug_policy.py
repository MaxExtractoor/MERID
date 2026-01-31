#!/usr/bin/env python3

import requests

def debug_policy_issue():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== Debug Policy Issue ===')
    
    # Start trial
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'1. Trial start: {start_resp.status_code}')
    
    # First decision
    print('2. First decision...')
    resp1 = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': 'First decision'
    })
    print(f'   First: {resp1.status_code}')
    if resp1.status_code != 200:
        print(f'   Error: {resp1.text}')
    
    # Second decision (same model)
    print('3. Second decision (same model)...')
    resp2 = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'promote',
        'decision_reason': 'Second decision'
    })
    print(f'   Second: {resp2.status_code}')
    if resp2.status_code != 200:
        print(f'   Error: {resp2.text}')
    
    # Third decision (different model)
    print('4. Third decision (different model)...')
    resp3 = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'arbitrage_analyst_v2',
        'human_decision': 'hold',
        'decision_reason': 'Third decision'
    })
    print(f'   Third: {resp3.status_code}')
    if resp3.status_code != 200:
        print(f'   Error: {resp3.text}')
    
    # Check trial status
    print('5. Trial status...')
    status_resp = requests.get(f'{base_url}/status')
    if status_resp.status_code == 200:
        data = status_resp.json()
        metrics = data.get('status', {}).get('current_metrics', {})
        total_dec = metrics.get('total_decisions', 0)
        weekly_dec = metrics.get('weekly_decisions', 0)
        print(f'   Total decisions: {total_dec}')
        print(f'   Weekly decisions: {weekly_dec}')
    
    print('=== Debug Complete ===')

if __name__ == '__main__':
    debug_policy_issue()
