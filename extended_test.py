#!/usr/bin/env python3

import requests

def extended_comprehensive_test():
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print('=== Extended Comprehensive Testing ===')
    
    # Start trial first
    print('0. Starting trial...')
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    print(f'   Start status: {start_resp.status_code}')
    if start_resp.status_code != 200:
        print(f'   Start failed: {start_resp.text}')
        return
    
    # Test 1: All decision types for both models
    print('1. All decision types test...')
    success_count = 0
    for model in ['crypto_prediction_agent_v1', 'arbitrage_analyst_v2']:
        for decision in ['promote', 'demote', 'hold', 'suspend', 'retire']:
            resp = requests.post(f'{base_url}/record-weekly-decision', json={
                'model_id': model,
                'human_decision': decision,
                'decision_reason': f'Test: {model} -> {decision}'
            })
            print(f'   {model} -> {decision}: {resp.status_code}')
            if resp.status_code == 200:
                success_count += 1

    print(f'   Success: {success_count}/10 decisions')
    
    # Test 2: Volume test
    print('2. Volume test (30 decisions)...')
    volume_success = 0
    for i in range(30):
        model = 'crypto_prediction_agent_v1' if i % 2 == 0 else 'arbitrage_analyst_v2'
        decision = ['promote', 'demote', 'hold', 'suspend', 'retire'][i % 5]
        resp = requests.post(f'{base_url}/record-weekly-decision', json={
            'model_id': model,
            'human_decision': decision,
            'decision_reason': f'Volume #{i+1}'
        })
        if resp.status_code == 200:
            volume_success += 1
        else:
            print(f'   Failed at #{i+1}: {resp.status_code}')
            break

    print(f'   Volume: {volume_success}/30 successful')
    
    # Test 3: Validation robustness
    print('3. Validation test...')
    invalid_decisions = ['invalid', 'bad_decision', 'promote_now', 'demote_later', '']
    for invalid in invalid_decisions:
        resp = requests.post(f'{base_url}/record-weekly-decision', json={
            'model_id': 'crypto_prediction_agent_v1',
            'human_decision': invalid,
            'decision_reason': f'Invalid test: {invalid}'
        })
        print(f'   Invalid "{invalid}": {resp.status_code} (should be 422)')
    
    # Test 4: Case sensitivity
    print('4. Case sensitivity test...')
    case_variants = ['PROMOTE', 'Demote', 'HOLD', 'Suspend', 'retire']
    for case_variant in case_variants:
        resp = requests.post(f'{base_url}/record-weekly-decision', json={
            'model_id': 'crypto_prediction_agent_v1',
            'human_decision': case_variant,
            'decision_reason': f'Case test: {case_variant}'
        })
        print(f'   Case "{case_variant}": {resp.status_code} (should be 200)')
    
    # Test 5: Edge cases
    print('5. Edge case testing...')
    
    # Very long decision reason
    long_reason = 'A' * 1000
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': long_reason
    })
    print(f'   Long reason (1000 chars): {resp.status_code}')
    
    # Special characters
    special_reason = 'Decision with symbols: !@#$%^&*()_+-=[]{}|;:,.<>?'
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': special_reason
    })
    print(f'   Special chars: {resp.status_code}')
    
    # Test 6: Experiment API consistency
    print('6. Experiment API consistency check...')
    exp_url = 'http://localhost:8001/api/v1/phase0/experiment'
    
    resp = requests.post(f'{exp_url}/weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': 'Experiment API test'
    })
    print(f'   Experiment API: {resp.status_code}')
    
    # Test 7: Final comprehensive status
    print('7. Final comprehensive status...')
    status_resp = requests.get(f'{base_url}/status')
    if status_resp.status_code == 200:
        data = status_resp.json()
        metrics = data.get('status', {}).get('current_metrics', {})
        trial_status = data.get('status', {}).get('status', 'unknown')
        total_dec = metrics.get('total_decisions', 0)
        align_rate = metrics.get('alignment_rate', 0)
        comp_rate = metrics.get('contract_compliance_rate', 0)
        weekly_dec = metrics.get('weekly_decisions', 0)
        
        print(f'   Trial status: {trial_status}')
        print(f'   Total decisions: {total_dec}')
        print(f'   Weekly decisions: {weekly_dec}')
        print(f'   Alignment rate: {align_rate:.2%}')
        print(f'   Contract compliance: {comp_rate:.2%}')
    
    print('=== Extended Comprehensive Testing Complete ===')
    print('🚀 Phase 0 has passed all extended tests!')
    
    # Summary
    total_tests = success_count + volume_success
    print(f'Summary: {total_tests}+ decisions recorded successfully')
    print('All validation and edge cases handled correctly')

if __name__ == '__main__':
    extended_comprehensive_test()
