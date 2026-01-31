#!/usr/bin/env python3

import requests

def clean_production_test():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== 🧹 CLEAN PRODUCTION TEST ===')
    print('Testing each scenario with fresh trial state')
    
    # Test 1: Core functionality
    print('1. Core functionality test...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'   Start: {start_resp.status_code}')
    
    success_count = 0
    for model in ['crypto_prediction_agent_v1', 'arbitrage_analyst_v2']:
        for decision in ['promote', 'demote', 'hold']:
            resp = requests.post(f'{base_url}/record-weekly-decision', json={
                'model_id': model,
                'human_decision': decision,
                'decision_reason': f'Core test: {model} -> {decision}'
            })
            if resp.status_code == 200:
                success_count += 1
    
    print(f'   Core functionality: {success_count}/6 decisions')
    
    # Test 2: Input validation (fresh trial)
    print('2. Input validation test...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    invalid_resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'invalid_decision',
        'decision_reason': 'Test validation'
    })
    print(f'   Invalid decision: {invalid_resp.status_code} (expected 422)')
    
    # Test 3: Case sensitivity (fresh trial)
    print('3. Case sensitivity test...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    case_resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'PROMOTE',
        'decision_reason': 'Test case sensitivity'
    })
    print(f'   Case sensitivity: {case_resp.status_code} (expected 200)')
    if case_resp.status_code != 200:
        print(f'   Error: {case_resp.text}')
    
    # Test 4: Edge cases (fresh trial)
    print('4. Edge cases test...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    # Long reason
    long_reason = 'A' * 1000
    long_resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': long_reason
    })
    print(f'   Long reason: {long_resp.status_code} (expected 200)')
    if long_resp.status_code != 200:
        print(f'   Error: {long_resp.text}')
    
    # Special characters
    special_resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': 'Decision with symbols: !@#$%^&*()_+-=[]{}|;:,.<>?'
    })
    print(f'   Special characters: {special_resp.status_code} (expected 200)')
    if special_resp.status_code != 200:
        print(f'   Error: {special_resp.text}')
    
    # Summary
    print()
    print('=== 🎯 CLEAN TEST SUMMARY ===')
    
    core_ok = success_count == 6
    validation_ok = invalid_resp.status_code == 422
    case_ok = case_resp.status_code == 200
    long_ok = long_resp.status_code == 200
    special_ok = special_resp.status_code == 200
    
    print(f'Core functionality: {"✅" if core_ok else "❌"}')
    print(f'Input validation: {"✅" if validation_ok else "❌"}')
    print(f'Case sensitivity: {"✅" if case_ok else "❌"}')
    print(f'Long reason: {"✅" if long_ok else "❌"}')
    print(f'Special characters: {"✅" if special_ok else "❌"}')
    
    all_ok = all([core_ok, validation_ok, case_ok, long_ok, special_ok])
    
    if all_ok:
        print()
        print('🚀 ALL TESTS PASSED!')
        print('✅ Phase 0 is fully production ready')
        print('✅ All edge cases handled correctly')
        print('✅ Input validation working properly')
        print('✅ Case sensitivity implemented')
        print('🎯 Ready for Phase 0b scaling!')
    else:
        print()
        print('❌ Some issues remain - investigation needed')

if __name__ == '__main__':
    clean_production_test()
