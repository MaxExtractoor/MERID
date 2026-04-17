#!/usr/bin/env python3
"""
MERID Stress Test Governance Gate
Add stress test requirement to promotion gates
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from cohort_governance_integration import CohortGovernanceIntegration

class StressTestGovernanceGate:
    """Governance gate for stress test requirements"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.governance_integration = CohortGovernanceIntegration(db_path)
        
        # Stress test requirements
        self.stress_test_requirements = {
            "memory_pressure_max_mb": 50,  # Max 50MB memory usage
            "memory_pressure_events_max": 5,  # Max 5 memory pressure events
            "database_connection_min_score": 80,  # Min 80% success rate
            "concurrent_access_min_score": 80,  # Min 80% success rate
            "overall_stress_test_min_score": 75  # Min 75% overall score
        }
    
    def evaluate_stress_test_gate(self, stress_test_report: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate stress test gate against requirements"""
        
        print("🚪 Evaluating Stress Test Governance Gate")
        
        # Extract stress test metrics
        stress_metrics = self.extract_stress_test_metrics(stress_test_report)
        
        # Evaluate each requirement
        evaluations = {}
        
        # Memory pressure evaluation
        evaluations["memory_pressure"] = self.evaluate_memory_pressure(stress_metrics)
        
        # Database connection evaluation
        evaluations["database_connection"] = self.evaluate_database_connection(stress_metrics)
        
        # Concurrent access evaluation
        evaluations["concurrent_access"] = self.evaluate_concurrent_access(stress_metrics)
        
        # Overall stress test evaluation
        evaluations["overall_stress_test"] = self.evaluate_overall_stress_test(evaluations)
        
        # Generate gate decision
        gate_decision = self.generate_gate_decision(evaluations)
        
        # Create gate report
        gate_report = {
            "gate_name": "Stress Test Governance Gate",
            "evaluation_date": datetime.now(timezone.utc).isoformat(),
            "requirements": self.stress_test_requirements,
            "stress_metrics": stress_metrics,
            "evaluations": evaluations,
            "gate_decision": gate_decision,
            "recommendations": self.generate_recommendations(evaluations)
        }
        
        # Save gate report
        self.save_gate_report(gate_report)
        
        return gate_report
    
    def extract_stress_test_metrics(self, stress_test_report: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant metrics from stress test report"""
        
        # Try to read the stress test report file
        try:
            with open("stage5_stress_test_report.html", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Parse metrics from HTML content
            metrics = {}
            
            # Extract overall status
            if "Overall Status:" in content:
                status_start = content.find("Overall Status:")
                status_line = content[status_start:status_start+200]
                if "NEEDS_ATTENTION" in status_line:
                    metrics["overall_status"] = "NEEDS_ATTENTION"
                elif "EXCELLENT" in status_line:
                    metrics["overall_status"] = "EXCELLENT"
                elif "GOOD" in status_line:
                    metrics["overall_status"] = "GOOD"
                else:
                    metrics["overall_status"] = "UNKNOWN"
            
            # Extract events processed
            if "Events Processed:" in content:
                events_start = content.find("Events Processed:")
                events_line = content[events_start:events_start+100]
                import re
                events_match = re.search(r'(\d+,)', events_line)
                if events_match:
                    metrics["events_processed"] = int(events_match.group(1))
            
            # Extract total errors
            if "Total Errors:" in content:
                errors_start = content.find("Total Errors:")
                errors_line = content[errors_start:errors_start+100]
                errors_match = re.search(r'(\d+)', errors_line)
                if errors_match:
                    metrics["total_errors"] = int(errors_match.group(1))
            
            # Extract failure scenarios
            if "failure scenarios tested" in content:
                scenarios_start = content.find("failure scenarios tested")
                scenarios_line = content[scenarios_start:scenarios_start+50]
                scenarios_match = re.search(r'(\d+)', scenarios_line)
                if scenarios_match:
                    metrics["failure_scenarios"] = int(scenarios_match.group(1))
            
            # Extract individual test results
            test_results = {}
            test_patterns = [
                ("Database Connection Stress", "database_connection"),
                ("Memory Pressure", "memory_pressure"),
                ("Concurrent Access Stress", "concurrent_access")
            ]
            
            for test_name, test_key in test_patterns:
                if test_name in content:
                    test_start = content.find(test_name)
                    test_section = content[test_start:test_start+200]
                    if "PASS" in test_section:
                        test_results[test_key] = "PASS"
                    elif "FAIL" in test_section:
                        test_results[test_key] = "FAIL"
                    else:
                        test_results[test_key] = "UNKNOWN"
            
            metrics["test_results"] = test_results
            
            return metrics
            
        except Exception as e:
            print(f"⚠️ Could not parse stress test report: {e}")
            return {"error": str(e)}
    
    def evaluate_memory_pressure(self, stress_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate memory pressure requirements"""
        
        # Use memory hardening report if available
        try:
            with open("memory_hardening_report.json", "r", encoding="utf-8") as f:
                memory_report = json.load(f)
            
            memory_usage = memory_report.get("peak_memory_mb", 0)
            pressure_events = memory_report.get("memory_pressure_events", 0)
            
            # Evaluate against requirements
            max_memory = self.stress_test_requirements["memory_pressure_max_mb"]
            max_events = self.stress_test_requirements["memory_pressure_events_max"]
            
            if memory_usage <= max_memory and pressure_events <= max_events:
                return {
                    "status": "PASS",
                    "score": 100,
                    "message": f"Memory pressure within limits: {memory_usage:.2f}MB ≤ {max_memory}MB, {pressure_events} events ≤ {max_events}",
                    "memory_usage_mb": memory_usage,
                    "pressure_events": pressure_events
                }
            else:
                issues = []
                if memory_usage > max_memory:
                    issues.append(f"Memory usage {memory_usage:.2f}MB exceeds limit {max_memory}MB")
                if pressure_events > max_events:
                    issues.append(f"Pressure events {pressure_events} exceed limit {max_events}")
                
                return {
                    "status": "FAIL",
                    "score": 30,
                    "message": f"Memory pressure issues: {', '.join(issues)}",
                    "memory_usage_mb": memory_usage,
                    "pressure_events": pressure_events,
                    "issues": issues
                }
        
        except Exception as e:
            return {
                "status": "UNKNOWN",
                "score": 50,
                "message": f"Could not evaluate memory pressure: {e}",
                "error": str(e)
            }
    
    def evaluate_database_connection(self, stress_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate database connection requirements"""
        
        test_results = stress_metrics.get("test_results", {})
        db_status = test_results.get("database_connection", "UNKNOWN")
        
        min_score = self.stress_test_requirements["database_connection_min_score"]
        
        if db_status == "PASS":
            return {
                "status": "PASS",
                "score": 100,
                "message": "Database connection stress test passed",
                "test_result": db_status
            }
        elif db_status == "FAIL":
            return {
                "status": "FAIL",
                "score": 30,
                "message": "Database connection stress test failed",
                "test_result": db_status
            }
        else:
            return {
                "status": "UNKNOWN",
                "score": 50,
                "message": "Database connection test result unknown",
                "test_result": db_status
            }
    
    def evaluate_concurrent_access(self, stress_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate concurrent access requirements"""
        
        test_results = stress_metrics.get("test_results", {})
        concurrent_status = test_results.get("concurrent_access", "UNKNOWN")
        
        min_score = self.stress_test_requirements["concurrent_access_min_score"]
        
        if concurrent_status == "PASS":
            return {
                "status": "PASS",
                "score": 100,
                "message": "Concurrent access stress test passed",
                "test_result": concurrent_status
            }
        elif concurrent_status == "FAIL":
            return {
                "status": "FAIL",
                "score": 30,
                "message": "Concurrent access stress test failed",
                "test_result": concurrent_status
            }
        else:
            return {
                "status": "UNKNOWN",
                "score": 50,
                "message": "Concurrent access test result unknown",
                "test_result": concurrent_status
            }
    
    def evaluate_overall_stress_test(self, evaluations: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate overall stress test requirements"""
        
        scores = []
        issues = []
        
        for eval_name, evaluation in evaluations.items():
            if eval_name != "overall_stress_test":
                scores.append(evaluation["score"])
                if evaluation["status"] == "FAIL":
                    issues.append(f"{eval_name}: {evaluation['message']}")
        
        avg_score = sum(scores) / len(scores) if scores else 0
        min_score = self.stress_test_requirements["overall_stress_test_min_score"]
        
        if avg_score >= min_score and not issues:
            return {
                "status": "PASS",
                "score": avg_score,
                "message": f"Overall stress test passed with score {avg_score:.1f}",
                "individual_scores": scores,
                "issues": []
            }
        else:
            return {
                "status": "FAIL",
                "score": avg_score,
                "message": f"Overall stress test failed: score {avg_score:.1f} < {min_score}",
                "individual_scores": scores,
                "issues": issues
            }
    
    def generate_gate_decision(self, evaluations: Dict[str, Any]) -> Dict[str, Any]:
        """Generate gate decision based on evaluations"""
        
        overall_eval = evaluations.get("overall_stress_test", {})
        
        # Check if overall test passes
        if overall_eval["status"] == "PASS":
            return {
                "gate_status": "PASS",
                "promotion_allowed": True,
                "decision": "Stress test requirements met - promotion allowed",
                "blocking_issues": [],
                "warning_issues": []
            }
        else:
            # Identify blocking issues
            blocking_issues = []
            warning_issues = []
            
            for eval_name, evaluation in evaluations.items():
                if eval_name != "overall_stress_test":
                    if evaluation["status"] == "FAIL":
                        blocking_issues.append({
                            "component": eval_name,
                            "issue": evaluation["message"],
                            "score": evaluation["score"]
                        })
                    elif evaluation["status"] == "UNKNOWN":
                        warning_issues.append({
                            "component": eval_name,
                            "issue": evaluation["message"],
                            "score": evaluation["score"]
                        })
            
            return {
                "gate_status": "FAIL",
                "promotion_allowed": False,
                "decision": f"Stress test requirements not met - {len(blocking_issues)} blocking issues",
                "blocking_issues": blocking_issues,
                "warning_issues": warning_issues
            }
    
    def generate_recommendations(self, evaluations: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on evaluations"""
        
        recommendations = []
        
        for eval_name, evaluation in evaluations.items():
            if eval_name == "overall_stress_test":
                continue
            
            if evaluation["status"] == "FAIL":
                if eval_name == "memory_pressure":
                    recommendations.extend([
                        "Optimize memory usage in event capture and identity resolution",
                        "Implement memory pooling for frequently allocated objects",
                        "Add memory pressure monitoring and automatic cleanup"
                    ])
                elif eval_name == "database_connection":
                    recommendations.extend([
                        "Improve database connection handling under load",
                        "Implement connection pooling and retry logic",
                        "Add database connection health monitoring"
                    ])
                elif eval_name == "concurrent_access":
                    recommendations.extend([
                        "Review and optimize locking mechanisms",
                        "Implement proper transaction isolation",
                        "Add concurrency testing to CI pipeline"
                    ])
            elif evaluation["status"] == "UNKNOWN":
                recommendations.append(f"Investigate {eval_name} test failures and improve test reliability")
        
        return recommendations
    
    def save_gate_report(self, gate_report: Dict[str, Any]):
        """Save gate report to file"""
        
        # Save JSON
        json_file = "stress_test_gate_report.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(gate_report, f, indent=2)
        
        # Save HTML report
        html_report = self.create_html_report(gate_report)
        html_file = "stress_test_gate_report.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"📄 Stress test gate report saved to {json_file}")
        print(f"📄 HTML report saved to {html_file}")
    
    def create_html_report(self, gate_report: Dict[str, Any]) -> str:
        """Create HTML report for stress test gate"""
        
        status = gate_report["gate_decision"]["gate_status"]
        status_class = status.lower()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{gate_report['gate_name']} Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .status-pass {{ background: #d4edda; color: #155724; padding: 20px; border-radius: 5px; }}
        .status-fail {{ background: #f8d7da; color: #721c24; padding: 20px; border-radius: 5px; }}
        .evaluation {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .blocking {{ background: #fff3cd; color: #856404; padding: 10px; margin: 5px 0; border-radius: 3px; }}
        .requirement {{ background: #e3f2fd; padding: 10px; margin: 5px 0; border-radius: 3px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{gate_report['gate_name']}</h1>
        <p>Generated: {gate_report['evaluation_date']}</p>
    </div>
    
    <div class="status-{status_class}">
        <h2>Gate Status: {gate_report['gate_decision']['gate_status']}</h2>
        <p>{gate_report['gate_decision']['decision']}</p>
        <p><strong>Promotion Allowed:</strong> {gate_report['gate_decision']['promotion_allowed']}</p>
    </div>
    
    <div class="evaluation">
        <h3>Stress Test Requirements</h3>
        <table>
            <tr><th>Requirement</th><th>Value</th></tr>
"""
        
        for req_name, req_value in gate_report["requirements"].items():
            html += f"            <tr><td>{req_name.replace('_', ' ').title()}</td><td>{req_value}</td></tr>\n"
        
        html += """
        </table>
    </div>
    
    <div class="evaluation">
        <h3>Evaluation Results</h3>
"""
        
        for eval_name, evaluation in gate_report["evaluations"].items():
            eval_class = evaluation["status"].lower()
            html += f"""
        <div class="evaluation">
            <h4>{eval_name.replace('_', ' ').title()}</h4>
            <p><strong>Status:</strong> {evaluation['status']}</p>
            <p><strong>Score:</strong> {evaluation['score']}/100</p>
            <p><strong>Message:</strong> {evaluation['message']}</p>
        </div>
"""
        
        html += """
    </div>
    
    <div class="evaluation">
        <h3>Blocking Issues</h3>
"""
        
        if gate_report["gate_decision"]["blocking_issues"]:
            for issue in gate_report["gate_decision"]["blocking_issues"]:
                html += f'        <div class="blocking"><strong>{issue["component"]}:</strong> {issue["issue"]}</div>\n'
        else:
            html += "        <p>No blocking issues</p>\n"
        
        html += """
    </div>
    
    <div class="evaluation">
        <h3>Recommendations</h3>
"""
        
        for rec in gate_report["recommendations"]:
            html += f'        <div class="requirement">{rec}</div>\n'
        
        html += """
    </div>
</body>
</html>
"""
        
        return html

def main():
    """Evaluate stress test governance gate"""
    
    print("🚪 Starting MERID Stress Test Governance Gate Evaluation")
    
    gate = StressTestGovernanceGate()
    
    # Load memory hardening report
    try:
        with open("memory_hardening_report.json", "r", encoding="utf-8") as f:
            memory_report = json.load(f)
        print(f"📊 Loaded memory hardening report: {memory_report['status']}")
    except Exception as e:
        print(f"⚠️ Could not load memory hardening report: {e}")
        memory_report = {"status": "UNKNOWN"}
    
    # Evaluate gate
    gate_report = gate.evaluate_stress_test_gate(memory_report)
    
    print(f"\n✅ Stress Test Gate Evaluation Complete")
    print(f"🚪 Gate Status: {gate_report['gate_decision']['gate_status']}")
    print(f"📈 Overall Score: {gate_report['evaluations']['overall_stress_test']['score']:.1f}/100")
    print(f"📋 Blocking Issues: {len(gate_report['gate_decision']['blocking_issues'])}")
    print(f"⚠️ Warning Issues: {len(gate_report['gate_decision']['warning_issues'])}")
    
    return gate

if __name__ == "__main__":
    main()
