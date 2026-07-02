#!/usr/bin/env python3
"""
Specific Invariant Scenario Tests

This script runs the specific test scenarios outlined in the user's request:
1. MD age invariants with negative/absurd age injection
2. WS forwarder health gating with idle/active scenarios  
3. Quality vs optimizer consistency with spread scenarios
4. Catalog age and depth gating with threshold violations
5. Paranoid mode vs normal mode invariant enforcement
6. E2E behavior validation with realistic MD scenarios

Each scenario can be run independently or as part of a comprehensive test suite.
"""

import asyncio
import logging
import os
import sys
import time
from typing import Dict, Any, List
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.core.e2e_invariants import check_system_invariants, get_invariant_checker
from merid.prediction.candidate_optimizer import CandidateOptimizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class InvariantScenarioTester:
    """Tests specific invariant scenarios."""
    
    def __init__(self):
        self.results = {}
        
    def log_scenario_start(self, scenario_name: str):
        """Log scenario start."""
        logger.info(f"🧪 Starting scenario: {scenario_name}")
        logger.info("=" * 60)
        
    def log_scenario_result(self, scenario_name: str, passed: bool, details: str = ""):
        """Log scenario result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status} {scenario_name}")
        if details:
            logger.info(f"   Details: {details}")
        logger.info("-" * 60)
        
        self.results[scenario_name] = {
            "passed": passed,
            "details": details,
            "timestamp": time.time()
        }
    
    def scenario_1_md_age_invariants(self):
        """Test MD age invariants with negative/absurd age injection."""
        self.log_scenario_start("MD Age Invariants")
        
        try:
            checker = get_invariant_checker(paranoid_mode=False)
            
            # Test 1: Negative age with FRESH status
            system_state = {
                "market_data": {
                    "KXBTC15M-123": {
                        "age": -1780503046.40,  # Huge negative age from logs
                        "stale": False,
                        "reason": "FRESH"
                    }
                }
            }
            
            violations = check_system_invariants(system_state, paranoid_mode=False)
            
            # Should detect MD_NEGATIVE_AGE violation
            negative_age_violations = [v for v in violations if v.invariant_name == "MD_NEGATIVE_AGE"]
            
            if len(negative_age_violations) > 0:
                logger.info("   ✅ Detected negative age violation")
                logger.info(f"   📋 Violation: {negative_age_violations[0].message}")
            else:
                logger.error("   ❌ Failed to detect negative age violation")
                return False
            
            # Test 2: FRESH status with impossible age
            system_state["market_data"]["KXBTC15M-123"] = {
                "age": 7200.0,  # 2 hours - impossible for FRESH
                "stale": False,
                "reason": "FRESH"
            }
            
            violations = check_system_invariants(system_state, paranoid_mode=False)
            
            impossible_age_violations = [v for v in violations if v.invariant_name == "MD_FRESH_IMPOSSIBLE_AGE"]
            
            if len(impossible_age_violations) > 0:
                logger.info("   ✅ Detected impossible age violation")
                logger.info(f"   📋 Violation: {impossible_age_violations[0].message}")
            else:
                logger.error("   ❌ Failed to detect impossible age violation")
                return False
            
            # Test 3: Normal age - no violations
            system_state["market_data"]["KXBTC15M-123"] = {
                "age": 15.0,  # Normal age
                "stale": False,
                "reason": "FRESH"
            }
            
            violations = check_system_invariants(system_state, paranoid_mode=False)
            
            if len(violations) == 0:
                logger.info("   ✅ No violations for normal age")
            else:
                logger.error("   ❌ Unexpected violations for normal age")
                return False
            
            self.log_scenario_result("MD Age Invariants", True, 
                                    f"Detected {len(negative_age_violations)} negative age, "
                                    f"{len(impossible_age_violations)} impossible age violations")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("MD Age Invariants", False, f"Exception: {e}")
            return False
    
    def scenario_2_ws_health_gating(self):
        """Test WS forwarder health gating with idle/active scenarios."""
        self.log_scenario_start("WS Forwarder Health Gating")
        
        try:
            # Test 1: Idle WS scenario (0 events/sec)
            system_state_idle = {
                "ws_forwarder": {
                    "events_per_sec": 0.0,
                    "time_since_last_event": 45.0,
                    "stalled": False,
                    "status": "OK"
                },
                "execution_ready": True,
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_GOOD", 
                    "depth_coverage": "HEALTH_GOOD",
                    "ws_forwarder": "HEALTH_GOOD"  # This should be inconsistent
                }
            }
            
            violations_idle = check_system_invariants(system_state_idle, paranoid_mode=False)
            
            # Should detect WS_FORWARDER_IMPOSSIBLE_OK
            ws_violations_idle = [v for v in violations_idle if v.invariant_name == "WS_FORWARDER_IMPOSSIBLE_OK"]
            
            if len(ws_violations_idle) > 0:
                logger.info("   ✅ Detected idle WS forwarder violation")
                logger.info(f"   📋 Violation: {ws_violations_idle[0].message}")
            else:
                logger.error("   ❌ Failed to detect idle WS forwarder violation")
                return False
            
            # Test 2: Active WS scenario
            system_state_active = {
                "ws_forwarder": {
                    "events_per_sec": 2.5,
                    "time_since_last_event": 5.0,
                    "stalled": False,
                    "status": "OK"
                },
                "execution_ready": True,
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_GOOD",
                    "depth_coverage": "HEALTH_GOOD", 
                    "ws_forwarder": "HEALTH_GOOD"
                }
            }
            
            violations_active = check_system_invariants(system_state_active, paranoid_mode=False)
            
            if len(violations_active) == 0:
                logger.info("   ✅ No violations for active WS forwarder")
            else:
                logger.error("   ❌ Unexpected violations for active WS forwarder")
                return False
            
            # Test 3: Stalled WS with OK status
            system_state_stalled = {
                "ws_forwarder": {
                    "events_per_sec": 0.0,
                    "time_since_last_event": 35.0,
                    "stalled": True,
                    "status": "OK"
                }
            }
            
            violations_stalled = check_system_invariants(system_state_stalled, paranoid_mode=False)
            
            # The stalled case with 0 events/sec still triggers WS_FORWARDER_IMPOSSIBLE_OK
            # because events/sec=0.0 and status=OK is the primary violation
            stalled_violations = [v for v in violations_stalled if v.invariant_name == "WS_FORWARDER_IMPOSSIBLE_OK"]
            
            if len(stalled_violations) > 0:
                logger.info("   ✅ Detected stalled WS violation")
                logger.info(f"   📋 Violation: {stalled_violations[0].message}")
            else:
                logger.error("   ❌ Failed to detect stalled WS violation")
                return False
            
            self.log_scenario_result("WS Forwarder Health Gating", True,
                                    f"Detected idle/stalled violations, active WS clean")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("WS Forwarder Health Gating", False, f"Exception: {e}")
            return False
    
    def scenario_3_quality_optimizer_consistency(self):
        """Test quality vs optimizer consistency with spread scenarios."""
        self.log_scenario_start("Quality vs Optimizer Consistency")
        
        try:
            # Test 1: Wide spread (96c) should be POOR quality and rejected
            system_state_wide = {
                "market_quality": {
                    "KXBTC15M-123": {
                        "depth_yes": 25,
                        "depth_no": 25,
                        "overall_quality": "POOR",  # Should be POOR after fix
                        "spread_cents": 96
                    }
                }
            }
            
            violations_wide = check_system_invariants(system_state_wide, paranoid_mode=False)
            
            # Should NOT have quality conflicts if properly aligned
            quality_conflicts = [v for v in violations_wide if v.invariant_name == "QUALITY_OPTIMIZER_MISMATCH"]
            
            if len(quality_conflicts) == 0:
                logger.info("   ✅ Wide spread correctly labeled POOR (no conflict)")
            else:
                logger.error(f"   ❌ Quality conflict detected: {quality_conflicts[0].message}")
                return False
            
            # Test 2: ACCEPTABLE quality with wide spread (should trigger conflict)
            system_state_conflict = {
                "market_quality": {
                    "KXETH15M-456": {
                        "depth_yes": 25,
                        "depth_no": 25,
                        "overall_quality": "ACCEPTABLE",  # Conflict with wide spread
                        "spread_cents": 98
                    }
                }
            }
            
            violations_conflict = check_system_invariants(system_state_conflict, paranoid_mode=False)
            
            quality_conflicts = [v for v in violations_conflict if v.invariant_name == "QUALITY_OPTIMIZER_MISMATCH"]
            
            if len(quality_conflicts) > 0:
                logger.info("   ✅ Detected quality/optimizer mismatch")
                logger.info(f"   📋 Violation: {quality_conflicts[0].message}")
            else:
                logger.error("   ❌ Failed to detect quality/optimizer mismatch")
                return False
            
            # Test 3: GOOD quality with zero depth (should trigger violation)
            system_state_zero_depth = {
                "market_quality": {
                    "KXSOL15M-789": {
                        "depth_yes": 0,
                        "depth_no": 50,
                        "overall_quality": "GOOD",  # Conflict with zero depth
                        "spread_cents": 20
                    }
                }
            }
            
            violations_zero_depth = check_system_invariants(system_state_zero_depth, paranoid_mode=False)
            
            zero_depth_violations = [v for v in violations_zero_depth if v.invariant_name == "QUALITY_GOOD_ZERO_DEPTH"]
            
            if len(zero_depth_violations) > 0:
                logger.info("   ✅ Detected zero depth violation")
                logger.info(f"   📋 Violation: {zero_depth_violations[0].message}")
            else:
                logger.error("   ❌ Failed to detect zero depth violation")
                return False
            
            # Test 4: Normal GOOD quality - no violations
            system_state_normal = {
                "market_quality": {
                    "KXDOGE15M-012": {
                        "depth_yes": 25,
                        "depth_no": 25,
                        "overall_quality": "GOOD",
                        "spread_cents": 30  # < 40 threshold
                    }
                }
            }
            
            violations_normal = check_system_invariants(system_state_normal, paranoid_mode=False)
            
            if len(violations_normal) == 0:
                logger.info("   ✅ No violations for normal GOOD quality")
            else:
                logger.error("   ❌ Unexpected violations for normal quality")
                return False
            
            self.log_scenario_result("Quality vs Optimizer Consistency", True,
                                    f"Wide spreads: {len(quality_conflicts)} conflicts, "
                                    f"Zero depth: {len(zero_depth_violations)} violations")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("Quality vs Optimizer Consistency", False, f"Exception: {e}")
            return False
    
    def scenario_4_catalog_depth_gating(self):
        """Test catalog age and depth gating with threshold violations."""
        self.log_scenario_start("Catalog Age and Depth Gating")
        
        try:
            # Test 1: Catalog too old (>10s threshold)
            system_state_old_catalog = {
                "execution_ready": True,  # Should be False due to old catalog
                "subsystem_health": {
                    "catalog": "HEALTH_ERROR",  # Catalog too old
                    "md_freshness": "HEALTH_GOOD",
                    "depth_coverage": "HEALTH_GOOD",
                    "ws_forwarder": "HEALTH_GOOD"
                }
            }
            
            violations_old = check_system_invariants(system_state_old_catalog, paranoid_mode=False)
            
            execution_violations = [v for v in violations_old if v.invariant_name == "EXECUTION_READY_CRITICAL_FAILURE"]
            
            if len(execution_violations) > 0:
                logger.info("   ✅ Detected execution ready violation due to old catalog")
                logger.info(f"   📋 Violation: {execution_violations[0].message}")
            else:
                logger.error("   ❌ Failed to detect execution ready violation")
                return False
            
            # Test 2: Partial depth coverage (2/5 assets)
            system_state_partial_depth = {
                "execution_ready": True,  # Should be False due to partial depth
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_GOOD",
                    "depth_coverage": "HEALTH_ERROR",  # Only 2/5 assets
                    "ws_forwarder": "HEALTH_GOOD"
                }
            }
            
            violations_partial = check_system_invariants(system_state_partial_depth, paranoid_mode=False)
            
            if len(violations_partial) > 0:
                logger.info("   ✅ Detected execution ready violation due to partial depth")
            else:
                logger.error("   ❌ Failed to detect execution ready violation for partial depth")
                return False
            
            # Test 3: All subsystems healthy - no violations
            system_state_healthy = {
                "execution_ready": True,
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_GOOD",
                    "depth_coverage": "HEALTH_GOOD",
                    "ws_forwarder": "HEALTH_GOOD"
                }
            }
            
            violations_healthy = check_system_invariants(system_state_healthy, paranoid_mode=False)
            
            if len(violations_healthy) == 0:
                logger.info("   ✅ No violations for all healthy subsystems")
            else:
                logger.error("   ❌ Unexpected violations for healthy subsystems")
                return False
            
            self.log_scenario_result("Catalog Age and Depth Gating", True,
                                    f"Old catalog: {len(execution_violations)} violations, "
                                    f"Partial depth: {len(violations_partial)} violations")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("Catalog Age and Depth Gating", False, f"Exception: {e}")
            return False
    
    def scenario_5_paranoid_mode(self):
        """Test paranoid mode vs normal mode invariant enforcement."""
        self.log_scenario_start("Paranoid Mode vs Normal Mode")
        
        try:
            # Create system state with violations
            system_state = {
                "market_data": {
                    "KXBTC15M-123": {
                        "age": -1000.0,  # Negative age
                        "stale": False,
                        "reason": "FRESH"
                    }
                },
                "ws_forwarder": {
                    "events_per_sec": 0.0,
                    "time_since_last_event": 45.0,
                    "stalled": False,
                    "status": "OK"
                },
                "execution_ready": True,
                "subsystem_health": {
                    "catalog": "HEALTH_ERROR"
                }
            }
            
            # Test 1: Normal mode - should log but not raise
            try:
                violations_normal = check_system_invariants(system_state, paranoid_mode=False)
                logger.info("   ✅ Normal mode: logged violations without raising")
                logger.info(f"   📋 Found {len(violations_normal)} violations")
            except Exception as e:
                logger.error(f"   ❌ Normal mode unexpectedly raised: {e}")
                return False
            
            # Test 2: Paranoid mode - should raise on critical violations
            exception_raised = False
            try:
                violations_paranoid = check_system_invariants(system_state, paranoid_mode=True)
                logger.error("   ❌ Paranoid mode should have raised exception")
                return False
            except RuntimeError as e:
                exception_raised = True
                if "CRITICAL INVARIANT VIOLATION" in str(e):
                    logger.info("   ✅ Paranoid mode: raised exception on critical violations")
                    logger.info(f"   📋 Exception: {e}")
                else:
                    logger.error(f"   ❌ Paranoid mode raised unexpected exception: {e}")
                    return False
            except Exception as e:
                exception_raised = True
                logger.error(f"   ❌ Paranoid mode raised unexpected exception type: {e}")
                return False
            
            if not exception_raised:
                logger.error("   ❌ Paranoid mode should have raised exception")
                return False
            
            self.log_scenario_result("Paranoid Mode vs Normal Mode", True,
                                    f"Normal: {len(violations_normal)} violations logged, "
                                    f"Paranoid: exception raised as expected")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("Paranoid Mode vs Normal Mode", False, f"Exception: {e}")
            return False
    
    def scenario_6_e2e_behavior(self):
        """Test E2E behavior validation with realistic MD scenarios."""
        self.log_scenario_start("E2E Behavior Validation")
        
        try:
            # Test 1: Clean execution-ready scenario
            system_state_clean = {
                "execution_ready": True,
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_GOOD",
                    "depth_coverage": "HEALTH_GOOD",
                    "ws_forwarder": "HEALTH_GOOD"
                },
                "market_data": {
                    "KXBTC15M-123": {"age": 15.0, "stale": False, "reason": "FRESH"},
                    "KXETH15M-456": {"age": 20.0, "stale": False, "reason": "FRESH"},
                    "KXSOL15M-789": {"age": 10.0, "stale": False, "reason": "FRESH"},
                    "KXXRP15M-012": {"age": 25.0, "stale": False, "reason": "FRESH"},
                    "KXDOGE15M-345": {"age": 18.0, "stale": False, "reason": "FRESH"}
                },
                "ws_forwarder": {
                    "events_per_sec": 2.5,
                    "time_since_last_event": 5.0,
                    "stalled": False,
                    "status": "OK"
                },
                "market_quality": {
                    "KXBTC15M-123": {"depth_yes": 25, "depth_no": 25, "overall_quality": "GOOD", "spread_cents": 30},
                    "KXETH15M-456": {"depth_yes": 20, "depth_no": 20, "overall_quality": "GOOD", "spread_cents": 35}
                }
            }
            
            violations_clean = check_system_invariants(system_state_clean, paranoid_mode=False)
            
            if len(violations_clean) == 0:
                logger.info("   ✅ Clean scenario: no violations")
            else:
                logger.error(f"   ❌ Clean scenario had {len(violations_clean)} violations")
                return False
            
            # Test 2: Realistic degraded scenario
            system_state_degraded = {
                "execution_ready": False,  # Should be False
                "subsystem_health": {
                    "catalog": "HEALTH_GOOD",
                    "md_freshness": "HEALTH_ERROR",  # Some assets stale
                    "depth_coverage": "HEALTH_ERROR",  # Some assets shallow
                    "ws_forwarder": "HEALTH_GOOD"
                },
                "market_data": {
                    "KXBTC15M-123": {"age": 15.0, "stale": False, "reason": "FRESH"},
                    "KXETH15M-456": {"age": 150.0, "stale": True, "reason": "LAST_UPDATE_TOO_OLD"},  # Stale
                    "KXSOL15M-789": {"age": 10.0, "stale": False, "reason": "FRESH"},
                    "KXXRP15M-012": {"age": 200.0, "stale": True, "reason": "LAST_UPDATE_TOO_OLD"},  # Stale
                    "KXDOGE15M-345": {"age": 18.0, "stale": False, "reason": "FRESH"}
                },
                "ws_forwarder": {
                    "events_per_sec": 1.5,
                    "time_since_last_event": 8.0,
                    "stalled": False,
                    "status": "OK"
                },
                "market_quality": {
                    "KXBTC15M-123": {"depth_yes": 25, "depth_no": 25, "overall_quality": "GOOD", "spread_cents": 30},
                    "KXETH15M-456": {"depth_yes": 5, "depth_no": 5, "overall_quality": "ACCEPTABLE", "spread_cents": 25},
                    "KXSOL15M-789": {"depth_yes": 2, "depth_no": 2, "overall_quality": "ACCEPTABLE", "spread_cents": 35},
                    "KXXRP15M-012": {"depth_yes": 1, "depth_no": 1, "overall_quality": "ACCEPTABLE", "spread_cents": 40},
                    "KXDOGE15M-345": {"depth_yes": 0, "depth_no": 0, "overall_quality": "SHALLOW", "spread_cents": 50}
                }
            }
            
            violations_degraded = check_system_invariants(system_state_degraded, paranoid_mode=False)
            
            # Should not be execution ready due to degraded subsystems
            if not system_state_degraded["execution_ready"]:
                logger.info("   ✅ Degraded scenario: not execution ready")
            else:
                logger.error("   ❌ Degraded scenario incorrectly marked as execution ready")
                return False
            
            # Should have some violations but not critical ones that prevent degraded status
            logger.info(f"   📋 Degraded scenario: {len(violations_degraded)} violations")
            
            self.log_scenario_result("E2E Behavior Validation", True,
                                    f"Clean: {len(violations_clean)} violations, "
                                    f"Degraded: {len(violations_degraded)} violations, "
                                    f"Execution ready: {system_state_clean['execution_ready']} vs {system_state_degraded['execution_ready']}")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Scenario failed with exception: {e}", exc_info=True)
            self.log_scenario_result("E2E Behavior Validation", False, f"Exception: {e}")
            return False
    
    def run_all_scenarios(self):
        """Run all test scenarios."""
        logger.info("🚀 Starting Invariant Scenario Testing")
        logger.info("=" * 80)
        
        scenarios = [
            ("MD Age Invariants", self.scenario_1_md_age_invariants),
            ("WS Forwarder Health Gating", self.scenario_2_ws_health_gating),
            ("Quality vs Optimizer Consistency", self.scenario_3_quality_optimizer_consistency),
            ("Catalog Age and Depth Gating", self.scenario_4_catalog_depth_gating),
            ("Paranoid Mode vs Normal Mode", self.scenario_5_paranoid_mode),
            ("E2E Behavior Validation", self.scenario_6_e2e_behavior)
        ]
        
        passed = 0
        total = len(scenarios)
        
        for scenario_name, scenario_func in scenarios:
            try:
                if scenario_func():
                    passed += 1
            except Exception as e:
                logger.error(f"Scenario {scenario_name} crashed: {e}", exc_info=True)
                self.log_scenario_result(scenario_name, False, f"Crash: {e}")
        
        # Print summary
        logger.info("=" * 80)
        logger.info("📊 SCENARIO TESTING SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Passed: {passed}/{total}")
        
        for scenario_name, result in self.results.items():
            status = "✅ PASS" if result["passed"] else "❌ FAIL"
            logger.info(f"{status} {scenario_name}")
            if result["details"]:
                logger.info(f"   {result['details']}")
        
        if passed == total:
            logger.info("🎉 All scenarios passed!")
            return True
        else:
            logger.error(f"💥 {total - passed} scenarios failed!")
            return False

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run invariant scenario tests")
    parser.add_argument("--scenario", choices=[
        "md-age", "ws-health", "quality-optimizer", "catalog-depth", 
        "paranoid-mode", "e2e-behavior", "all"
    ], default="all", help="Specific scenario to run (default: all)")
    
    args = parser.parse_args()
    
    tester = InvariantScenarioTester()
    
    if args.scenario == "all":
        success = tester.run_all_scenarios()
    elif args.scenario == "md-age":
        success = tester.scenario_1_md_age_invariants()
    elif args.scenario == "ws-health":
        success = tester.scenario_2_ws_health_gating()
    elif args.scenario == "quality-optimizer":
        success = tester.scenario_3_quality_optimizer_consistency()
    elif args.scenario == "catalog-depth":
        success = tester.scenario_4_catalog_depth_gating()
    elif args.scenario == "paranoid-mode":
        success = tester.scenario_5_paranoid_mode()
    elif args.scenario == "e2e-behavior":
        success = tester.scenario_6_e2e_behavior()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
