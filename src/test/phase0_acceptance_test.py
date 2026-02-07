#!/usr/bin/env python3
"""
MERID Phase 0 Acceptance Test with Structured Logging
Tests decision persistence with correlation ID tracing
"""

import json
import requests
import sys
import os
from datetime import datetime
from typing import Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.structured_logging import correlation_context, StructuredLogger


class Phase0AcceptanceTest:
    """Phase 0 acceptance test with structured logging"""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
        self.test_id = None
        self.correlation_id = None
        self.logger = None
        self.errors = []
    
    def run_test(self) -> bool:
        """Run complete acceptance test"""
        with correlation_context() as (test_id, correlation_id, logger):
            self.test_id = test_id
            self.correlation_id = correlation_id
            self.logger = logger
            
            logger.info("acceptance_test_started", 
                       test_id=test_id,
                       correlation_id=correlation_id,
                       base_url=self.base_url)
            
            try:
                # Step 1: Health Check
                self.test_health_check()
                
                # Step 2: Start Trial
                self.test_start_trial()
                
                # Step 3: Record Decision
                self.test_record_decision()
                
                # Step 4: Verify Trial Status
                self.test_trial_status()
                
                # Step 5: Verify Alignment Analysis
                self.test_alignment_analysis()
                
                # Step 6: Verify Contract Compliance
                self.test_contract_compliance()
                
                # Step 7: Report Results
                self.report_results()
                
                return len(self.errors) == 0
                
            except Exception as e:
                logger.error("acceptance_test_failed", 
                           test_id=test_id,
                           correlation_id=correlation_id,
                           error=str(e),
                           error_type=type(e).__name__)
                return False
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> requests.Response:
        """Make HTTP request with correlation headers"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-Id": self.correlation_id,
            "X-Test-Id": self.test_id
        }
        
        self.logger.info("http_request_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id,
                        method=method,
                        url=url,
                        has_data=data is not None)
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, headers=headers)
            elif method.upper() == "POST":
                response = self.session.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            self.logger.info("http_request_completed",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            method=method,
                            url=url,
                            status_code=response.status_code,
                            response_size=len(response.content))
            
            return response
            
        except Exception as e:
            self.logger.error("http_request_failed",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            method=method,
                            url=url,
                            error=str(e))
            raise
    
    def test_health_check(self):
        """Test server health check"""
        self.logger.info("step_1_health_check_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/health")
            
            if response.status_code == 200:
                self.logger.info("health_check_passed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                response=response.json())
            else:
                error_msg = f"Health check failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("health_check_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Health check exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("health_check_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def test_start_trial(self):
        """Test trial start"""
        self.logger.info("step_2_start_trial_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        try:
            response = self._make_request("POST", "/api/v1/phase0/trial/start", data={})
            
            if response.status_code == 200:
                self.logger.info("trial_start_passed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                response=response.json())
            else:
                error_msg = f"Trial start failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("trial_start_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Trial start exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("trial_start_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def test_record_decision(self):
        """Test decision recording"""
        self.logger.info("step_3_record_decision_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        decision_payload = {
            "model_id": "crypto_prediction_agent_v1",
            "human_decision": "hold",
            "decision_reason": "Acceptance test decision without performance data"
        }
        
        try:
            response = self._make_request("POST", "/api/v1/phase0/trial/record-weekly-decision", data=decision_payload)
            
            self.logger.info("decision_recording_attempted",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            payload=decision_payload,
                            status_code=response.status_code,
                            response=response.text)
            
            if response.status_code == 200:
                self.logger.info("decision_recording_passed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                response=response.json())
            else:
                error_msg = f"Decision recording failed with status {response.status_code}: {response.text}"
                self.errors.append(error_msg)
                self.logger.error("decision_recording_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Decision recording exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("decision_recording_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def test_trial_status(self):
        """Test trial status verification"""
        self.logger.info("step_4_trial_status_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/status")
            
            if response.status_code == 200:
                status_data = response.json()
                total_decisions = status_data.get("status", {}).get("current_metrics", {}).get("total_decisions", 0)
                
                self.logger.info("trial_status_retrieved",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                total_decisions=total_decisions,
                                status_data=status_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_persisted_in_status",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
                else:
                    error_msg = "total_decisions is 0 after recording decision"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_persisted_in_status",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Trial status failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("trial_status_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Trial status exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("trial_status_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def test_alignment_analysis(self):
        """Test alignment analysis verification"""
        self.logger.info("step_5_alignment_analysis_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/alignment-analysis")
            
            if response.status_code == 200:
                alignment_data = response.json()
                total_decisions = alignment_data.get("total_decisions", 0)
                
                self.logger.info("alignment_analysis_retrieved",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                total_decisions=total_decisions,
                                alignment_data=alignment_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_appears_in_alignment",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
                else:
                    error_msg = "alignment-analysis shows 0 decisions"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_in_alignment",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Alignment analysis failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("alignment_analysis_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Alignment analysis exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("alignment_analysis_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def test_contract_compliance(self):
        """Test contract compliance verification"""
        self.logger.info("step_6_contract_compliance_started",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id)
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/contract-compliance")
            
            if response.status_code == 200:
                compliance_data = response.json()
                total_decisions = compliance_data.get("total_decisions", 0)
                
                self.logger.info("contract_compliance_retrieved",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                total_decisions=total_decisions,
                                compliance_data=compliance_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_appears_in_compliance",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
                else:
                    error_msg = "contract-compliance shows 0 decisions"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_in_compliance",
                                    test_id=self.test_id,
                                    correlation_id=self.correlation_id,
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Contract compliance failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("contract_compliance_failed",
                                test_id=self.test_id,
                                correlation_id=self.correlation_id,
                                status_code=response.status_code,
                                response=response.text)
                
        except Exception as e:
            error_msg = f"Contract compliance exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("contract_compliance_exception",
                            test_id=self.test_id,
                            correlation_id=self.correlation_id,
                            error=str(e))
    
    def report_results(self):
        """Report final test results"""
        self.logger.info("acceptance_test_completed",
                        test_id=self.test_id,
                        correlation_id=self.correlation_id,
                        total_errors=len(self.errors),
                        errors=self.errors)
        
        if len(self.errors) == 0:
            print("✅ PHASE 0 ACCEPTANCE TEST PASSED")
            print("All persistence assertions passed")
        else:
            print("❌ PHASE 0 ACCEPTANCE TEST FAILED")
            print("Errors:")
            for error in self.errors:
                print(f"  - {error}")


def main():
    """Main entry point"""
    test = Phase0AcceptanceTest()
    success = test.run_test()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
