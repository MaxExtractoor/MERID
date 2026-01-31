#!/usr/bin/env python3
"""
MERID Day 1: Internal User Simulation
Simulate internal user activity to generate D7 core activation events
"""

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from event_capture_system import EventCaptureSystem
from identity_resolution_service import IdentityResolutionService
from cohort_analysis_queries import CohortAnalysisQueries

class Day1InternalUserSimulation:
    """Simulate internal user activity for Day 1 of Week N Action Plan"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.event_system = EventCaptureSystem(db_path)
        self.identity_service = IdentityResolutionService(db_path)
        self.cohort_queries = CohortAnalysisQueries(db_path)
        
        # Internal user definitions
        self.internal_users = [
            {
                "user_id": "user_internal_1",
                "device_id": "device_internal_1_abc123",
                "role": "product_team_lead",
                "name": "Product Lead"
            },
            {
                "user_id": "user_internal_2", 
                "device_id": "device_internal_2_def456",
                "role": "engineering_lead",
                "name": "Engineering Lead"
            },
            {
                "user_id": "user_internal_3",
                "device_id": "device_internal_3_ghi789", 
                "role": "data_analyst",
                "name": "Data Analyst"
            },
            {
                "user_id": "user_internal_4",
                "device_id": "device_internal_4_jkl012",
                "role": "operations_manager", 
                "name": "Operations Manager"
            },
            {
                "user_id": "user_internal_5",
                "device_id": "device_internal_5_mno345",
                "role": "qa_tester",
                "name": "QA Tester"
            }
        ]
        
        # Core value actions
        self.core_value_actions = [
            "positions_view",
            "risk_analysis", 
            "shadow_pnl_inspection",
            "assertion_review"
        ]
        
        # Simulation results
        self.simulation_results = {
            "events_generated": 0,
            "core_value_events": 0,
            "users_active": 0,
            "session_durations": [],
            "errors": []
        }
    
    def run_day1_simulation(self) -> Dict[str, Any]:
        """Run complete Day 1 internal user simulation"""
        
        print("🚀 Starting MERID Day 1 Internal User Simulation")
        print("=" * 60)
        
        # Phase 1: User First Active Events
        print("\n📱 Phase 1: User First Active Events")
        self.simulate_user_first_active()
        
        # Phase 2: Core Value Actions
        print("\n💎 Phase 2: Core Value Actions")
        self.simulate_core_value_actions()
        
        # Phase 3: Session Activity
        print("\n🔄 Phase 3: Session Activity")
        self.simulate_session_activity()
        
        # Phase 4: Analysis and Reporting
        print("\n📊 Phase 4: Analysis and Reporting")
        results = self.analyze_simulation_results()
        
        # Generate report
        self.generate_simulation_report(results)
        
        return results
    
    def simulate_user_first_active(self):
        """Simulate user_first_active events for all internal users"""
        
        print("  📋 Generating user_first_active events...")
        
        for user in self.internal_users:
            try:
                # Resolve identity
                canonical_user_id = self.identity_service.get_canonical_user_id(
                    user["device_id"], 
                    user["user_id"], 
                    "127.0.0.1"
                )
                
                # Capture user_first_active event
                event_id = self.event_system.capture_event(
                    user_id=canonical_user_id,
                    device_id=user["device_id"],
                    event_name="user_first_active",
                    properties={
                        "platform": "web",
                        "role": user["role"],
                        "user_type": "internal",
                        "session_id": f"sess_{user['user_id']}_{int(time.time())}",
                        "source": "day1_simulation"
                    }
                )
                
                self.simulation_results["events_generated"] += 1
                print(f"    ✅ {user['name']}: user_first_active captured")
                
            except Exception as e:
                self.simulation_results["errors"].append({
                    "user": user["name"],
                    "event": "user_first_active",
                    "error": str(e)
                })
                print(f"    ❌ {user['name']}: user_first_active failed - {e}")
    
    def simulate_core_value_actions(self):
        """Simulate core value actions for all internal users"""
        
        print("  💎 Simulating core value actions...")
        
        for user in self.internal_users:
            print(f"    🔄 {user['name']} core value actions:")
            
            # Resolve identity
            canonical_user_id = self.identity_service.get_canonical_user_id(
                user["device_id"], 
                user["user_id"], 
                "127.0.0.1"
            )
            
            # Simulate core value actions
            for action in self.core_value_actions:
                try:
                    # Determine properties based on action
                    if action == "positions_view":
                        properties = {
                            "positions_count": 5,
                            "total_value": 250000,
                            "active_positions": 3
                        }
                    elif action == "risk_analysis":
                        properties = {
                            "risk_score": 7.5,
                            "risk_level": "medium",
                            "factors_analyzed": 12
                        }
                    elif action == "shadow_pnl_inspection":
                        properties = {
                            "shadow_pnl": 12500,
                            "variance": 2.3,
                            "confidence": 0.95
                        }
                    elif action == "assertion_review":
                        properties = {
                            "assertions_reviewed": 8,
                            "assertions_passed": 7,
                            "assertions_failed": 1
                        }
                    else:
                        properties = {}
                    
                    # Capture core_value_experienced event
                    event_id = self.event_system.capture_event(
                        user_id=canonical_user_id,
                        device_id=user["device_id"],
                        event_name="core_value_experienced",
                        properties={
                            "core_value_action": action,
                            "user_role": user["role"],
                            **properties,
                            "session_id": f"sess_{user['user_id']}_{int(time.time())}",
                            "source": "day1_simulation"
                        }
                    )
                    
                    self.simulation_results["events_generated"] += 1
                    self.simulation_results["core_value_events"] += 1
                    print(f"      ✅ {action}: core_value_experienced captured")
                    
                    # Small delay between actions
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.simulation_results["errors"].append({
                        "user": user["name"],
                        "action": action,
                        "error": str(e)
                    })
                    print(f"      ❌ {action}: failed - {e}")
    
    def simulate_session_activity(self):
        """Simulate ongoing session activity"""
        
        print("  🔄 Simulating ongoing session activity...")
        
        for user in self.internal_users:
            session_start = time.time()
            
            try:
                # Resolve identity
                canonical_user_id = self.identity_service.get_canonical_user_id(
                    user["device_id"], 
                    user["user_id"], 
                    "127.0.0.1"
                )
                
                # Simulate multiple session_active events
                for i in range(3):  # 3 session events per user
                    event_id = self.event_system.capture_event(
                        user_id=canonical_user_id,
                        device_id=user["device_id"],
                        event_name="session_active",
                        properties={
                            "platform": "web",
                            "page": f"/dashboard_{i+1}",
                            "session_duration": i * 300,  # 5min intervals
                            "session_id": f"sess_{user['user_id']}_{int(time.time())}",
                            "source": "day1_simulation"
                        }
                    )
                    
                    self.simulation_results["events_generated"] += 1
                    time.sleep(0.05)  # Small delay
                
                session_duration = time.time() - session_start
                self.simulation_results["session_durations"].append({
                    "user": user["name"],
                    "duration": session_duration,
                    "events": 3
                })
                
                self.simulation_results["users_active"] += 1
                print(f"    ✅ {user['name']}: 3 session_active events ({session_duration:.2f}s)")
                
            except Exception as e:
                self.simulation_results["errors"].append({
                    "user": user["name"],
                    "event": "session_active",
                    "error": str(e)
                })
                print(f"    ❌ {user['name']}: session_active failed - {e}")
    
    def analyze_simulation_results(self) -> Dict[str, Any]:
        """Analyze simulation results and generate metrics"""
        
        print("  📊 Analyzing simulation results...")
        
        # Get current analytics data
        try:
            d7_d14_cohorts = self.cohort_queries.get_d7_d14_cohort_analysis()
            identity_stats = self.identity_service.get_identity_resolution_stats()
            
            # Calculate metrics
            total_events = self.simulation_results["events_generated"]
            core_value_events = self.simulation_results["core_value_events"]
            users_active = self.simulation_results["users_active"]
            errors = len(self.simulation_results["errors"])
            
            # Session metrics
            if self.simulation_results["session_durations"]:
                avg_session_duration = sum(
                    s["duration"] for s in self.simulation_results["session_durations"]
                ) / len(self.simulation_results["session_durations"])
            else:
                avg_session_duration = 0
            
            results = {
                "simulation_summary": {
                    "total_events": total_events,
                    "core_value_events": core_value_events,
                    "users_active": users_active,
                    "errors": errors,
                    "success_rate": ((total_events - errors) / total_events * 100) if total_events > 0 else 0,
                    "avg_session_duration": avg_session_duration
                },
                "analytics_data": {
                    "d7_cohorts": len(d7_d14_cohorts),
                    "identity_mappings": identity_stats.get("identity_mappings", {}),
                    "identity_stats": identity_stats
                },
                "simulation_details": self.simulation_results,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            
            print(f"    ✅ Total events: {total_events}")
            print(f"    ✅ Core value events: {core_value_events}")
            print(f"    ✅ Users active: {users_active}")
            print(f"    ✅ Success rate: {results['simulation_summary']['success_rate']:.1f}%")
            print(f"    ✅ Avg session duration: {avg_session_duration:.2f}s")
            
            return results
            
        except Exception as e:
            print(f"    ❌ Analysis failed: {e}")
            return {
                "simulation_summary": self.simulation_results,
                "error": str(e),
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
    
    def generate_simulation_report(self, results: Dict[str, Any]):
        """Generate simulation report"""
        
        print("\n📄 Generating Day 1 Simulation Report...")
        
        # Create HTML report
        html_report = self.create_html_report(results)
        html_file = "day1_simulation_report.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        # Save JSON report
        json_file = "day1_simulation_results.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"📄 HTML report saved to {html_file}")
        print(f"📄 JSON report saved to {json_file}")
    
    def create_html_report(self, results: Dict[str, Any]) -> str:
        """Create HTML report for simulation results"""
        
        summary = results.get("simulation_summary", {})
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>MERID Day 1 Simulation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .section {{ margin: 30px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
        .metric {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .success {{ color: #2e7d32; font-weight: bold; }}
        .error {{ color: #d32f2f; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>MERID Day 1 Simulation Report</h1>
        <p>Internal User Activity Simulation for Week N Action Plan</p>
        <p>Generated: {results.get('generated_at', 'Unknown')}</p>
    </div>
    
    <div class="section">
        <h2>Simulation Summary</h2>
        <div class="metric">
            <h3>Event Generation</h3>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Total Events</td><td>{summary.get('total_events', 0)}</td></tr>
                <tr><td>Core Value Events</td><td>{summary.get('core_value_events', 0)}</td></tr>
                <tr><td>Users Active</td><td>{summary.get('users_active', 0)}</td></tr>
                <tr><td>Errors</td><td>{summary.get('errors', 0)}</td></tr>
                <tr><td>Success Rate</td><td>{summary.get('success_rate', 0):.1f}%</td></tr>
                <tr><td>Avg Session Duration</td><td>{summary.get('avg_session_duration', 0):.2f}s</td></tr>
            </table>
        </div>
    </div>
    
    <div class="section">
        <h2>Internal Users</h2>
        <table>
            <tr><th>User</th><th>Role</th><th>Device ID</th><th>Status</th></tr>
"""
        
        for user in self.internal_users:
            status = "✅ Active" if user["user_id"] in [u["user_id"] for u in self.internal_users] else "❌ Inactive"
            html += f"""
            <tr>
                <td>{user['name']}</td>
                <td>{user['role']}</td>
                <td>{user['device_id']}</td>
                <td>{status}</td>
            </tr>
"""
        
        html += """
        </table>
    </div>
    
    <div class="section">
        <h2>Core Value Actions</h2>
        <table>
            <tr><th>Action</th><th>Description</th><th>Events Generated</th></tr>
"""
        
        for action in self.core_value_actions:
            html += f"""
            <tr>
                <td>{action.replace('_', ' ').title()}</td>
                <td>Core value action for internal users</td>
                <td>{summary.get('core_value_events', 0) // len(self.core_value_actions)}</td>
            </tr>
"""
        
        html += """
        </table>
    </div>
    
    <div class="section">
        <h2>Session Details</h2>
"""
        
        if self.simulation_results["session_durations"]:
            html += "<table><tr><th>User</th><th>Duration (s)</th><th>Events</th></tr>"
            for session in self.simulation_results["session_durations"]:
                html += f"""
                <tr>
                    <td>{session['user']}</td>
                    <td>{session['duration']:.2f}</td>
                    <td>{session['events']}</td>
                </tr>
"""
            html += "</table>"
        else:
            html += "<p>No session data available</p>"
        
        html += """
    </div>
    
    <div class="section">
        <h2>Errors</h2>
"""
        
        if self.simulation_results["errors"]:
            html += "<table><tr><th>User</th><th>Event/Action</th><th>Error</th></tr>"
            for error in self.simulation_results["errors"]:
                html += f"""
                <tr>
                    <td>{error['user']}</td>
                    <td>{error.get('event', error.get('action', 'Unknown'))}</td>
                    <td class="error">{error['error']}</td>
                </tr>
"""
            html += "</table>"
        else:
            html += "<p class='success'>No errors encountered!</p>"
        
        html += """
    </div>
    
    <div class="section">
        <h2>Next Steps</h2>
        <ul>
            <li>Monitor D7 retention over the next 7 days</li>
            <li>Track D7→D30 conversion rates</li>
            <li>Verify identity resolution improvements</li>
            <li>Prepare for Day 2: Identity failure analysis</li>
        </ul>
    </div>
</body>
</html>
"""
        
        return html

def main():
    """Run Day 1 internal user simulation"""
    
    print("🚀 Starting MERID Day 1 Internal User Simulation")
    
    simulator = Day1InternalUserSimulation()
    results = simulator.run_day1_simulation()
    
    print(f"\n✅ Day 1 Simulation Complete")
    print(f"📊 Total Events: {results['simulation_summary']['total_events']}")
    print(f"💎 Core Value Events: {results['simulation_summary']['core_value_events']}")
    print(f"👥 Users Active: {results['simulation_summary']['users_active']}")
    print(f"✅ Success Rate: {results['simulation_summary']['success_rate']:.1f}%")
    
    return simulator

if __name__ == "__main__":
    main()
