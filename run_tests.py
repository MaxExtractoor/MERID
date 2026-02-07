#!/usr/bin/env python3
"""
MERID Comprehensive Testing Script

Executes all test scenarios and validates system readiness.
"""

import asyncio
import logging
import sys
import time
from typing import Dict, List, Any
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Test result data."""
    scenario_id: str
    name: str
    passed: bool
    duration_seconds: float
    failures: List[str]
    details: Dict[str, Any]


class MERIDTestRunner:
    """Comprehensive test runner for MERID system."""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = time.time()
    
    async def test_neo4j_integration(self) -> TestResult:
        """Test Neo4j graph database integration."""
        logger.info("Testing Neo4j integration...")
        start = time.time()
        failures = []
        
        try:
            from core.graph_service import get_graph_service
            
            graph = get_graph_service()
            
            # Test 1: Connection
            try:
                health = graph.get_system_health_summary()
                logger.info(f"  ✓ Neo4j connected: {health}")
            except Exception as e:
                failures.append(f"Connection failed: {e}")
            
            # Test 2: Write operation
            try:
                test_proposal = {
                    "proposal_id": "test_001",
                    "state": "CREATED",
                    "side": "BUY",
                    "asset_id": "WETH",
                    "venue_id": "uniswap-v3",
                    "size_usd": 100.0,
                }
                graph.record_proposal(test_proposal, [], "test_agent")
                logger.info("  ✓ Write operation successful")
            except Exception as e:
                failures.append(f"Write failed: {e}")
            
            # Test 3: Read operation
            try:
                lineage = graph.get_proposal_lineage("test_001")
                if lineage:
                    logger.info("  ✓ Read operation successful")
                else:
                    failures.append("Read returned no data")
            except Exception as e:
                failures.append(f"Read failed: {e}")
            
        except Exception as e:
            failures.append(f"Neo4j test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T001",
            name="Neo4j Integration",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_reality_registry(self) -> TestResult:
        """Test Reality Registry."""
        logger.info("Testing Reality Registry...")
        start = time.time()
        failures = []
        
        try:
            from core.reality_registry import get_reality_registry
            
            registry = get_reality_registry()
            
            # Test 1: Domain count
            domains = registry.get_all_domains()
            if len(domains) < 8:
                failures.append(f"Only {len(domains)} domains (expected 8)")
            else:
                logger.info(f"  ✓ {len(domains)} domains registered")
            
            # Test 2: Create assertion
            try:
                assertion_id = registry.assert_fact(
                    domain="PRICE",
                    claim="WETH price is $3000",
                    confidence=0.95,
                    source="test",
                    evidence={"price": 3000}
                )
                logger.info(f"  ✓ Assertion created: {assertion_id}")
            except Exception as e:
                failures.append(f"Assertion creation failed: {e}")
            
            # Test 3: Query assertion
            try:
                assertions = registry.get_assertions_by_domain("PRICE")
                if assertions:
                    logger.info(f"  ✓ Query returned {len(assertions)} assertions")
                else:
                    failures.append("Query returned no assertions")
            except Exception as e:
                failures.append(f"Query failed: {e}")
            
        except Exception as e:
            failures.append(f"Reality Registry test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T002",
            name="Reality Registry",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_execution_controller(self) -> TestResult:
        """Test Execution Controller."""
        logger.info("Testing Execution Controller...")
        start = time.time()
        failures = []
        
        try:
            from core.execution_controller import get_execution_controller
            
            controller = get_execution_controller()
            
            # Test 1: Kill switch
            if controller.kill_switch_active:
                logger.info("  ✓ Kill switch active (safe state)")
            else:
                logger.info("  ⚠ Kill switch inactive (trading enabled)")
            
            # Test 2: Proposal submission (would need mock)
            logger.info("  ⊘ Proposal submission test skipped (requires mock)")
            
        except Exception as e:
            failures.append(f"Execution Controller test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T003",
            name="Execution Controller",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_risk_envelope(self) -> TestResult:
        """Test Risk Envelope Manager."""
        logger.info("Testing Risk Envelope Manager...")
        start = time.time()
        failures = []
        
        try:
            from core.risk_envelope import get_risk_envelope_manager
            
            risk_mgr = get_risk_envelope_manager()
            
            # Test 1: Verify limits
            envelope = risk_mgr.envelope
            if envelope.max_position_size_usd > 0:
                logger.info(f"  ✓ Position limit: ${envelope.max_position_size_usd:,.0f}")
            else:
                failures.append("Position limit not set")
            
            if envelope.max_leverage > 0:
                logger.info(f"  ✓ Leverage limit: {envelope.max_leverage}x")
            else:
                failures.append("Leverage limit not set")
            
            # Test 2: Risk check (would need mock proposal)
            logger.info("  ⊘ Risk check test skipped (requires mock)")
            
        except Exception as e:
            failures.append(f"Risk Envelope test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T004",
            name="Risk Envelope Manager",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_threat_monitor(self) -> TestResult:
        """Test Enhanced Threat Monitor."""
        logger.info("Testing Enhanced Threat Monitor...")
        start = time.time()
        failures = []
        
        try:
            from core.enhanced_threat_model import get_enhanced_threat_monitor
            
            threat_monitor = get_enhanced_threat_monitor()
            
            # Test 1: Threat count
            threat_count = len(threat_monitor.threats)
            if threat_count >= 8:
                logger.info(f"  ✓ {threat_count} threats registered")
            else:
                failures.append(f"Only {threat_count} threats (expected 8+)")
            
            # Test 2: Metric update
            try:
                threat_monitor.update_metric("test_metric", 1.0)
                logger.info("  ✓ Metric update successful")
            except Exception as e:
                failures.append(f"Metric update failed: {e}")
            
        except Exception as e:
            failures.append(f"Threat Monitor test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T005",
            name="Enhanced Threat Monitor",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_model_inventory(self) -> TestResult:
        """Test Model Inventory."""
        logger.info("Testing Model Inventory...")
        start = time.time()
        failures = []
        
        try:
            from core.model_risk_management import get_model_inventory, ModelType
            
            inventory = get_model_inventory()
            
            # Test 1: Register model
            try:
                metadata = inventory.register_model(
                    model_id="test_model_001",
                    model_name="Test Model",
                    model_type=ModelType.LANGUAGE_MODEL,
                    version="1.0",
                    owner="test",
                    team="test_team",
                    intended_use="Testing",
                    prohibited_use=["Production trading"],
                    training_data_sources=["test_data"]
                )
                logger.info(f"  ✓ Model registered: {metadata.model_id}")
            except Exception as e:
                failures.append(f"Model registration failed: {e}")
            
            # Test 2: Check use allowed
            try:
                check = inventory.check_use_allowed("test_model_001", "Testing purposes")
                if check["allowed"]:
                    logger.info("  ✓ Use check passed")
                else:
                    failures.append(f"Use check failed: {check['reason']}")
            except Exception as e:
                failures.append(f"Use check failed: {e}")
            
        except Exception as e:
            failures.append(f"Model Inventory test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T006",
            name="Model Inventory",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def test_compliance_engine(self) -> TestResult:
        """Test Programmable Compliance Engine."""
        logger.info("Testing Programmable Compliance Engine...")
        start = time.time()
        failures = []
        
        try:
            from core.defi_compliance import get_programmable_compliance_engine
            
            compliance = get_programmable_compliance_engine()
            
            # Test 1: Configuration
            if compliance.max_wallet_risk_score > 0:
                logger.info(f"  ✓ Max wallet risk: {compliance.max_wallet_risk_score}")
            else:
                failures.append("Wallet risk score not configured")
            
            # Test 2: Compliance check (would need mock addresses)
            logger.info("  ⊘ Compliance check test skipped (requires mock)")
            
        except Exception as e:
            failures.append(f"Compliance Engine test failed: {e}")
        
        duration = time.time() - start
        return TestResult(
            scenario_id="T007",
            name="Programmable Compliance Engine",
            passed=len(failures) == 0,
            duration_seconds=duration,
            failures=failures,
            details={}
        )
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all tests and return summary."""
        logger.info("="*70)
        logger.info("MERID COMPREHENSIVE TEST SUITE")
        logger.info("="*70 + "\n")
        
        # Run all tests
        tests = [
            self.test_neo4j_integration(),
            self.test_reality_registry(),
            self.test_execution_controller(),
            self.test_risk_envelope(),
            self.test_threat_monitor(),
            self.test_model_inventory(),
            self.test_compliance_engine(),
        ]
        
        self.results = await asyncio.gather(*tests)
        
        # Calculate summary
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        total_duration = time.time() - self.start_time
        
        # Print results
        print("\n" + "="*70)
        print("TEST RESULTS")
        print("="*70 + "\n")
        
        for result in self.results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"{status} | {result.scenario_id} | {result.name} ({result.duration_seconds:.2f}s)")
            
            if result.failures:
                for failure in result.failures:
                    print(f"       └─ {failure}")
        
        print("\n" + "="*70)
        print(f"SUMMARY: {passed}/{total} tests passed ({failed} failed)")
        print(f"Total duration: {total_duration:.2f} seconds")
        
        if failed == 0:
            print("\n🎉 ALL TESTS PASSED - SYSTEM READY")
        else:
            print(f"\n⚠️  {failed} TEST(S) FAILED - REVIEW BEFORE DEPLOYMENT")
        
        print("="*70 + "\n")
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "duration_seconds": total_duration,
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "name": r.name,
                    "passed": r.passed,
                    "failures": r.failures
                }
                for r in self.results
            ]
        }


async def main():
    """Main entry point."""
    runner = MERIDTestRunner()
    
    try:
        summary = await runner.run_all_tests()
        sys.exit(0 if summary["failed"] == 0 else 1)
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error during testing: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
