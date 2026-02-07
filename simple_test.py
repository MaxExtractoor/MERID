#!/usr/bin/env python3

import requests

def simple_test():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== Simple Case Sensitivity Test ===')
    
    # Start fresh trial
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'Start: {start_resp.status_code}')
    
    # Test case sensitivity
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'PROMOTE',
        'decision_reason': 'Case test'
    })
    print(f'Case PROMOTE: {resp.status_code}')
    if resp.status_code != 200:
        print(f'Error: {resp.text}')
    
    # Test long reason
    long_reason = 'A' * 1000
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': long_reason
    })
    print(f'Long reason: {resp.status_code}')
    if resp.status_code != 200:
        print(f'Error: {resp.text}')
    
    print('=== Done ===')

if __name__ == '__main__':
    simple_test()
