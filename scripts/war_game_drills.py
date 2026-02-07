#!/usr/bin/env python3
"""
War Game Drills for MERID Season 1.

Simulates incidents to test operator response times and effectiveness
using the Season 1 Operator Runbook procedures.
"""

import json
import time
import argparse
import sys
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

class IncidentType(Enum):
    MODE_ROLLBACK = "mode_rollback"
    ASSERTION_COLLAPSE = "assertion_collapse"
    PRIORITY_VIOLATION_FLOOD = "priority_violation_flood"
    SYSTEM_DEGRADATION = "system_degradation"
    SECURITY_BREACH = "security_breach"
    COMPLIANCE_FAILURE = "compliance_failure"

class WarGameDrill:
    """War game drill simulator for MERID operations."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self.drill_results = []
        self.current_drill = None
    
    def simulate_mode_rollback(self) -> Dict[str, Any]:
        """Simulate a mode rollback incident."""
        print("🚨 SIMULATING MODE ROLLBACK INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate system mode change to BLIND
        print("1. Simulating system mode change to BLIND...")
        self._simulate_mode_change("BLIND")
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("mode_rollback")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("mode_rollback")
        
        # Step 4: Simulate system recovery
        print("4. Simulating system recovery...")
        recovery_time = self._simulate_system_recovery("mode_rollback")
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.MODE_ROLLBACK.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "recovery_time": recovery_time,
            "success": runbook_followed and recovery_time < 300,  # 5 minutes
            "score": self._calculate_drill_score(response_time, runbook_followed, recovery_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def simulate_assertion_collapse(self) -> Dict[str, Any]:
        """Simulate an assertion collapse incident."""
        print("🚨 SIMULATING ASSERTION COLLAPSE INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate assertion health dropping
        print("1. Simulating assertion health dropping...")
        self._simulate_assertion_health_drop()
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("assertion_collapse")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("assertion_collapse")
        
        # Step 4: Simulate assertion recovery
        print("4. Simulating assertion recovery...")
        recovery_time = self._simulate_assertion_recovery()
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.ASSERTION_COLLAPSE.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "recovery_time": recovery_time,
            "success": runbook_followed and recovery_time < 600,  # 10 minutes
            "score": self._calculate_drill_score(response_time, runbook_followed, recovery_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def simulate_priority_violation_flood(self) -> Dict[str, Any]:
        """Simulate a priority violation flood incident."""
        print("🚨 SIMULATING PRIORITY VIOLATION FLOOD INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate spike in priority violations
        print("1. Simulating spike in priority violations...")
        self._simulate_priority_violation_spike()
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("priority_violation_flood")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("priority_violation_flood")
        
        # Step 4: Simulate violation mitigation
        print("4. Simulating violation mitigation...")
        mitigation_time = self._simulate_violation_mitigation()
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.PRIORITY_VIOLATION_FLOOD.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "mitigation_time": mitigation_time,
            "success": runbook_followed and mitigation_time < 900,  # 15 minutes
            "score": self._calculate_drill_score(response_time, runbook_followed, mitigation_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def simulate_system_degradation(self) -> Dict[str, Any]:
        """Simulate a system degradation incident."""
        print("🚨 SIMULATING SYSTEM DEGRADATION INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate performance degradation
        print("1. Simulating performance degradation...")
        self._simulate_performance_degradation()
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("system_degradation")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("system_degradation")
        
        # Step 4: Simulate system optimization
        print("4. Simulating system optimization...")
        optimization_time = self._simulate_system_optimization()
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.SYSTEM_DEGRADATION.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "optimization_time": optimization_time,
            "success": runbook_followed and optimization_time < 1800,  # 30 minutes
            "score": self._calculate_drill_score(response_time, runbook_followed, optimization_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def simulate_security_breach(self) -> Dict[str, Any]:
        """Simulate a security breach incident."""
        print("🚨 SIMULATING SECURITY BREACH INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate security alert
        print("1. Simulating security alert...")
        self._simulate_security_alert()
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("security_breach")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("security_breach")
        
        # Step 4: Simulate security containment
        print("4. Simulating security containment...")
        containment_time = self._simulate_security_containment()
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.SECURITY_BREACH.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "containment_time": containment_time,
            "success": runbook_followed and containment_time < 600,  # 10 minutes
            "score": self._calculate_drill_score(response_time, runbook_followed, containment_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def simulate_compliance_failure(self) -> Dict[str, Any]:
        """Simulate a compliance failure incident."""
        print("🚨 SIMULATING COMPLIANCE FAILURE INCIDENT")
        
        drill_start = time.time()
        
        # Step 1: Simulate compliance alert
        print("1. Simulating compliance alert...")
        self._simulate_compliance_alert()
        
        # Step 2: Check operator response time
        print("2. Measuring operator response time...")
        response_time = self._measure_operator_response("compliance_failure")
        
        # Step 3: Simulate operator following runbook procedures
        print("3. Simulating operator following runbook procedures...")
        runbook_followed = self._simulate_runbook_procedures("compliance_failure")
        
        # Step 4: Simulate compliance remediation
        print("4. Simulating compliance remediation...")
        remediation_time = self._simulate_compliance_remediation()
        
        drill_end = time.time()
        
        result = {
            "incident_type": IncidentType.COMPLIANCE_FAILURE.value,
            "drill_start": drill_start,
            "drill_end": drill_end,
            "total_duration": drill_end - drill_start,
            "operator_response_time": response_time,
            "runbook_followed": runbook_followed,
            "remediation_time": remediation_time,
            "success": runbook_followed and remediation_time < 3600,  # 1 hour
            "score": self._calculate_drill_score(response_time, runbook_followed, remediation_time)
        }
        
        self.drill_results.append(result)
        return result
    
    def _simulate_mode_change(self, target_mode: str):
        """Simulate system mode change."""
        print(f"   System mode changing to {target_mode}")
        time.sleep(2)  # Simulate mode change delay
    
    def _simulate_assertion_health_drop(self):
        """Simulate assertion health dropping."""
        print("   Assertion health dropping to 30%...")
        time.sleep(3)  # Simulate health drop
    
    def _simulate_priority_violation_spike(self):
        """Simulate spike in priority violations."""
        print("   Priority violations spiking to 100/hour...")
        time.sleep(2)  # Simulate spike duration
    
    def _simulate_performance_degradation(self):
        """Simulate performance degradation."""
        print("   Performance degrading: latency +200%, throughput -50%...")
        time.sleep(4)  # Simulate degradation
    
    def _simulate_security_alert(self):
        """Simulate security alert."""
        print("   Security alert: Suspicious activity detected!")
        time.sleep(1)  # Simulate alert processing
    
    def _simulate_compliance_alert(self):
        """Simulate compliance alert."""
        print("   Compliance alert: Audit trail integrity check failed!")
        time.sleep(1)  # Simulate alert processing
    
    def _measure_operator_response(self, incident_type: str) -> float:
        """Measure operator response time."""
        print(f"   Measuring operator response time for {incident_type}...")
        
        # Simulate operator response time (random between 30-300 seconds)
        response_time = random.uniform(30, 300)
        
        print(f"   Operator responded in {response_time:.1f} seconds")
        return response_time
    
    def _simulate_runbook_procedures(self, incident_type: str) -> bool:
        """Simulate operator following runbook procedures."""
        print(f"   Simulating operator following runbook for {incident_type}...")
        
        # Simulate runbook procedure time (random between 60-600 seconds)
        procedure_time = random.uniform(60, 600)
        
        print(f"   Runbook procedures completed in {procedure_time:.1f} seconds")
        
        # Simulate whether procedures were followed correctly
        # 90% chance of following procedures correctly
        followed_correctly = random.random() < 0.9
        
        if followed_correctly:
            print("   ✅ Runbook procedures followed correctly")
        else:
            print("   ❌ Runbook procedures not followed correctly")
        
        time.sleep(procedure_time)
        return followed_correctly
    
    def _simulate_system_recovery(self, incident_type: str) -> float:
        """Simulate system recovery."""
        print(f"   Simulating system recovery from {incident_type}...")
        
        # Simulate recovery time (random between 60-300 seconds)
        recovery_time = random.uniform(60, 300)
        
        print(f"   System recovered in {recovery_time:.1f} seconds")
        time.sleep(recovery_time)
        return recovery_time
    
    def _simulate_assertion_recovery(self) -> float:
        """Simulate assertion recovery."""
        print("   Simulating assertion recovery...")
        
        # Simulate recovery time (random between 120-600 seconds)
        recovery_time = random.uniform(120, 600)
        
        print(f"   Assertions recovered in {recovery_time:.1f} seconds")
        time.sleep(recovery_time)
        return recovery_time
    
    def _simulate_violation_mitigation(self) -> float:
        """Simulate violation mitigation."""
        print("   Simulating violation mitigation...")
        
        # Simulate mitigation time (random between 180-900 seconds)
        mitigation_time = random.uniform(180, 900)
        
        print(f"   Violations mitigated in {mitigation_time:.1f} seconds")
        time.sleep(mitigation_time)
        return mitigation_time
    
    def _simulate_system_optimization(self) -> float:
        """Simulate system optimization."""
        print("   Simulating system optimization...")
        
        # Simulate optimization time (random between 300-1800 seconds)
        optimization_time = random.uniform(300, 1800)
        
        print(f"   System optimized in {optimization_time:.1f} seconds")
        time.sleep(optimization_time)
        return optimization_time
    
    def _simulate_security_containment(self) -> float:
        """Simulate security containment."""
        print("   Simulating security containment...")
        
        # Simulate containment time (random between 120-600 seconds)
        containment_time = random.uniform(120, 600)
        
        print(f"   Security contained in {containment_time:.1f} seconds")
        time.sleep(containment_time)
        return containment_time
    
    def _simulate_compliance_remediation(self) -> float:
        """Simulate compliance remediation."""
        print("   Simulating compliance remediation...")
        
        # Simulate remediation time (random between 600-3600 seconds)
        remediation_time = random.uniform(600, 3600)
        
        print(f"   Compliance remediated in {remediation_time:.1f} seconds")
        time.sleep(remediation_time)
        return remediation_time
    
    def _calculate_drill_score(self, response_time: float, runbook_followed: bool, recovery_time: float) -> float:
        """Calculate drill score based on performance."""
        base_score = 100.0
        
        # Response time penalty (30% weight)
        if response_time < 60:  # Under 1 minute
            response_penalty = 0
        elif response_time < 300:  # Under 5 minutes
            response_penalty = (response_time - 60) / 240 * 30
        else:  # Over 5 minutes
            response_penalty = 30
        
        # Runbook following penalty (40% weight)
        runbook_penalty = 0 if runbook_followed else 40
        
        # Recovery time penalty (30% weight)
        if recovery_time < 300:  # Under 5 minutes
            recovery_penalty = 0
        elif recovery_time < 1800:  # Under 30 minutes
            recovery_penalty = (recovery_time - 300) / 1500 * 30
        else:  # Over 30 minutes
            recovery_penalty = 30
        
        total_penalty = response_penalty + runbook_penalty + recovery_penalty
        score = max(0.0, base_score - total_penalty)
        
        return score
    
    def run_war_game_drill(self, incident_type: IncidentType) -> Dict[str, Any]:
        """Run a specific war game drill."""
        print(f"\n{'='*60}")
        print(f"WAR GAME DRILL: {incident_type.value.upper()}")
        print(f"{'='*60}")
        
        if incident_type == IncidentType.MODE_ROLLBACK:
            return self.simulate_mode_rollback()
        elif incident_type == IncidentType.ASSERTION_COLLAPSE:
            return self.simulate_assertion_collapse()
        elif incident_type == IncidentType.PRIORITY_VIOLATION_FLOOD:
            return self.simulate_priority_violation_flood()
        elif incident_type == IncidentType.SYSTEM_DEGRADATION:
            return self.simulate_system_degradation()
        elif incident_type == IncidentType.SECURITY_BREACH:
            return self.simulate_security_breach()
        elif incident_type == IncidentType.COMPLIANCE_FAILURE:
            return self.simulate_compliance_failure()
        else:
            raise ValueError(f"Unknown incident type: {incident_type}")
    
    def run_all_war_game_drills(self) -> Dict[str, Any]:
        """Run all war game drills."""
        print(f"\n{'='*60}")
        print("RUNNING ALL WAR GAME DRILLS")
        print(f"{'='*60}")
        
        all_results = []
        
        for incident_type in IncidentType:
            result = self.run_war_game_drill(incident_type)
            all_results.append(result)
        
        # Calculate overall score
        overall_score = sum(result["score"] for result in all_results) / len(all_results)
        
        summary = {
            "drill_date": datetime.utcnow().isoformat(),
            "total_drills": len(all_results),
            "overall_score": overall_score,
            "drill_results": all_results,
            "summary": self._generate_drill_summary(all_results)
        }
        
        print(f"\n{'='*60}")
        print("WAR GAME DRILLS SUMMARY")
        print(f"{'='*60}")
        print(f"Overall Score: {overall_score:.1f}%")
        print(f"Total Drills: {len(all_results)}")
        print(summary)
        
        return summary
    
    def _generate_drill_summary(self, results: List[Dict[str, Any]]) -> str:
        """Generate drill summary."""
        summary = []
        
        for result in results:
            incident_type = result["incident_type"]
            score = result["score"]
            success = result["success"]
            
            status = "✅" if success else "❌"
            
            summary.append(f"{status} {incident_type}: {score:.1f}% (Response: {result['operator_response_time']:.1f}s, Recovery: {result.get('recovery_time', 0):.1f}s)")
        
        return "\n".join(summary)
    
    def save_drill_results(self, filename: str):
        """Save drill results to file."""
        with open(filename, 'w') as f:
            json.dump(self.drill_results, f, indent=2)
        
        print(f"Drill results saved to {filename}")


def main():
    """Main entry point for war game drills."""
    parser = argparse.ArgumentParser(description='Run MERID war game drills')
    parser.add_argument('--base-url', default='http://localhost:8001', help='Base URL for MERID API')
    parser.add_argument('--api-key', help='API key for authentication')
    parser.add_argument('--incident-type', choices=[t.value for t in IncidentType], help='Type of incident to simulate')
    parser.add_argument('--all', action='store_true', help='Run all war game drills')
    parser.add_argument('--output', default='war-game-results.json', help='Output filename')
    parser.add_argument('--port', type=int, default=8080, help='Port to serve results on')
    
    args = parser.parse_args()
    
    # Create war game drill simulator
    simulator = WarGameDrill(args.base_url, args.api_key)
    
    if args.all:
        # Run all drills
        summary = simulator.run_all_war_game_drills()
        simulator.save_drill_results(args.output)
    else:
        # Run specific drill
        incident_type = IncidentType(args.incident_type)
        result = simulator.run_war_game_drill(incident_type)
        simulator.drill_results.append(result)
        simulator.save_drill_results(args.output)
    
    print(f"\nWar game drills completed. Results saved to {args.output}")


if __name__ == "__main__":
    main()
