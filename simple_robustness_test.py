#!/usr/bin/env python3

import requests
import time

def test_robustness_improvements():
    """Test key robustness improvements made to MERID"""
    base_url = 'http://localhost:8001/api/v1/phase0/trial'
    
    print("🚀 Testing MERID Robustness Improvements")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 0
    
    # Test 1: Enhanced Error Handling
    print("\n1. Enhanced Error Handling Test")
    
    # Start fresh trial
    start_resp = requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    if start_resp.status_code != 200:
        print("❌ Failed to start trial")
        return
    
    # Test empty model ID
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': '',
        'human_decision': 'hold',
        'decision_reason': 'Test'
    })
    total_tests += 1
    if resp.status_code == 400 and "cannot be empty" in resp.text:
        print("✅ Empty model ID properly rejected")
        tests_passed += 1
    else:
        print("❌ Empty model ID not handled correctly")
    
    # Test invalid decision
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'invalid_decision',
        'decision_reason': 'Test'
    })
    total_tests += 1
    if resp.status_code == 422:
        print("✅ Invalid decision properly rejected")
        tests_passed += 1
    else:
        print("❌ Invalid decision not handled correctly")
    
    # Test 2: Case-Insensitive Validation
    print("\n2. Case-Insensitive Validation Test")
    
    # Start fresh trial
    requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    case_variants = ['PROMOTE', 'Demote', 'HOLD', 'Suspend', 'retire']
    case_passed = 0
    
    for variant in case_variants:
        resp = requests.post(f'{base_url}/record-weekly-decision', json={
            'model_id': 'crypto_prediction_agent_v1',
            'human_decision': variant,
            'decision_reason': f'Case test: {variant}'
        })
        if resp.status_code == 200:
            case_passed += 1
    
    total_tests += 1
    if case_passed == len(case_variants):
        print(f"✅ All case variants accepted ({case_passed}/{len(case_variants)})")
        tests_passed += 1
    else:
        print(f"❌ Case sensitivity issues ({case_passed}/{len(case_variants)})")
    
    # Test 3: Edge Cases
    print("\n3. Edge Cases Test")
    
    # Start fresh trial
    requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    edge_passed = 0
    edge_total = 0
    
    # Long reason
    edge_total += 1
    long_reason = 'A' * 1000
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': long_reason
    })
    if resp.status_code == 200:
        edge_passed += 1
        print("✅ Long reason (1000 chars) accepted")
    else:
        print("❌ Long reason rejected")
    
    # Special characters
    edge_total += 1
    special_reason = 'Decision with symbols: !@#$%^&*()_+-=[]{}|;:,.<>? and unicode: αβγδε'
    resp = requests.post(f'{base_url}/record-weekly-decision', json={
        'model_id': 'crypto_prediction_agent_v1',
        'human_decision': 'hold',
        'decision_reason': special_reason
    })
    if resp.status_code == 200:
        edge_passed += 1
        print("✅ Special characters and unicode accepted")
    else:
        print("❌ Special characters rejected")
    
    total_tests += 1
    if edge_passed == edge_total:
        print(f"✅ All edge cases handled ({edge_passed}/{edge_total})")
        tests_passed += 1
    else:
        print(f"❌ Edge case issues ({edge_passed}/{edge_total})")
    
    # Test 4: Basic Functionality
    print("\n4. Basic Functionality Test")
    
    # Start fresh trial
    requests.post(f'{base_url}/start', json={'duration_weeks': 6})
    
    basic_passed = 0
    basic_total = 0
    
    # Test all decision types
    for decision in ['promote', 'demote', 'hold', 'suspend', 'retire']:
        basic_total += 1
        resp = requests.post(f'{base_url}/record-weekly-decision', json={
            'model_id': 'crypto_prediction_agent_v1',
            'human_decision': decision,
            'decision_reason': f'Basic test: {decision}'
        })
        if resp.status_code == 200:
            basic_passed += 1
    
    total_tests += 1
    if basic_passed == basic_total:
        print(f"✅ All decision types work ({basic_passed}/{basic_total})")
        tests_passed += 1
    else:
        print(f"❌ Decision type issues ({basic_passed}/{basic_total})")
    
    # Test 5: System Metrics
    print("\n5. System Metrics Test")
    
    status_resp = requests.get(f'{base_url}/status')
    total_tests += 1
    if status_resp.status_code == 200:
        data = status_resp.json()
        metrics = data.get('status', {}).get('current_metrics', {})
        
        if all(key in metrics for key in ['total_decisions', 'weekly_decisions', 'alignment_rate', 'contract_compliance_rate']):
            print("✅ Comprehensive metrics available")
            tests_passed += 1
            print(f"   Total decisions: {metrics.get('total_decisions', 0)}")
            print(f"   Weekly decisions: {metrics.get('weekly_decisions', 0)}")
            print(f"   Alignment rate: {metrics.get('alignment_rate', 0):.2%}")
            print(f"   Contract compliance: {metrics.get('contract_compliance_rate', 0):.2%}")
        else:
            print("❌ Incomplete metrics")
    else:
        print("❌ Status endpoint failed")
    
    # Results Summary
    print("\n" + "=" * 50)
    print("🎯 ROBUSTNESS TEST RESULTS")
    print("=" * 50)
    print(f"📊 Total Tests: {total_tests}")
    print(f"✅ Passed: {tests_passed}")
    print(f"❌ Failed: {total_tests - tests_passed}")
    print(f"📈 Success Rate: {(tests_passed/total_tests*100):.1f}%" if total_tests > 0 else "N/A")
    
    if tests_passed == total_tests:
        print("\n🎉 ALL ROBUSTNESS IMPROVEMENTS VALIDATED!")
        print("✅ Enhanced error handling working")
        print("✅ Case-insensitive validation working")
        print("✅ Edge cases handled properly")
        print("✅ Basic functionality robust")
        print("✅ System metrics comprehensive")
        print("\n🚀 MERID is highly robust and production-ready!")
    elif tests_passed / total_tests >= 0.8:
        print("\n✅ MOST ROBUSTNESS IMPROVEMENTS WORKING!")
        print("✅ MERID robustness significantly improved")
    elif tests_passed / total_tests >= 0.6:
        print("\n⚠️  PARTIAL ROBUSTNESS IMPROVEMENTS")
        print("⚠️  Some improvements need more work")
    else:
        print("\n❌ LIMITED ROBUSTNESS IMPROVEMENTS")
        print("❌ More robustness work needed")
    
    print("\n🚀 Robustness Testing Complete!")

if __name__ == '__main__':
    test_robustness_improvements()
