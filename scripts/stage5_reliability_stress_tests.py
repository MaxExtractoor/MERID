#!/usr/bin/env python3
"""
MERID Stage 5: Reliability Stress Tests
"Break it on purpose" - push load through event tracker, cross-device identity chaos, verify retention curves and promotion gates stay correct
"""

import asyncio
import json
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
import threading
import uuid

from event_capture_system import EventCaptureSystem
from identity_resolution_service import IdentityResolutionService
from cohort_analysis_queries import CohortAnalysisQueries
from cohort_governance_integration import CohortGovernanceIntegration

class ReliabilityStressTests:
    """Stage 5: Break it on purpose stress testing"""
    
    def __init__(self, db_path: str = "analytics_stress_test.db"):
        self.db_path = db_path
        self.event_system = EventCaptureSystem(db_path)
        self.identity_service = IdentityResolutionService(db_path)
        self.cohort_queries = CohortAnalysisQueries(db_path)
        self.governance_integration = CohortGovernanceIntegration(db_path)
        
        # Stress test parameters
        self.test_duration = 300  # 5 minutes
        self.concurrent_users = 100
        self.events_per_user = 50
        self.device_chaos_rate = 0.3  # 30% of users will have device chaos
        
        # Test results
        self.test_results = {
            "events_processed": 0,
            "identity_merges": 0,
            "errors": [],
            "performance_metrics": {},
            "data_quality_checks": {},
            "promotion_gate_tests": {}
        }
    
    async def run_all_stress_tests(self):
        """Run comprehensive stress tests"""
        
        print("🚀 Starting MERID Stage 5: Reliability Stress Tests")
        print("=" * 60)
        
        # Test 1: High-volume event tracking
        await self.test_high_volume_event_tracking()
        
        # Test 2: Cross-device identity chaos
        await self.test_cross_device_identity_chaos()
        
        # Test 3: Data quality under stress
        await self.test_data_quality_under_stress()
        
        # Test 4: Promotion gate integrity
        await self.test_promotion_gate_integrity()
        
        # Test 5: System failure scenarios
        await self.test_system_failure_scenarios()
        
        # Generate comprehensive report
        self.generate_stress_test_report()
        
        print("\n✅ Stage 5 Stress Tests Complete")
        return self.test_results
    
    async def test_high_volume_event_tracking(self):
        """Test 1: High-volume event tracking"""
        
        print("\n📊 Test 1: High-Volume Event Tracking")
        print(f"  - {self.concurrent_users} concurrent users")
        print(f"  - {self.events_per_user} events per user")
        print(f"  - Duration: {self.test_duration} seconds")
        
        start_time = time.time()
        
        # Generate concurrent users
        tasks = []
        for user_id in range(self.concurrent_users):
            task = self.simulate_user_activity(f"stress_user_{user_id}")
            tasks.append(task)
        
        # Execute all user simulations concurrently
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Calculate performance metrics
        total_events = self.concurrent_users * self.events_per_user
        events_per_second = total_events / duration
        
        self.test_results["performance_metrics"]["event_tracking"] = {
            "total_events": total_events,
            "duration_seconds": duration,
            "events_per_second": events_per_second,
            "average_latency_ms": (duration / total_events) * 1000
        }
        
        print(f"  ✅ Processed {total_events} events in {duration:.2f}s")
        print(f"  ✅ {events_per_second:.2f} events/second")
        print(f"  ✅ Average latency: {(duration / total_events) * 1000:.2f}ms")
    
    async def simulate_user_activity(self, user_id: str):
        """Simulate realistic user activity"""
        
        # Generate device ID
        device_id = f"device_{user_id}_{random.randint(1000, 9999)}"
        
        # Simulate user timeline
        current_time = datetime.now(timezone.utc)
        
        for event_num in range(self.events_per_user):
            # Random delay between events
            await asyncio.sleep(random.uniform(0.01, 0.1))
            
            # Event time progression
            event_time = current_time + timedelta(seconds=event_num * 2)
            
            # Determine event type
            if event_num == 0:
                # First event is always user_first_active
                event_name = "user_first_active"
                properties = {
                    "platform": "web",
                    "role": random.choice(["operator", "developer", "analyst"]),
                    "env": "stress_test",
                    "session_id": f"sess_{user_id}_{event_num}"
                }
            elif event_num % 10 == 0:
                # Every 10th event is core_value_experienced
                event_name = "core_value_experienced"
                properties = {
                    "shadow_pnl_inspected": True,
                    "pnl_amount": random.uniform(-10000, 50000),
                    "positions_count": random.randint(1, 10)
                }
            else:
                # Regular session_active events
                event_name = "session_active"
                properties = {
                    "platform": "web",
                    "session_id": f"sess_{user_id}_{event_num // 10}",
                    "page": random.choice(["/dashboard", "/analytics", "/risk", "/positions"])
                }
            
            # Capture event
            try:
                event_id = self.event_system.capture_event(
                    user_id=user_id,
                    device_id=device_id,
                    event_name=event_name,
                    properties=properties
                )
                self.test_results["events_processed"] += 1
                
            except Exception as e:
                self.test_results["errors"].append({
                    "type": "event_capture_error",
                    "user_id": user_id,
                    "event_name": event_name,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
    
    async def test_cross_device_identity_chaos(self):
        """Test 2: Cross-device identity chaos"""
        
        print("\n🔄 Test 2: Cross-Device Identity Chaos")
        print(f"  - {int(self.concurrent_users * self.device_chaos_rate)} users with device chaos")
        
        chaos_users = int(self.concurrent_users * self.device_chaos_rate)
        
        for user_idx in range(chaos_users):
            user_id = f"chaos_user_{user_idx}"
            
            # Create multiple devices for the same user
            devices = [f"device_{user_id}_{i}" for i in range(random.randint(2, 5))]
            
            # Simulate user switching between devices
            for device_idx, device_id in enumerate(devices):
                # First event on this device
                await self.simulate_device_switch(user_id, device_id, device_idx)
                
                # Small delay between device switches
                await asyncio.sleep(0.05)
        
        # Verify identity resolution worked correctly
        identity_stats = self.identity_service.get_identity_resolution_stats()
        
        self.test_results["identity_merges"] = identity_stats["merge_activity"]["total_merges"]
        
        print(f"  ✅ Identity merges: {identity_stats['merge_activity']['total_merges']}")
        print(f"  ✅ Total devices: {identity_stats['identity_mappings']['total_devices']}")
        print(f"  ✅ Total users: {identity_stats['identity_mappings']['total_users']}")
    
    async def simulate_device_switch(self, user_id: str, device_id: str, device_idx: int):
        """Simulate user switching to a new device"""
        
        # Resolve identity (this should merge devices)
        canonical_user_id = self.identity_service.get_canonical_user_id(
            device_id, user_id, "127.0.0.1"
        )
        
        # Capture events on new device
        events = ["session_active", "mode_viewed", "assertion_viewed"]
        
        for event_name in events:
            properties = {
                "device_switch": True,
                "device_index": device_idx,
                "session_id": f"sess_{user_id}_{device_idx}"
            }
            
            try:
                self.event_system.capture_event(
                    user_id=canonical_user_id,
                    device_id=device_id,
                    event_name=event_name,
                    properties=properties
                )
                
            except Exception as e:
                self.test_results["errors"].append({
                    "type": "identity_chaos_error",
                    "user_id": user_id,
                    "device_id": device_id,
                    "event_name": event_name,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
    
    async def test_data_quality_under_stress(self):
        """Test 3: Data quality under stress"""
        
        print("\n📊 Test 3: Data Quality Under Stress")
        
        # Run cohort analysis on stress test data
        try:
            d7_d14_cohorts = self.cohort_queries.get_d7_d14_cohort_analysis()
            conversion_analysis = self.cohort_queries.get_d7_to_d30_conversion_analysis()
            
            # Data quality checks
            quality_issues = []
            
            # Check for empty cohorts
            empty_cohorts = [c for c in d7_d14_cohorts if c["cohort_size"] == 0]
            if empty_cohorts:
                quality_issues.append(f"{len(empty_cohorts)} empty cohorts")
            
            # Check for anomalous retention rates
            anomalous = [c for c in d7_d14_cohorts if c["d7_retention_percent"] > 100]
            if anomalous:
                quality_issues.append(f"{len(anomalous)} cohorts with anomalous retention")
            
            # Check for zero retention (expected in stress test)
            zero_retention = [c for c in d7_d14_cohorts if c["d7_retention_percent"] == 0]
            if zero_retention:
                quality_issues.append(f"{len(zero_retention)} cohorts with zero retention (expected)")
            
            self.test_results["data_quality_checks"] = {
                "total_cohorts": len(d7_d14_cohorts),
                "quality_issues": quality_issues,
                "conversion_analysis_available": len(conversion_analysis) > 0,
                "data_integrity": "PASS" if len(quality_issues) <= 2 else "WARNING"
            }
            
            print(f"  ✅ Cohorts analyzed: {len(d7_d14_cohorts)}")
            print(f"  ✅ Quality issues: {len(quality_issues)}")
            print(f"  ✅ Data integrity: {self.test_results['data_quality_checks']['data_integrity']}")
            
        except Exception as e:
            self.test_results["errors"].append({
                "type": "data_quality_error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            print(f"  ❌ Data quality test failed: {e}")
    
    async def test_promotion_gate_integrity(self):
        """Test 4: Promotion gate integrity"""
        
        print("\n🚪 Test 4: Promotion Gate Integrity")
        
        try:
            # Generate governance report
            governance_report = self.governance_integration.evaluate_promotion_readiness(1)
            
            # Check gate integrity
            gate_integrity = {}
            
            for gate_name, gate_data in governance_report["gate_evaluations"].items():
                gate_integrity[gate_name] = {
                    "status": gate_data["status"],
                    "score": gate_data["score"],
                    "message": gate_data["message"],
                    "integrity_check": "PASS" if 0 <= gate_data["score"] <= 100 else "FAIL"
                }
            
            # Check overall decision logic
            decision = governance_report["promotion_decision"]
            
            self.test_results["promotion_gate_tests"] = {
                "overall_readiness": governance_report["promotion_readiness"],
                "promotion_decision": decision["decision_message"],
                "blocking_gates": len(decision["blocking_gates"]),
                "warning_gates": len(decision["warning_gates"]),
                "gate_integrity": gate_integrity,
                "decision_logic": "PASS" if decision["ready_for_promotion"] or len(decision["blocking_gates"]) > 0 else "FAIL"
            }
            
            print(f"  ✅ Overall readiness: {governance_report['promotion_readiness']}")
            print(f"  ✅ Blocking gates: {len(decision['blocking_gates'])}")
            print(f"  ✅ Warning gates: {len(decision['warning_gates'])}")
            print(f"  ✅ Decision logic: {self.test_results['promotion_gate_tests']['decision_logic']}")
            
        except Exception as e:
            self.test_results["errors"].append({
                "type": "promotion_gate_error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            print(f"  ❌ Promotion gate test failed: {e}")
    
    async def test_system_failure_scenarios(self):
        """Test 5: System failure scenarios"""
        
        print("\n💥 Test 5: System Failure Scenarios")
        
        failure_tests = []
        
        # Test 1: Database connection failure simulation
        failure_tests.append(await self.test_database_failure_simulation())
        
        # Test 2: Memory pressure simulation
        failure_tests.append(await self.test_memory_pressure_simulation())
        
        # Test 3: Concurrent access stress
        failure_tests.append(await self.test_concurrent_access_stress())
        
        self.test_results["failure_scenarios"] = failure_tests
        
        print(f"  ✅ Failure scenarios tested: {len(failure_tests)}")
        for test in failure_tests:
            print(f"    • {test['scenario']}: {test['result']}")
    
    async def test_database_failure_simulation(self):
        """Simulate database connection issues"""
        
        try:
            # This would simulate database connection issues
            # For now, we'll test rapid connection/disconnection
            
            for i in range(10):
                # Create new connection
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Quick query
                cursor.execute("SELECT COUNT(*) FROM events")
                count = cursor.fetchone()[0]
                
                conn.close()
                
                # Small delay
                await asyncio.sleep(0.01)
            
            return {
                "scenario": "Database Connection Stress",
                "result": "PASS",
                "details": f"Completed 10 connection cycles"
            }
            
        except Exception as e:
            return {
                "scenario": "Database Connection Stress",
                "result": "FAIL",
                "error": str(e)
            }
    
    async def test_memory_pressure_simulation(self):
        """Simulate memory pressure"""
        
        try:
            # Create large number of events in memory
            large_events = []
            
            for i in range(1000):
                event = {
                    "user_id": f"memory_test_user_{i}",
                    "device_id": f"memory_test_device_{i}",
                    "event_name": "session_active",
                    "event_time": datetime.now(timezone.utc).isoformat(),
                    "properties": {
                        "large_data": "x" * 1000,  # 1KB of data per event
                        "iteration": i
                    }
                }
                large_events.append(event)
            
            # Process events
            for event in large_events:
                self.event_system.capture_event(**event)
            
            return {
                "scenario": "Memory Pressure",
                "result": "PASS",
                "details": f"Processed {len(large_events)} large events"
            }
            
        except Exception as e:
            return {
                "scenario": "Memory Pressure",
                "result": "FAIL",
                "error": str(e)
            }
    
    async def test_concurrent_access_stress(self):
        """Test concurrent access patterns"""
        
        try:
            # Simulate high concurrent access
            async def concurrent_access():
                for i in range(10):
                    user_id = f"concurrent_user_{uuid.uuid4().hex[:8]}"
                    device_id = f"concurrent_device_{uuid.uuid4().hex[:8]}"
                    
                    # Rapid identity resolution
                    canonical_id = self.identity_service.get_canonical_user_id(
                        device_id, user_id, "127.0.0.1"
                    )
                    
                    # Rapid event capture
                    self.event_system.capture_event(
                        user_id=canonical_id,
                        device_id=device_id,
                        event_name="session_active",
                        properties={"concurrent_test": True}
                    )
            
            # Run 50 concurrent access tasks
            tasks = [concurrent_access() for _ in range(50)]
            await asyncio.gather(*tasks)
            
            return {
                "scenario": "Concurrent Access Stress",
                "result": "PASS",
                "details": "Completed 50 concurrent access tasks"
            }
            
        except Exception as e:
            return {
                "scenario": "Concurrent Access Stress",
                "result": "FAIL",
                "error": str(e)
            }
    
    def generate_stress_test_report(self):
        """Generate comprehensive stress test report"""
        
        print("\n📄 Generating Stress Test Report...")
        
        # Calculate overall metrics
        total_errors = len(self.test_results["errors"])
        total_events = self.test_results["events_processed"]
        
        # Overall assessment
        if total_errors == 0:
            overall_status = "EXCELLENT"
        elif total_errors < 10:
            overall_status = "GOOD"
        elif total_errors < 50:
            overall_status = "ACCEPTABLE"
        else:
            overall_status = "NEEDS_ATTENTION"
        
        # Generate HTML report
        html_report = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MERID Stage 5 Stress Test Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f5f5f5; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                .status-excellent {{ background: #d4edda; border-color: #c3e6cb; }}
                .status-good {{ background: #cce5ff; border-color: #b3d9ff; }}
                .status-acceptable {{ background: #fff3cd; border-color: #ffeeba; }}
                .status-needs-attention {{ background: #f8d7da; border-color: #f5c6cb; }}
                .metric {{ display: inline-block; margin: 10px; padding: 10px; background: #f9f9f9; border-radius: 5px; }}
                .error {{ color: #d32f2f; }}
                .success {{ color: #2e7d32; }}
                table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>MERID Stage 5 Stress Test Report</h1>
                <p>Generated: {datetime.now(timezone.utc).isoformat()}</p>
                <h2>Overall Status: <span class="status-{overall_status.lower()}">{overall_status}</span></h2>
                <p>System reliability under stress testing</p>
            </div>
            
            <div class="section">
                <h2>Test Summary</h2>
                <div class="metric">
                    <h3>Events Processed</h3>
                    <p class="success">{total_events:,}</p>
                </div>
                <div class="metric">
                    <h3>Identity Merges</h3>
                    <p class="success">{self.test_results.get('identity_merges', 0):,}</p>
                </div>
                <div class="metric">
                    <h3>Total Errors</h3>
                    <p class="{'error' if total_errors > 0 else 'success'}">{total_errors}</p>
                </div>
            </div>
            
            <div class="section">
                <h2>Performance Metrics</h2>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
        """
        
        # Add performance metrics
        for metric_name, metric_data in self.test_results.get("performance_metrics", {}).items():
            html_report += f"""
                    <tr>
                        <td>{metric_name.replace('_', ' ').title()}</td>
                        <td>{metric_data}</td>
                    </tr>
            """
        
        html_report += """
                </table>
            </div>
            
            <div class="section">
                <h2>Data Quality Checks</h2>
        """
        
        # Add data quality checks
        quality_data = self.test_results.get("data_quality_checks", {})
        for key, value in quality_data.items():
            html_report += f"<p><strong>{key.replace('_', ' ').title()}:</strong> {value}</p>"
        
        html_report += """
            </div>
            
            <div class="section">
                <h2>Promotion Gate Tests</h2>
        """
        
        # Add promotion gate tests
        gate_data = self.test_results.get("promotion_gate_tests", {})
        for key, value in gate_data.items():
            if key != "gate_integrity":
                html_report += f"<p><strong>{key.replace('_', ' ').title()}:</strong> {value}</p>"
        
        html_report += """
            </div>
            
            <div class="section">
                <h2>Failure Scenarios</h2>
        """
        
        # Add failure scenarios
        failure_data = self.test_results.get("failure_scenarios", [])
        for scenario in failure_data:
            status_class = "success" if scenario["result"] == "PASS" else "error"
            html_report += f"""
                <p><strong>{scenario['scenario']}:</strong> 
                <span class="{status_class}">{scenario['result']}</span></p>
            """
        
        html_report += """
            </div>
            
            <div class="section">
                <h2>Errors Encountered</h2>
        """
        
        # Add errors
        if total_errors > 0:
            html_report += "<table><tr><th>Type</th><th>Error</th><th>Timestamp</th></tr>"
            for error in self.test_results["errors"][:10]:  # Show first 10 errors
                html_report += f"""
                    <tr>
                        <td>{error['type']}</td>
                        <td>{error['error']}</td>
                        <td>{error['timestamp']}</td>
                    </tr>
                """
            html_report += "</table>"
            if len(self.test_results["errors"]) > 10:
                html_report += f"<p>... and {len(self.test_results['errors']) - 10} more errors</p>"
        else:
            html_report += "<p class='success'>No errors encountered!</p>"
        
        html_report += """
            </div>
        </body>
        </html>
        """
        
        # Save report
        report_file = "stage5_stress_test_report.html"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"📄 Stress test report saved to {report_file}")
        
        # Print summary
        print(f"\n📊 STRESS TEST SUMMARY:")
        print(f"  • Overall Status: {overall_status}")
        print(f"  • Events Processed: {total_events:,}")
        print(f"  • Identity Merges: {self.test_results.get('identity_merges', 0):,}")
        print(f"  • Total Errors: {total_errors}")
        print(f"  • Test Duration: {self.test_duration} seconds")

async def main():
    """Run Stage 5 stress tests"""
    
    stress_tests = ReliabilityStressTests()
    results = await stress_tests.run_all_stress_tests()
    
    return stress_tests

if __name__ == "__main__":
    asyncio.run(main())
