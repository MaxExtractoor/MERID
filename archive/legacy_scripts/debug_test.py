#!/usr/bin/env python3

import requests

def debug_issues():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== Debug Extended Test Issues ===')
    
    # Start trial
    print('0. Starting trial...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'   Start: {start_resp.status_code}')
    
    # Test volume decision
    print('1. Testing volume decision...')
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'promote',
        'decision_reason': 'Volume #1'
    })
    print(f'   Volume #1: {resp.status_code}')
    if resp.status_code != 200:
        print(f'   Error: {resp.text}')
    
    # Test case sensitivity
    print('2. Testing case sensitivity...')
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'PROMOTE',
        'decision_reason': 'Case test'
    })
    print(f'   Case PROMOTE: {resp.status_code}')
    if resp.status_code != 200:
        print(f'   Error: {resp.text}')
    
    # Test long reason
    print('3. Testing long reason...')
    long_reason = 'A' * 1000
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': long_reason
    })
    print(f'   Long reason: {resp.status_code}')
    if resp.status_code != 200:
        print(f'   Error: {resp.text}')
    
    # Test experiment API
    print('4. Testing experiment API...')
    exp_url = 'http://localhost:8001/api/v1/phase0/experiment'
    resp = requests.post(f'{exp_url}/weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': 'Experiment test'
    })
    print(f'   Experiment API: {resp.status_code}')
    if resp.status_code != 200:
        print(f'   Error: {resp.text}')
    
    print('=== Debug Complete ===')

if __name__ == '__main__':
    debug_issues()
