#!/usr/bin/env python3
"""
MERID Cohort Governance Integration
Treats cohort and conversion outputs as first-class inputs to governance
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from analytics_governance_integration import AnalyticsGovernanceIntegration

class CohortGovernanceIntegration:
    """Integrates cohort metrics as first-class governance inputs"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.analytics_integration = AnalyticsGovernanceIntegration(db_path)
        self.governance_thresholds = {
            "d7_retention_min": 40.0,  # 40% minimum D7 retention
            "d7_to_d30_conversion_min": 60.0,  # 60% minimum conversion
            "cohort_size_min": 5,  # Minimum cohort size for reliability
            "identity_resolution_temp_max": 20.0,  # Max 20% temp mappings
            "data_quality_score_min": 80.0  # Minimum data quality score
        }
    
    def evaluate_promotion_readiness(self, week_number: int) -> Dict[str, Any]:
        """Evaluate promotion readiness based on cohort metrics"""
        
        print(f"🔍 Evaluating Promotion Readiness for Week {week_number}...")
        
        # Get latest analytics data
        dossier_data = self.analytics_integration.generate_weekly_dossier_analytics(week_number)
        
        # Extract key metrics
        key_metrics = dossier_data["key_metrics"]
        governance_impact = dossier_data["governance_impact"]
        
        # Evaluate each gate
        gates = {
            "d7_retention_gate": self._evaluate_d7_retention_gate(key_metrics),
            "d7_to_d30_conversion_gate": self._evaluate_d7_to_d30_conversion_gate(key_metrics),
            "identity_resolution_gate": self._evaluate_identity_resolution_gate(dossier_data["identity_resolution"]),
            "data_quality_gate": self._evaluate_data_quality_gate(dossier_data["cohort_analysis"]),
            "statistical_significance_gate": self._evaluate_statistical_significance_gate(dossier_data["cohort_analysis"])
        }
        
        # Calculate overall readiness
        overall_readiness = self._calculate_overall_readiness(gates)
        
        # Generate promotion decision
        promotion_decision = self._generate_promotion_decision(gates, overall_readiness)
        
        # Create governance report
        governance_report = {
            "week_number": week_number,
            "evaluation_date": datetime.now(timezone.utc).isoformat(),
            "promotion_readiness": overall_readiness,
            "promotion_decision": promotion_decision,
            "gate_evaluations": gates,
            "key_metrics": key_metrics,
            "thresholds": self.governance_thresholds,
            "recommendations": self._generate_promotion_recommendations(gates, overall_readiness),
            "blocking_issues": self._identify_blocking_issues(gates),
            "next_steps": self._generate_next_steps(promotion_decision)
        }
        
        print(f"✅ Promotion Readiness Evaluation Complete: {overall_readiness}")
        return governance_report
    
    def _evaluate_d7_retention_gate(self, key_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate D7 retention gate"""
        
        current_d7 = key_metrics["latest_d7_retention"]
        threshold = self.governance_thresholds["d7_retention_min"]
        
        if current_d7 >= threshold:
            return {
                "status": "PASS",
                "score": 100,
                "message": f"D7 retention {current_d7:.1f}% meets threshold ({threshold}%)",
                "value": current_d7,
                "threshold": threshold,
                "gap": max(0, threshold - current_d7)
            }
        elif current_d7 >= threshold * 0.75:  # 75% of threshold
            return {
                "status": "WARNING",
                "score": 70,
                "message": f"D7 retention {current_d7:.1f}% below threshold ({threshold}%)",
                "value": current_d7,
                "threshold": threshold,
                "gap": threshold - current_d7
            }
        else:
            return {
                "status": "FAIL",
                "score": 30,
                "message": f"D7 retention {current_d7:.1f}% significantly below threshold ({threshold}%)",
                "value": current_d7,
                "threshold": threshold,
                "gap": threshold - current_d7
            }
    
    def _evaluate_d7_to_d30_conversion_gate(self, key_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate D7→D30 conversion gate"""
        
        current_conversion = key_metrics["latest_d7_to_d30_conversion"]
        threshold = self.governance_thresholds["d7_to_d30_conversion_min"]
        
        if current_conversion >= threshold:
            return {
                "status": "PASS",
                "score": 100,
                "message": f"D7→D30 conversion {current_conversion:.1f}% meets threshold ({threshold}%)",
                "value": current_conversion,
                "threshold": threshold,
                "gap": max(0, threshold - current_conversion)
            }
        elif current_conversion >= threshold * 0.75:
            return {
                "status": "WARNING",
                "score": 70,
                "message": f"D7→D30 conversion {current_conversion:.1f}% below threshold ({threshold}%)",
                "value": current_conversion,
                "threshold": threshold,
                "gap": threshold - current_conversion
            }
        else:
            return {
                "status": "FAIL",
                "score": 30,
                "message": f"D7→D30 conversion {current_conversion:.1f}% significantly below threshold ({threshold}%)",
                "value": current_conversion,
                "threshold": threshold,
                "gap": threshold - current_conversion
            }
    
    def _evaluate_identity_resolution_gate(self, identity_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate identity resolution gate"""
        
        total_mappings = identity_stats["identity_mappings"]["total_mappings"]
        temp_mappings = identity_stats["identity_mappings"]["temp_mappings"]
        blocked_validations = identity_stats["security_validations"]["blocked_validations"]
        total_validations = identity_stats["security_validations"]["total_validations"]
        
        # Calculate metrics
        temp_percentage = (temp_mappings / total_mappings * 100) if total_mappings > 0 else 0
        security_failure_rate = (blocked_validations / total_validations * 100) if total_validations > 0 else 0
        
        # Evaluate against thresholds
        temp_threshold = self.governance_thresholds["identity_resolution_temp_max"]
        
        score = 100
        issues = []
        
        if temp_percentage > temp_threshold:
            score -= 40
            issues.append(f"High temp mappings ({temp_percentage:.1f}% > {temp_threshold}%)")
        
        if security_failure_rate > 10:
            score -= 30
            issues.append(f"High security failures ({security_failure_rate:.1f}%)")
        
        if total_mappings < 10:
            score -= 20
            issues.append(f"Low total mappings ({total_mappings})")
        
        if score >= 80:
            status = "PASS"
        elif score >= 60:
            status = "WARNING"
        else:
            status = "FAIL"
        
        return {
            "status": status,
            "score": score,
            "message": f"Identity resolution {status.lower()} - {', '.join(issues) if issues else 'No issues'}",
            "temp_percentage": temp_percentage,
            "security_failure_rate": security_failure_rate,
            "total_mappings": total_mappings,
            "issues": issues
        }
    
    def _evaluate_data_quality_gate(self, cohort_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate data quality gate"""
        
        d7_d14_cohorts = cohort_analysis["d7_d14_cohorts"]
        conversion_analysis = cohort_analysis["conversion_analysis"]
        
        # Check data quality issues
        issues = []
        score = 100
        
        # Check for empty cohorts
        empty_cohorts = [c for c in d7_d14_cohorts if c["cohort_size"] == 0]
        if empty_cohorts:
            issues.append(f"{len(empty_cohorts)} empty cohorts")
            score -= 20
        
        # Check for zero retention
        zero_retention = [c for c in d7_d14_cohorts if c["d7_retention_percent"] == 0]
        if zero_retention:
            issues.append(f"{len(zero_retention)} cohorts with zero D7 retention")
            score -= 30
        
        # Check for anomalous data
        anomalous = [c for c in d7_d14_cohorts if c["d7_retention_percent"] > 100]
        if anomalous:
            issues.append(f"{len(anomalous)} cohorts with anomalous data")
            score -= 40
        
        # Check minimum cohort size
        small_cohorts = [c for c in d7_d14_cohorts if c["cohort_size"] < self.governance_thresholds["cohort_size_min"]]
        if small_cohorts:
            issues.append(f"{len(small_cohorts)} cohorts below minimum size")
            score -= 10
        
        if score >= 80:
            status = "PASS"
        elif score >= 60:
            status = "WARNING"
        else:
            status = "FAIL"
        
        return {
            "status": status,
            "score": score,
            "message": f"Data quality {status.lower()} - {', '.join(issues) if issues else 'No issues'}",
            "total_cohorts": len(d7_d14_cohorts),
            "issues": issues,
            "quality_metrics": {
                "empty_cohorts": len(empty_cohorts),
                "zero_retention_cohorts": len(zero_retention),
                "anomalous_cohorts": len(anomalous),
                "small_cohorts": len(small_cohorts)
            }
        }
    
    def _evaluate_statistical_significance_gate(self, cohort_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate statistical significance gate"""
        
        d7_d14_cohorts = cohort_analysis["d7_d14_cohorts"]
        conversion_analysis = cohort_analysis["conversion_analysis"]
        
        # Check statistical significance
        significant_cohorts = []
        total_cohorts = len(d7_d14_cohorts)
        
        for cohort in d7_d14_cohorts:
            if cohort["cohort_size"] >= self.governance_thresholds["cohort_size_min"]:
                # Calculate confidence interval (simplified Wilson score)
                n = cohort["cohort_size"]
                p = cohort["d7_retention_percent"] / 100
                
                if n > 0 and 0 < p < 1:
                    # Wilson score interval (simplified)
                    z = 1.96  # 95% confidence
                    margin = z * ((p * (1 - p) / n) ** 0.5)
                    
                    if margin < 0.1:  # Less than 10% margin of error
                        significant_cohorts.append(cohort)
        
        significance_rate = (len(significant_cohorts) / total_cohorts * 100) if total_cohorts > 0 else 0
        
        if significance_rate >= 80:
            status = "PASS"
            score = 100
        elif significance_rate >= 60:
            status = "WARNING"
            score = 70
        else:
            status = "FAIL"
            score = 40
        
        return {
            "status": status,
            "score": score,
            "message": f"Statistical significance {status.lower()} - {significance_rate:.1f}% cohorts significant",
            "significant_cohorts": len(significant_cohorts),
            "total_cohorts": total_cohorts,
            "significance_rate": significance_rate
        }
    
    def _calculate_overall_readiness(self, gates: Dict[str, Any]) -> str:
        """Calculate overall readiness from gate evaluations"""
        
        # Critical gates that must pass
        critical_gates = ["d7_retention_gate", "d7_to_d30_conversion_gate"]
        
        # Check if any critical gate failed
        for gate_name in critical_gates:
            if gates[gate_name]["status"] == "FAIL":
                return "NOT_READY"
        
        # Check if any critical gate is warning
        for gate_name in critical_gates:
            if gates[gate_name]["status"] == "WARNING":
                return "CONDITIONAL"
        
        # Check if any gate failed
        for gate_name, gate_data in gates.items():
            if gate_data["status"] == "FAIL":
                return "NOT_READY"
        
        # Check if any gate is warning
        for gate_name, gate_data in gates.items():
            if gate_data["status"] == "WARNING":
                return "CONDITIONAL"
        
        return "READY"
    
    def _generate_promotion_decision(self, gates: Dict[str, Any], overall_readiness: str) -> Dict[str, Any]:
        """Generate promotion decision"""
        
        decision = {
            "ready_for_promotion": overall_readiness == "READY",
            "ready_for_sighted_live": overall_readiness in ["READY", "CONDITIONAL"],
            "blocking_gates": [],
            "warning_gates": [],
            "passed_gates": [],
            "decision_rationale": []
        }
        
        for gate_name, gate_data in gates.items():
            if gate_data["status"] == "FAIL":
                decision["blocking_gates"].append(gate_name)
                decision["decision_rationale"].append(f"{gate_name} failed: {gate_data['message']}")
            elif gate_data["status"] == "WARNING":
                decision["warning_gates"].append(gate_name)
                decision["decision_rationale"].append(f"{gate_name} warning: {gate_data['message']}")
            else:
                decision["passed_gates"].append(gate_name)
        
        if decision["ready_for_promotion"]:
            decision["decision_message"] = "System ready for promotion to next stage"
        elif decision["ready_for_sighted_live"]:
            decision["decision_message"] = "System ready for SIGHTED_LIVE with conditions"
        else:
            decision["decision_message"] = "System not ready for promotion"
        
        return decision
    
    def _generate_promotion_recommendations(self, gates: Dict[str, Any], overall_readiness: str) -> List[Dict[str, Any]]:
        """Generate promotion recommendations"""
        
        recommendations = []
        
        for gate_name, gate_data in gates.items():
            if gate_data["status"] == "FAIL":
                recommendations.append({
                    "priority": "CRITICAL",
                    "gate": gate_name,
                    "action": f"Address {gate_name} failure",
                    "details": gate_data["message"],
                    "estimated_effort": "1-2 weeks",
                    "owner": self._get_gate_owner(gate_name)
                })
            elif gate_data["status"] == "WARNING":
                recommendations.append({
                    "priority": "HIGH",
                    "gate": gate_name,
                    "action": f"Improve {gate_name} performance",
                    "details": gate_data["message"],
                    "estimated_effort": "1 week",
                    "owner": self._get_gate_owner(gate_name)
                })
        
        return recommendations
    
    def _identify_blocking_issues(self, gates: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify blocking issues"""
        
        blocking_issues = []
        
        for gate_name, gate_data in gates.items():
            if gate_data["status"] == "FAIL":
                blocking_issues.append({
                    "gate": gate_name,
                    "issue": gate_data["message"],
                    "impact": "BLOCKS_PROMOTION",
                    "urgency": "IMMEDIATE"
                })
        
        return blocking_issues
    
    def _generate_next_steps(self, promotion_decision: Dict[str, Any]) -> List[str]:
        """Generate next steps based on promotion decision"""
        
        if promotion_decision["ready_for_promotion"]:
            return [
                "Proceed with promotion to next stage",
                "Schedule stakeholder review",
                "Prepare promotion documentation",
                "Update governance records"
            ]
        elif promotion_decision["ready_for_sighted_live"]:
            return [
                "Proceed with SIGHTED_LIVE deployment",
                "Monitor warning gates closely",
                "Address warning conditions within 2 weeks",
                "Schedule follow-up review"
            ]
        else:
            return [
                "Address all blocking gates before promotion",
                "Focus on critical issues first",
                "Re-evaluate after fixes are implemented",
                "Schedule review in 2 weeks"
            ]
    
    def _get_gate_owner(self, gate_name: str) -> str:
        """Get owner for a specific gate"""
        owners = {
            "d7_retention_gate": "product_team",
            "d7_to_d30_conversion_gate": "product_team",
            "identity_resolution_gate": "engineering_team",
            "data_quality_gate": "data_team",
            "statistical_significance_gate": "analytics_team"
        }
        return owners.get(gate_name, "team_lead")
    
    def generate_promotion_report(self, week_number: int) -> str:
        """Generate promotion report"""
        
        governance_report = self.evaluate_promotion_readiness(week_number)
        
        # Create HTML report
        html_report = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MERID Promotion Report - Week {week_number}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f5f5f5; padding: 20px; border-radius: 5px; }}
                .gate {{ margin: 20px 0; padding: 15px; border-left: 4px solid #ccc; }}
                .pass {{ border-left-color: #4CAF50; }}
                .warning {{ border-left-color: #FF9800; }}
                .fail {{ border-left-color: #F44336; }}
                .status {{ font-weight: bold; padding: 4px 8px; border-radius: 3px; color: white; }}
                .status-pass {{ background: #4CAF50; }}
                .status-warning {{ background: #FF9800; }}
                .status-fail {{ background: #F44336; }}
                .metrics {{ display: flex; gap: 20px; margin: 20px 0; }}
                .metric {{ text-align: center; padding: 15px; background: #f9f9f9; border-radius: 5px; }}
                .recommendation {{ margin: 10px 0; padding: 10px; background: #e3f2fd; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>MERID Promotion Report</h1>
                <p>Week {week_number} - {governance_report['evaluation_date']}</p>
                <h2>Overall Status: {governance_report['promotion_readiness']}</h2>
                <p>{governance_report['promotion_decision']['decision_message']}</p>
            </div>
            
            <div class="metrics">
                <div class="metric">
                    <h3>D7 Retention</h3>
                    <p>{governance_report['key_metrics']['latest_d7_retention']:.1f}%</p>
                </div>
                <div class="metric">
                    <h3>D7→D30 Conversion</h3>
                    <p>{governance_report['key_metrics']['latest_d7_to_d30_conversion']:.1f}%</p>
                </div>
                <div class="metric">
                    <h3>Total Cohorts</h3>
                    <p>{governance_report['key_metrics']['total_cohorts_analyzed']}</p>
                </div>
                <div class="metric">
                    <h3>Total Devices</h3>
                    <p>{governance_report['key_metrics']['total_devices']}</p>
                </div>
            </div>
            
            <h2>Gate Evaluations</h2>
        """
        
        for gate_name, gate_data in governance_report['gate_evaluations'].items():
            status_class = gate_data['status'].lower()
            html_report += f"""
            <div class="gate {status_class}">
                <h3>{gate_name.replace('_', ' ').title()}</h3>
                <span class="status status-{status_class}">{gate_data['status']}</span>
                <p>{gate_data['message']}</p>
                <p>Score: {gate_data['score']}/100</p>
            </div>
            """
        
        html_report += """
            <h2>Recommendations</h2>
        """
        
        for rec in governance_report['recommendations']:
            html_report += f"""
            <div class="recommendation">
                <h4>{rec['action']} ({rec['priority']})</h4>
                <p>{rec['details']}</p>
                <p>Owner: {rec['owner']} | Effort: {rec['estimated_effort']}</p>
            </div>
            """
        
        html_report += """
            <h2>Next Steps</h2>
            <ul>
        """
        
        for step in governance_report['next_steps']:
            html_report += f"<li>{step}</li>"
        
        html_report += """
            </ul>
        </body>
        </html>
        """
        
        # Save report
        report_file = f"promotion_report_week_{week_number}.html"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"📄 Promotion report saved to {report_file}")
        return report_file

def demo_cohort_governance_integration():
    """Demonstrate cohort governance integration"""
    
    print("🚀 Starting MERID Cohort Governance Integration Demo")
    
    # Initialize integration
    cgi = CohortGovernanceIntegration()
    
    # Evaluate promotion readiness
    print("\n🔍 Evaluating Promotion Readiness...")
    governance_report = cgi.evaluate_promotion_readiness(1)
    
    print(f"📊 Overall Readiness: {governance_report['promotion_readiness']}")
    print(f"🎯 Promotion Decision: {governance_report['promotion_decision']['decision_message']}")
    
    # Show gate evaluations
    print("\n📋 Gate Evaluations:")
    for gate_name, gate_data in governance_report['gate_evaluations'].items():
        print(f"  • {gate_name}: {gate_data['status']} ({gate_data['score']}/100)")
        print(f"    {gate_data['message']}")
    
    # Show recommendations
    print(f"\n📋 Recommendations ({len(governance_report['recommendations'])}):")
    for rec in governance_report['recommendations']:
        print(f"  • {rec['action']} ({rec['priority']}) - {rec['owner']}")
    
    # Show next steps
    print(f"\n📝 Next Steps:")
    for step in governance_report['next_steps']:
        print(f"  • {step}")
    
    # Generate promotion report
    print("\n📄 Generating Promotion Report...")
    report_file = cgi.generate_promotion_report(1)
    
    print("\n✅ Cohort Governance Integration Demo Complete!")
    
    return cgi

if __name__ == "__main__":
    demo_cohort_governance_integration()
