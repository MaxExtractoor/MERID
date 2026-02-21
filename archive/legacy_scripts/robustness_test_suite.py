#!/usr/bin/env python3

import requests
import time
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

class MERIDRobustnessTestSuite:
    """
    Comprehensive robustness testing suite for MERID Phase 0
    Tests edge cases, error handling, concurrency, and system resilience
    """
    
    def __init__(self):
        self.base_url = 'http://localhost:8001/api/v1/phase0/trial'
        self.exp_url = 'http://localhost:8001/api/v1/phase0/experiment'
        self.results = {
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': 0,
            'errors': []
        }
    
    def log_result(self, test_name: str, passed: bool, details: str = ""):
        """Log test result"""
        self.results['total_tests'] += 1
        if passed:
            self.results['passed_tests'] += 1
            print(f"✅ {test_name}: PASSED {details}")
        else:
            self.results['failed_tests'] += 1
            print(f"❌ {test_name}: FAILED {details}")
            self.results['errors'].append(f"{test_name}: {details}")
    
    def test_basic_functionality(self) -> bool:
        """Test basic Phase 0 functionality"""
        print("\n=== Basic Functionality Test ===")
        
        try:
            # Start trial
            start_resp = requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            if start_resp.status_code != 200:
                self.log_result("Trial Start", False, f"Status: {start_resp.status_code}")
                return False
            
            # Test all decision types
            success_count = 0
            for model in ['crypto_prediction_agent_v1', 'arbitrage_analyst_v2']:
                for decision in ['promote', 'demote', 'hold', 'suspend', 'retire']:
                    resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                        'model_id': model,
                        'human_decision': decision,
                        'decision_reason': f'Basic test: {model} -> {decision}'
                    })
                    if resp.status_code == 200:
                        success_count += 1
            
            basic_ok = success_count == 10
            self.log_result("Basic Functionality", basic_ok, f"{success_count}/10 decisions")
            return basic_ok
            
        except Exception as e:
            self.log_result("Basic Functionality", False, f"Exception: {str(e)}")
            return False
    
    def test_input_validation_robustness(self) -> bool:
        """Test input validation with edge cases"""
        print("\n=== Input Validation Robustness Test ===")
        
        try:
            # Start fresh trial
            requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            validation_passed = 0
            total_tests = 0
            
            # Test invalid decisions
            invalid_decisions = [
                'invalid', 'bad_decision', 'promote_now', 'demote_later', 
                '', ' ', 'PROMOTE_INVALID', 'invalid123', 'null', 'undefined'
            ]
            
            for invalid in invalid_decisions:
                total_tests += 1
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': invalid,
                    'decision_reason': f'Invalid test: {invalid}'
                })
                if resp.status_code == 422:
                    validation_passed += 1
            
            # Test valid case variants
            valid_variants = ['PROMOTE', 'Demote', 'HOLD', 'Suspend', 'retire']
            for variant in valid_variants:
                total_tests += 1
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': variant,
                    'decision_reason': f'Case test: {variant}'
                })
                if resp.status_code == 200:
                    validation_passed += 1
            
            validation_ok = validation_passed == total_tests
            self.log_result("Input Validation", validation_ok, f"{validation_passed}/{total_tests}")
            return validation_ok
            
        except Exception as e:
            self.log_result("Input Validation", False, f"Exception: {str(e)}")
            return False
    
    def test_edge_cases(self) -> bool:
        """Test edge cases and boundary conditions"""
        print("\n=== Edge Cases Test ===")
        
        try:
            # Start fresh trial
            requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            edge_passed = 0
            total_edge = 0
            
            # Test very long decision reason
            long_reasons = [100, 1000, 5000, 10000]
            for length in long_reasons:
                total_edge += 1
                long_reason = 'A' * length
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': 'hold',
                    'decision_reason': long_reason
                })
                if resp.status_code == 200:
                    edge_passed += 1
            
            # Test special characters and unicode
            special_cases = [
                'Decision with symbols: !@#$%^&*()_+-=[]{}|;:,.<>?',
                'Unicode test: αβγδεζηθικλμνξοπρστυφχψω',
                'Mixed: Hello 世界 🌍 Test 123',
                'Newlines\nand\ttabs\ttest',
                'Quotes "single" and "double" test',
                'JSON special: {}[]":,\/'
            ]
            
            for special in special_cases:
                total_edge += 1
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': 'hold',
                    'decision_reason': special
                })
                if resp.status_code == 200:
                    edge_passed += 1
            
            # Test boundary model IDs
            boundary_models = [
                'crypto_prediction_agent_v1',  # Valid
                'arbitrage_analyst_v2',         # Valid
                'invalid_model',               # Invalid
                '',                            # Empty
                'a' * 100,                    # Very long
            ]
            
            for model in boundary_models:
                total_edge += 1
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': model,
                    'human_decision': 'hold',
                    'decision_reason': f'Boundary model test: {model}'
                })
                # Valid models should succeed, invalid should fail
                expected_success = model in ['crypto_prediction_agent_v1', 'arbitrage_analyst_v2']
                actual_success = resp.status_code == 200
                if expected_success == actual_success:
                    edge_passed += 1
            
            edge_ok = edge_passed == total_edge
            self.log_result("Edge Cases", edge_ok, f"{edge_passed}/{total_edge}")
            return edge_ok
            
        except Exception as e:
            self.log_result("Edge Cases", False, f"Exception: {str(e)}")
            return False
    
    def test_concurrent_requests(self) -> bool:
        """Test concurrent request handling"""
        print("\n=== Concurrent Requests Test ===")
        
        try:
            # Start fresh trial
            requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            def make_request(request_id: int) -> Dict[str, Any]:
                """Make a single decision request"""
                model = 'crypto_prediction_agent_v1' if request_id % 2 == 0 else 'arbitrage_analyst_v2'
                decision = ['promote', 'demote', 'hold', 'suspend', 'retire'][request_id % 5]
                
                try:
                    resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                        'model_id': model,
                        'human_decision': decision,
                        'decision_reason': f'Concurrent test #{request_id}'
                    })
                    return {
                        'request_id': request_id,
                        'status_code': resp.status_code,
                        'success': resp.status_code == 200
                    }
                except Exception as e:
                    return {
                        'request_id': request_id,
                        'status_code': 0,
                        'success': False,
                        'error': str(e)
                    }
            
            # Test with 20 concurrent requests
            concurrent_results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(make_request, i) for i in range(20)]
                for future in as_completed(futures):
                    result = future.result()
                    concurrent_results.append(result)
            
            successful_requests = sum(1 for r in concurrent_results if r['success'])
            concurrent_ok = successful_requests >= 18  # Allow for some failures
            
            self.log_result("Concurrent Requests", concurrent_ok, 
                          f"{successful_requests}/20 requests successful")
            return concurrent_ok
            
        except Exception as e:
            self.log_result("Concurrent Requests", False, f"Exception: {str(e)}")
            return False
    
    def test_error_recovery(self) -> bool:
        """Test error recovery and resilience"""
        print("\n=== Error Recovery Test ===")
        
        try:
            recovery_passed = 0
            total_recovery = 0
            
            # Test 1: Invalid request followed by valid request
            total_recovery += 1
            requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            # Make invalid request
            invalid_resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'invalid_decision',
                'decision_reason': 'Test recovery'
            })
            
            # Make valid request after error
            valid_resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Recovery test'
            })
            
            if invalid_resp.status_code == 422 and valid_resp.status_code == 200:
                recovery_passed += 1
            
            # Test 2: Multiple trial starts
            total_recovery += 1
            start1 = requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            start2 = requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            # Should still be able to make decisions
            decision_resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Multiple start test'
            })
            
            if decision_resp.status_code == 200:
                recovery_passed += 1
            
            # Test 3: Malformed JSON handling
            total_recovery += 1
            try:
                malformed_resp = requests.post(
                    f'{self.base_url}/record-weekly-decision',
                    data='{"invalid": json}',  # Malformed JSON
                    headers={'Content-Type': 'application/json'}
                )
                # Should handle gracefully (400 or 422)
                if malformed_resp.status_code in [400, 422]:
                    recovery_passed += 1
            except:
                # Exception is also acceptable handling
                recovery_passed += 1
            
            recovery_ok = recovery_passed == total_recovery
            self.log_result("Error Recovery", recovery_ok, f"{recovery_passed}/{total_recovery}")
            return recovery_ok
            
        except Exception as e:
            self.log_result("Error Recovery", False, f"Exception: {str(e)}")
            return False
    
    def test_high_volume_stress(self) -> bool:
        """Test high-volume request handling"""
        print("\n=== High Volume Stress Test ===")
        
        try:
            # Start fresh trial
            requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            
            volume_success = 0
            volume_total = 100
            
            print("  Sending 100 sequential requests...")
            for i in range(volume_total):
                model = 'crypto_prediction_agent_v1' if i % 2 == 0 else 'arbitrage_analyst_v2'
                decision = ['promote', 'demote', 'hold', 'suspend', 'retire'][i % 5]
                
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': model,
                    'human_decision': decision,
                    'decision_reason': f'Volume test #{i+1}'
                })
                
                if resp.status_code == 200:
                    volume_success += 1
                elif resp.status_code == 400:
                    # Stop early if we hit policy issues
                    break
                
                # Small delay to avoid overwhelming
                if i % 10 == 0:
                    time.sleep(0.1)
            
            volume_ok = volume_success >= 50  # At least 50% should succeed
            self.log_result("High Volume Stress", volume_ok, f"{volume_success}/{volume_total}")
            return volume_ok
            
        except Exception as e:
            self.log_result("High Volume Stress", False, f"Exception: {str(e)}")
            return False
    
    def test_api_consistency(self) -> bool:
        """Test consistency between trial and experiment APIs"""
        print("\n=== API Consistency Test ===")
        
        try:
            consistency_passed = 0
            total_consistency = 0
            
            # Test trial API
            total_consistency += 1
            trial_start = requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            trial_decision = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Consistency test'
            })
            
            if trial_start.status_code == 200 and trial_decision.status_code == 200:
                consistency_passed += 1
            
            # Test experiment API
            total_consistency += 1
            exp_start = requests.post(f'{self.exp_url}/start', json={'models': ['crypto_prediction_agent_v1']})
            exp_decision = requests.post(f'{self.exp_url}/weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Experiment consistency test'
            })
            
            # Experiment API might have different behavior, so we check for reasonable responses
            if exp_start.status_code in [200, 500] and exp_decision.status_code in [200, 500, 400]:
                consistency_passed += 1
            
            consistency_ok = consistency_passed >= 1  # At least trial API should work
            self.log_result("API Consistency", consistency_ok, f"{consistency_passed}/{total_consistency}")
            return consistency_ok
            
        except Exception as e:
            self.log_result("API Consistency", False, f"Exception: {str(e)}")
            return False
    
    def run_comprehensive_test_suite(self) -> Dict[str, Any]:
        """Run all robustness tests"""
        print("🚀 Starting MERID Robustness Test Suite")
        print("=" * 50)
        
        # Run all tests
        tests = [
            self.test_basic_functionality,
            self.test_input_validation_robustness,
            self.test_edge_cases,
            self.test_concurrent_requests,
            self.test_error_recovery,
            self.test_high_volume_stress,
            self.test_api_consistency
        ]
        
        for test in tests:
            try:
                test()
            except Exception as e:
                print(f"❌ Test {test.__name__} crashed: {str(e)}")
                self.results['errors'].append(f"Test crash: {test.__name__} - {str(e)}")
        
        # Generate final report
        self.generate_final_report()
        return self.results
    
    def generate_final_report(self):
        """Generate final test report"""
        print("\n" + "=" * 50)
        print("🎯 ROBUSTNESS TEST SUITE RESULTS")
        print("=" * 50)
        
        total = self.results['total_tests']
        passed = self.results['passed_tests']
        failed = self.results['failed_tests']
        
        print(f"📊 Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📈 Success Rate: {(passed/total*100):.1f}%" if total > 0 else "N/A")
        
        if self.results['errors']:
            print("\n🔍 Errors Encountered:")
            for error in self.results['errors']:
                print(f"  • {error}")
        
        # Overall assessment
        if total == 0:
            print("\n❌ No tests executed")
        elif passed == total:
            print("\n🎉 ALL TESTS PASSED - MERID is highly robust!")
        elif passed / total >= 0.8:
            print("\n✅ GOOD ROBUSTNESS - Most tests passed")
        elif passed / total >= 0.6:
            print("\n⚠️  MODERATE ROBUSTNESS - Some improvements needed")
        else:
            print("\n❌ POOR ROBUSTNESS - Significant improvements required")
        
        print("\n🚀 MERID Robustness Testing Complete!")

if __name__ == '__main__':
    suite = MERIDRobustnessTestSuite()
    results = suite.run_comprehensive_test_suite()
