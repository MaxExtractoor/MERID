#!/usr/bin/env python3

import requests
import time
import json
from typing import Dict, Any, List

class RobustnessValidationTest:
    """
    Comprehensive validation test for MERID robustness improvements
    """
    
    def __init__(self):
        self.base_url = 'http://localhost:8001/api/v1/phase0/trial'
        self.exp_url = 'http://localhost:8001/api/v1/phase0/experiment'
        self.results = {
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': 0,
            'improvements_validated': []
        }
    
    def log_result(self, test_name: str, passed: bool, details: str = "", improvement: str = ""):
        """Log test result"""
        self.results['total_tests'] += 1
        if passed:
            self.results['passed_tests'] += 1
            print(f"✅ {test_name}: PASSED {details}")
            if improvement:
                self.results['improvements_validated'].append(improvement)
        else:
            self.results['failed_tests'] += 1
            print(f"❌ {test_name}: FAILED {details}")
    
    def start_fresh_trial(self) -> bool:
        """Start a fresh trial for testing"""
        try:
            start_resp = requests.post(f'{self.base_url}/start', json={'duration_weeks': 6})
            return start_resp.status_code == 200
        except:
            return False
    
    def test_enhanced_error_handling(self) -> bool:
        """Test enhanced error handling improvements"""
        print("\n=== Enhanced Error Handling Test ===")
        
        try:
            if not self.start_fresh_trial():
                self.log_result("Error Handling Setup", False, "Failed to start trial")
                return False
            
            error_handling_passed = 0
            total_error_tests = 0
            
            # Test 1: Empty model ID
            total_error_tests += 1
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': '',
                'human_decision': 'hold',
                'decision_reason': 'Test empty model ID'
            })
            if resp.status_code == 400 and "cannot be empty" in resp.text:
                error_handling_passed += 1
                self.log_result("Empty Model ID", True, "Properly rejected", "Input validation")
            
            # Test 2: Empty decision
            total_error_tests += 1
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': '',
                'decision_reason': 'Test empty decision'
            })
            if resp.status_code == 400 and "cannot be empty" in resp.text:
                error_handling_passed += 1
                self.log_result("Empty Decision", True, "Properly rejected", "Input validation")
            
            # Test 3: Empty reason
            total_error_tests += 1
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': ''
            })
            if resp.status_code == 400 and "cannot be empty" in resp.text:
                error_handling_passed += 1
                self.log_result("Empty Reason", True, "Properly rejected", "Input validation")
            
            # Test 4: Invalid decision with detailed error
            total_error_tests += 1
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'invalid_decision',
                'decision_reason': 'Test invalid decision'
            })
            if resp.status_code == 422 and "Valid options" in resp.text:
                error_handling_passed += 1
                self.log_result("Invalid Decision", True, "Detailed error message", "Error messaging")
            
            error_handling_ok = error_handling_passed == total_error_tests
            self.log_result("Enhanced Error Handling", error_handling_ok, 
                          f"{error_handling_passed}/{total_error_tests} tests passed")
            return error_handling_ok
            
        except Exception as e:
            self.log_result("Enhanced Error Handling", False, f"Exception: {str(e)}")
            return False
    
    def test_case_insensitive_validation(self) -> bool:
        """Test case-insensitive decision validation"""
        print("\n=== Case-Insensitive Validation Test ===")
        
        try:
            if not self.start_fresh_trial():
                self.log_result("Case Validation Setup", False, "Failed to start trial")
                return False
            
            case_passed = 0
            total_case_tests = 0
            
            # Test case variants
            case_variants = [
                ('PROMOTE', 'promote'),
                ('Demote', 'demote'),
                ('HOLD', 'hold'),
                ('Suspend', 'suspend'),
                ('retire', 'retire')
            ]
            
            for input_case, expected_normalized in case_variants:
                total_case_tests += 1
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': input_case,
                    'decision_reason': f'Test case: {input_case}'
                })
                
                if resp.status_code == 200:
                    # Check if decision was normalized
                    decision_data = resp.json().get('decision', {})
                    actual_decision = decision_data.get('human_decision', '')
                    if actual_decision == expected_normalized:
                        case_passed += 1
                        self.log_result(f"Case {input_case}", True, f"Normalized to {expected_normalized}", "Case-insensitive validation")
                    else:
                        self.log_result(f"Case {input_case}", False, f"Expected {expected_normalized}, got {actual_decision}")
                else:
                    self.log_result(f"Case {input_case}", False, f"Status {resp.status_code}")
            
            case_ok = case_passed == total_case_tests
            self.log_result("Case-Insensitive Validation", case_ok, f"{case_passed}/{total_case_tests}")
            return case_ok
            
        except Exception as e:
            self.log_result("Case-Insensitive Validation", False, f"Exception: {str(e)}")
            return False
    
    def test_edge_case_handling(self) -> bool:
        """Test edge case handling improvements"""
        print("\n=== Edge Case Handling Test ===")
        
        try:
            if not self.start_fresh_trial():
                self.log_result("Edge Case Setup", False, "Failed to start trial")
                return False
            
            edge_passed = 0
            total_edge_tests = 0
            
            # Test 1: Long decision reason
            total_edge_tests += 1
            long_reason = 'A' * 1000
            resp = requests.post(
                f'{self.base_url}/record-weekly-decision', 
                json={
                    'model_id': 'crypto_prediction_agent_v1',
                    'human_decision': 'hold',
                    'decision_reason': long_reason
                }
            )
            if resp.status_code == 200:
                edge_passed += 1
                self.log_result("Long Reason", True, "1000 chars accepted", "Edge case handling")
            
            # Test 2: Special characters
            total_edge_tests += 1
            special_reason = 'Decision with symbols: !@#$%^&*()_+-=[]{}|;:,.<>? and unicode: αβγδε'
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': special_reason
            })
            if resp.status_code == 200:
                edge_passed += 1
                self.log_result("Special Characters", True, "Unicode and symbols accepted", "Edge case handling")
            
            # Test 3: Newlines and tabs
            total_edge_tests += 1
            multiline_reason = 'Decision with\nnewlines\nand\ttabs\tincluded'
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': multiline_reason
            })
            if resp.status_code == 200:
                edge_passed += 1
                self.log_result("Multiline Reason", True, "Newlines and tabs accepted", "Edge case handling")
            
            edge_ok = edge_passed == total_edge_tests
            self.log_result("Edge Case Handling", edge_ok, f"{edge_passed}/{total_edge_tests}")
            return edge_ok
            
        except Exception as e:
            self.log_result("Edge Case Handling", False, f"Exception: {str(e)}")
            return False
    
    def test_resilience_under_load(self) -> bool:
        """Test system resilience under moderate load"""
        print("\n=== Resilience Under Load Test ===")
        
        try:
            if not self.start_fresh_trial():
                self.log_result("Load Test Setup", False, "Failed to start trial")
                return False
            
            load_passed = 0
            total_load_tests = 0
            
            # Test 1: Sequential requests
            total_load_tests += 1
            sequential_success = 0
            for i in range(10):
                model = 'crypto_prediction_agent_v1' if i % 2 == 0 else 'arbitrage_analyst_v2'
                decision = ['promote', 'demote', 'hold', 'suspend', 'retire'][i % 5]
                
                resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                    'model_id': model,
                    'human_decision': decision,
                    'decision_reason': f'Sequential test #{i+1}'
                })
                
                if resp.status_code == 200:
                    sequential_success += 1
                elif resp.status_code == 400:
                    # Stop if we hit policy issues
                    break
            
            if sequential_success >= 5:  # At least half should succeed
                load_passed += 1
                self.log_result("Sequential Load", True, f"{sequential_success}/10 successful", "Load resilience")
            
            # Test 2: Error recovery
            total_load_tests += 1
            # Make invalid request
            invalid_resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'invalid',
                'decision_reason': 'Test recovery'
            })
            
            # Make valid request after error
            valid_resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Recovery test'
            })
            
            if invalid_resp.status_code == 422 and valid_resp.status_code == 200:
                load_passed += 1
                self.log_result("Error Recovery", True, "Recovered after invalid request", "Error resilience")
            
            load_ok = load_passed == total_load_tests
            self.log_result("Resilience Under Load", load_ok, f"{load_passed}/{total_load_tests}")
            return load_ok
            
        except Exception as e:
            self.log_result("Resilience Under Load", False, f"Exception: {str(e)}")
            return False
    
    def test_improved_logging_and_observability(self) -> bool:
        """Test improved logging and observability"""
        print("\n=== Logging and Observability Test ===")
        
        try:
            if not self.start_fresh_trial():
                self.log_result("Logging Setup", False, "Failed to start trial")
                return False
            
            logging_passed = 0
            total_logging_tests = 0
            
            # Test 1: Detailed response data
            total_logging_tests += 1
            resp = requests.post(f'{self.base_url}/record-weekly-decision', json({
                'model_id': 'crypto_prediction_agent_v1',
                'human_decision': 'hold',
                'decision_reason': 'Test detailed response'
            })
            
            if resp.status_code == 200:
                response_data = resp.json()
                analysis = response_data.get('analysis', {})
                
                # Check for enhanced response fields
                if (analysis.get('metrics_state') and 
                    'fallback_used' in analysis and
                    response_data.get('message')):
                    logging_passed += 1
                    self.log_result("Detailed Response", True, "Enhanced response data", "Observability")
            
            # Test 2: Status endpoint metrics
            total_logging_tests += 1
            status_resp = requests.get(f'{self.base_url}/status')
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                metrics = status_data.get('status', {}).get('current_metrics', {})
                
                # Check for comprehensive metrics
                if all(key in metrics for key in ['total_decisions', 'weekly_decisions', 'alignment_rate', 'contract_compliance_rate']):
                    logging_passed += 1
                    self.log_result("Status Metrics", True, "Comprehensive metrics available", "Observability")
            
            logging_ok = logging_passed == total_logging_tests
            self.log_result("Logging and Observability", logging_ok, f"{logging_passed}/{total_logging_tests}")
            return logging_ok
            
        except Exception as e:
            self.log_result("Logging and Observability", False, f"Exception: {str(e)}")
            return False
    
    def run_robustness_validation(self) -> Dict[str, Any]:
        """Run comprehensive robustness validation"""
        print("🚀 Starting MERID Robustness Validation Test")
        print("=" * 60)
        print("Testing all robustness improvements implemented")
        print("=" * 60)
        
        # Run all validation tests
        tests = [
            self.test_enhanced_error_handling,
            self.test_case_insensitive_validation,
            self.test_edge_case_handling,
            self.test_resilience_under_load,
            self.test_improved_logging_and_observability
        ]
        
        for test in tests:
            try:
                test()
                time.sleep(0.5)  # Brief pause between tests
            except Exception as e:
                print(f"❌ Test {test.__name__} crashed: {str(e)}")
        
        # Generate final report
        self.generate_validation_report()
        return self.results
    
    def generate_validation_report(self):
        """Generate validation report"""
        print("\n" + "=" * 60)
        print("🎯 ROBUSTNESS VALIDATION RESULTS")
        print("=" * 60)
        
        total = self.results['total_tests']
        passed = self.results['failed_tests']
        failed = self.results['failed_tests']
        
        print(f"📊 Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📈 Success Rate: {(passed/total*100):.1f}%" if total > 0 else "N/A")
        
        if self.results['improvements_validated']:
            print("\n🔧 Robustness Improvements Validated:")
            for improvement in set(self.results['improvements_validated']):
                print(f"  ✅ {improvement}")
        
        # Overall assessment
        if total == 0:
            print("\n❌ No tests executed")
        elif passed == total:
            print("\n🎉 ALL ROBUSTNESS IMPROVEMENTS VALIDATED!")
            print("✅ MERID is now highly robust and production-ready")
        elif passed / total >= 0.8:
            print("\n✅ MOST IMPROVEMENTS VALIDATED!")
            print("✅ MERID robustness significantly improved")
        elif passed / total >= 0.6:
            print("\n⚠️  PARTIAL IMPROVEMENTS VALIDATED")
            print("⚠️  Some robustness improvements need more work")
        else:
            print("\n❌ LIMITED IMPROVEMENTS VALIDATED")
            print("❌ Significant robustness work still needed")
        
        print("\n🚀 MERID Robustness Validation Complete!")

if __name__ == '__main__':
    validator = RobustnessValidationTest()
    results = validator.run_robustness_validation()
