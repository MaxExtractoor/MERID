#!/usr/bin/env python3
"""
MERID Phase 0 Acceptance Test with Structlog
Enhanced test with structured logging and correlation tracking
"""

import json
import os
import sys
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.structlog_config import configure_logging, get_logger
from middleware.structlog_correlation import bind_test_context
import requests


class Phase0StructlogAcceptanceTest:
    """Phase 0 acceptance test with enhanced structlog integration"""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
        self.test_id = None
        self.correlation_id = None
        self.logger = None
        self.errors = []
        
        # Configure structured logging for tests
        os.environ["APP_ENV"] = "test"
        configure_logging()
    
    def run_test(self) -> bool:
        """Run complete acceptance test with structured logging"""
        # Generate test and correlation IDs
        self.test_id = f"phase0_acceptance_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.correlation_id = str(uuid.uuid4())
        
        # Bind test context to structlog
        bind_test_context(
            test_id=self.test_id,
            correlation_id=self.correlation_id,
            base_url=self.base_url
        )
        
        self.logger = get_logger("acceptance_test")
        
        self.logger.info("acceptance_test_started", 
                        test_id=self.test_id,
                        correlation_id=self.correlation_id,
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
            self.logger.error("acceptance_test_failed", 
                           test_id=self.test_id,
                           correlation_id=self.correlation_id,
                           error=str(e),
                           error_type=type(e).__name__)
            return False
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> requests.Response:
        """Make HTTP request with correlation headers and structured logging"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-Id": self.correlation_id,
            "X-Test-Id": self.test_id
        }
        
        self.logger.info("http_request_started",
                        method=method,
                        url=url,
                        has_data=data is not None,
                        headers=headers)
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, headers=headers)
            elif method.upper() == "POST":
                response = self.session.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            self.logger.info("http_request_completed",
                            method=method,
                            url=url,
                            status_code=response.status_code,
                            response_size=len(response.content),
                            response_headers=dict(response.headers))
            
            return response
            
        except Exception as e:
            self.logger.error("http_request_failed",
                            method=method,
                            url=url,
                            error=str(e),
                            error_type=type(e).__name__)
            raise
    
    def test_health_check(self):
        """Test server health check with structured logging"""
        self.logger.info("step_1_health_check_started")
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/health")
            
            if response.status_code == 200:
                self.logger.info("health_check_passed",
                                response_body=response.json())
            else:
                error_msg = f"Health check failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("health_check_failed",
                                status_code=response.status_code,
                                response_body=response.text)
                
        except Exception as e:
            error_msg = f"Health check exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("health_check_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def test_start_trial(self):
        """Test trial start with structured logging"""
        self.logger.info("step_2_start_trial_started")
        
        try:
            response = self._make_request("POST", "/api/v1/phase0/trial/start", data={})
            
            if response.status_code == 200:
                self.logger.info("trial_start_passed",
                                response_body=response.json())
            else:
                error_msg = f"Trial start failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("trial_start_failed",
                                status_code=response.status_code,
                                response_body=response.text)
                
        except Exception as e:
            error_msg = f"Trial start exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("trial_start_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def test_record_decision(self):
        """Test decision recording with detailed structured logging"""
        self.logger.info("step_3_record_decision_started")
        
        decision_payload = {
            "model_id": "crypto_prediction_agent_v1",
            "human_decision": "hold",
            "decision_reason": "Acceptance test decision without performance data"
        }
        
        try:
            response = self._make_request("POST", "/api/v1/phase0/trial/record-weekly-decision", data=decision_payload)
            
            self.logger.info("decision_recording_attempted",
                            model_id=decision_payload["model_id"],
                            human_decision=decision_payload["human_decision"],
                            decision_reason=decision_payload["decision_reason"],
                            has_performance_data=False,
                            status_code=response.status_code,
                            response_body=response.text)
            
            if response.status_code == 200:
                self.logger.info("decision_recording_passed",
                                response_body=response.json())
            else:
                error_msg = f"Decision recording failed with status {response.status_code}: {response.text}"
                self.errors.append(error_msg)
                self.logger.error("decision_recording_failed",
                                status_code=response.status_code,
                                response_body=response.text,
                                error_details=response.json() if response.headers.get("content-type", "").startswith("application/json") else None)
                
        except Exception as e:
            error_msg = f"Decision recording exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("decision_recording_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def test_trial_status(self):
        """Test trial status verification with structured logging"""
        self.logger.info("step_4_trial_status_started")
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/status")
            
            if response.status_code == 200:
                status_data = response.json()
                total_decisions = status_data.get("status", {}).get("current_metrics", {}).get("total_decisions", 0)
                
                self.logger.info("trial_status_retrieved",
                                total_decisions=total_decisions,
                                status_data=status_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_persisted_in_status",
                                    total_decisions=total_decisions)
                else:
                    error_msg = "total_decisions is 0 after recording decision"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_persisted_in_status",
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Trial status failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("trial_status_failed",
                                status_code=response.status_code,
                                response_body=response.text)
                
        except Exception as e:
            error_msg = f"Trial status exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("trial_status_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def test_alignment_analysis(self):
        """Test alignment analysis verification with structured logging"""
        self.logger.info("step_5_alignment_analysis_started")
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/alignment-analysis")
            
            if response.status_code == 200:
                alignment_data = response.json()
                total_decisions = alignment_data.get("total_decisions", 0)
                
                self.logger.info("alignment_analysis_retrieved",
                                total_decisions=total_decisions,
                                alignment_data=alignment_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_appears_in_alignment",
                                    total_decisions=total_decisions)
                else:
                    error_msg = "alignment-analysis shows 0 decisions"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_in_alignment",
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Alignment analysis failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("alignment_analysis_failed",
                                status_code=response.status_code,
                                response_body=response.text)
                
        except Exception as e:
            error_msg = f"Alignment analysis exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("alignment_analysis_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def test_contract_compliance(self):
        """Test contract compliance verification with structured logging"""
        self.logger.info("step_6_contract_compliance_started")
        
        try:
            response = self._make_request("GET", "/api/v1/phase0/trial/contract-compliance")
            
            if response.status_code == 200:
                compliance_data = response.json()
                total_decisions = compliance_data.get("total_decisions", 0)
                
                self.logger.info("contract_compliance_retrieved",
                                total_decisions=total_decisions,
                                compliance_data=compliance_data)
                
                if total_decisions > 0:
                    self.logger.info("decision_appears_in_compliance",
                                    total_decisions=total_decisions)
                else:
                    error_msg = "contract-compliance shows 0 decisions"
                    self.errors.append(error_msg)
                    self.logger.error("decision_not_in_compliance",
                                    total_decisions=total_decisions)
            else:
                error_msg = f"Contract compliance failed with status {response.status_code}"
                self.errors.append(error_msg)
                self.logger.error("contract_compliance_failed",
                                status_code=response.status_code,
                                response_body=response.text)
                
        except Exception as e:
            error_msg = f"Contract compliance exception: {str(e)}"
            self.errors.append(error_msg)
            self.logger.error("contract_compliance_exception",
                            error=str(e),
                            error_type=type(e).__name__)
    
    def report_results(self):
        """Report final test results with structured logging"""
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
    test = Phase0StructlogAcceptanceTest()
    success = test.run_test()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
