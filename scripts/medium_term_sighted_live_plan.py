#!/usr/bin/env python3
"""
MERID Medium-Term SIGHTED_LIVE Plan
For when D7 retention and D7→D30 conversion show stable, non-zero numbers with significant cohorts
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from cohort_governance_integration import CohortGovernanceIntegration

class MediumTermSightedLivePlan:
    """Medium-term plan for SIGHTED_LIVE readiness"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.governance_integration = CohortGovernanceIntegration(db_path)
        
        # SIGHTED_LIVE targets (higher than baseline)
        self.sighted_live_targets = {
            "d7_retention_min": 25.0,  # 25% (between baseline 5% and production 40%)
            "d7_to_d30_conversion_min": 40.0,  # 40% (between baseline 5% and production 60%)
            "cohort_size_min": 20,  # 20 users per cohort
            "significant_cohorts_min": 3,  # At least 3 significant cohorts
            "identity_failures_max": 3.0,  # <3% identity failures
            "data_quality_score_min": 85.0  # 85% data quality score
        }
    
    def generate_sighted_live_plan(self) -> Dict[str, Any]:
        """Generate comprehensive SIGHTED_LIVE plan"""
        
        print("🎯 Generating Medium-Term SIGHTED_LIVE Plan")
        print("=" * 60)
        
        # Current state assessment
        current_assessment = self.assess_current_readiness()
        
        # Gap analysis
        gap_analysis = self.analyze_gaps_to_sighted_live(current_assessment)
        
        # Readiness criteria
        readiness_criteria = self.define_sighted_live_criteria()
        
        # Implementation roadmap
        roadmap = self.create_sighted_live_roadmap(gap_analysis)
        
        # Success metrics
        success_metrics = self.define_sighted_live_success_metrics()
        
        # Risk assessment
        risk_assessment = self.assess_sighted_live_risks()
        
        plan = {
            "title": "MERID Medium-Term SIGHTED_LIVE Plan",
            "subtitle": "Path to SIGHTED_LIVE with Stable Analytics & Governance",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_assessment": current_assessment,
            "sighted_live_targets": self.sighted_live_targets,
            "gap_analysis": gap_analysis,
            "readiness_criteria": readiness_criteria,
            "roadmap": roadmap,
            "success_metrics": success_metrics,
            "risk_assessment": risk_assessment,
            "estimated_timeline": "4-8 weeks after baseline targets achieved",
            "next_milestone": "Achieve baseline targets (Week 1-2)"
        }
        
        # Save plan
        self.save_sighted_live_plan(plan)
        
        return plan
    
    def assess_current_readiness(self) -> Dict[str, Any]:
        """Assess current readiness against SIGHTED_LIVE criteria"""
        
        print("\n📊 Assessing Current SIGHTED_LIVE Readiness...")
        
        # Get current governance report
        governance_report = self.governance_integration.evaluate_promotion_readiness(1)
        
        # Extract current metrics
        current_metrics = {
            "d7_retention": governance_report["key_metrics"]["latest_d7_retention"],
            "d7_to_d30_conversion": governance_report["key_metrics"]["latest_d7_to_d30_conversion"],
            "cohort_size": governance_report["key_metrics"]["total_cohorts_analyzed"],
            "identity_failures": self._calculate_identity_failures(),
            "data_quality_score": governance_report["gate_evaluations"]["data_quality_gate"]["score"],
            "significant_cohorts": self._count_significant_cohorts(),
            "overall_readiness": governance_report["promotion_readiness"]
        }
        
        # Calculate readiness percentage
        readiness_score = self._calculate_sighted_live_readiness(current_metrics)
        
        assessment = {
            "current_metrics": current_metrics,
            "readiness_score": readiness_score,
            "readiness_status": self._get_readiness_status(readiness_score),
            "blocking_issues": self._identify_blocking_issues(current_metrics),
            "readiness_gates": self._evaluate_readiness_gates(current_metrics)
        }
        
        print(f"  • Current Readiness: {readiness_score:.1f}%")
        print(f"  • Status: {assessment['readiness_status']}")
        print(f"  • Blocking Issues: {len(assessment['blocking_issues'])}")
        
        return assessment
    
    def analyze_gaps_to_sighted_live(self, current_assessment: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze gaps between current state and SIGHTED_LIVE targets"""
        
        print("\n📈 Analyzing Gaps to SIGHTED_LIVE...")
        
        current = current_assessment["current_metrics"]
        gaps = {}
        
        # Calculate gaps for each metric
        gaps["d7_retention_gap"] = max(0, self.sighted_live_targets["d7_retention_min"] - current["d7_retention"])
        gaps["d7_to_d30_conversion_gap"] = max(0, self.sighted_live_targets["d7_to_d30_conversion_min"] - current["d7_to_d30_conversion"])
        gaps["cohort_size_gap"] = max(0, self.sighted_live_targets["cohort_size_min"] - current["cohort_size"])
        gaps["identity_failures_gap"] = max(0, current["identity_failures"] - self.sighted_live_targets["identity_failures_max"])
        gaps["data_quality_gap"] = max(0, self.sighted_live_targets["data_quality_score_min"] - current["data_quality_score"])
        gaps["significant_cohorts_gap"] = max(0, self.sighted_live_targets["significant_cohorts_min"] - current["significant_cohorts"])
        
        # Calculate overall gap score
        total_gap = sum(gaps.values())
        max_possible_gap = (
            self.sighted_live_targets["d7_retention_min"] +
            self.sighted_live_targets["d7_to_d30_conversion_min"] +
            self.sighted_live_targets["cohort_size_min"] +
            20 +  # Max identity failures gap
            20 +  # Max data quality gap
            self.sighted_live_targets["significant_cohorts_min"]
        )
        
        gap_percentage = (total_gap / max_possible_gap) * 100
        
        # Prioritize gaps
        prioritized_gaps = sorted(
            [(metric, gap) for metric, gap in gaps.items() if gap > 0],
            key=lambda x: x[1],
            reverse=True
        )
        
        gap_analysis = {
            "total_gap_score": total_gap,
            "gap_percentage": gap_percentage,
            "individual_gaps": gaps,
            "prioritized_gaps": prioritized_gaps,
            "largest_gap": prioritized_gaps[0] if prioritized_gaps else None,
            "readiness_distance": f"{gap_percentage:.1f}% from SIGHTED_LIVE targets"
        }
        
        print(f"  • Total Gap: {gap_percentage:.1f}% from SIGHTED_LIVE")
        print(f"  • Largest Gap: {gap_analysis['largest_gap'][0]} ({gap_analysis['largest_gap'][1]:.1f})")
        
        return gap_analysis
    
    def define_sighted_live_criteria(self) -> Dict[str, Any]:
        """Define SIGHTED_LIVE readiness criteria"""
        
        return {
            "critical_gates": {
                "d7_retention": {
                    "requirement": f"≥{self.sighted_live_targets['d7_retention_min']}% D7 retention",
                    "rationale": "Demonstrates user activation and early retention",
                    "measurement": "Cohort analysis of Day 7 return rate",
                    "confidence_level": "95% with Wilson CI"
                },
                "d7_to_d30_conversion": {
                    "requirement": f"≥{self.sighted_live_targets['d7_to_d30_conversion_min']}% D7→D30 conversion",
                    "rationale": "Shows long-term retention and value realization",
                    "measurement": "D7 retained users returning on Day 30",
                    "confidence_level": "90% with sufficient sample size"
                }
            },
            "quality_gates": {
                "cohort_size": {
                    "requirement": f"≥{self.sighted_live_targets['cohort_size_min']} users per cohort",
                    "rationale": "Ensures statistical significance of retention metrics",
                    "measurement": "Average cohort size over last 4 weeks"
                },
                "significant_cohorts": {
                    "requirement": f"≥{self.sighted_live_targets['significant_cohorts_min']} significant cohorts",
                    "rationale": "Demonstrates consistent performance across time periods",
                    "measurement": "Cohorts with statistically significant retention"
                }
            },
            "operational_gates": {
                "identity_resolution": {
                    "requirement": f"≤{self.sighted_live_targets['identity_failures_max']}% identity failures",
                    "rationale": "Ensures clean user tracking and analytics",
                    "measurement": "Security validation failure rate"
                },
                "data_quality": {
                    "requirement": f"≥{self.sighted_live_targets['data_quality_score_min']}% data quality score",
                    "rationale": "Ensures reliable analytics and governance decisions",
                    "measurement": "Data quality gate evaluation score"
                }
            },
            "governance_requirements": {
                "automated_decisions": "All promotion gates must be automated and data-driven",
                "evidence_generation": "Complete audit trail and compliance evidence",
                "real_time_monitoring": "Live dashboard with all key metrics",
                "stress_testing": "System proven under load conditions"
            }
        }
    
    def create_sighted_live_roadmap(self, gap_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create roadmap to achieve SIGHTED_LIVE"""
        
        print("\n🗺️ Creating SIGHTED_LIVE Roadmap...")
        
        roadmap = []
        
        # Phase 1: Foundation (Weeks 3-4)
        roadmap.append({
            "phase": 1,
            "name": "Foundation Building",
            "duration": 2,
            "focus": "Achieve baseline targets and stabilize metrics",
            "objectives": [
                "Reach 5% D7 retention",
                "Achieve 10+ users per cohort",
                "Reduce identity failures to <5%",
                "Implement consistent event tracking"
            ],
            "key_activities": [
                "Complete baseline improvement plan",
                "Scale user activity and engagement",
                "Fix identity resolution issues",
                "Establish data quality monitoring"
            ],
            "success_criteria": [
                "All baseline targets met",
                "Consistent event capture",
                "Stable identity resolution",
                "Data quality >80%"
            ],
            "risks": [
                "User adoption slower than expected",
                "Identity resolution complexity",
                "Data quality inconsistencies"
            ]
        })
        
        # Phase 2: Growth (Weeks 5-6)
        roadmap.append({
            "phase": 2,
            "name": "Growth & Optimization",
            "duration": 2,
            "focus": "Scale to SIGHTED_LIVE targets",
            "objectives": [
                "Reach 25% D7 retention",
                "Achieve 40% D7→D30 conversion",
                "Grow to 20+ users per cohort",
                "Maintain <3% identity failures"
            ],
            "key_activities": [
                "Scale user base and activity",
                "Optimize onboarding and retention",
                "Enhance core value experiences",
                "Fine-tune analytics and governance"
            ],
            "success_criteria": [
                "D7 retention ≥25%",
                "D7→D30 conversion ≥40%",
                "3+ significant cohorts",
                "Data quality ≥85%"
            ],
            "risks": [
                "Retention plateau",
                "Conversion optimization challenges",
                "System scaling issues"
            ]
        })
        
        # Phase 3: Validation (Weeks 7-8)
        roadmap.append({
            "phase": 3,
            "name": "Validation & Readiness",
            "duration": 2,
            "focus": "Validate SIGHTED_LIVE readiness",
            "objectives": [
                "Demonstrate stable metrics",
                "Complete stress testing",
                "Validate governance integration",
                "Prepare for SIGHTED_LIVE"
            ],
            "key_activities": [
                "Run comprehensive validation tests",
                "Validate governance decisions",
                "Complete documentation",
                "Prepare deployment plan"
            ],
            "success_criteria": [
                "All SIGHTED_LIVE gates PASS",
                "System proven under stress",
                "Governance integration validated",
                "Deployment ready"
            ],
            "risks": [
                "Validation failures",
                "Governance issues",
                "Deployment challenges"
            ]
        })
        
        print(f"  • Created {len(roadmap)} phases")
        print(f"  • Total Duration: {sum(phase['duration'] for phase in roadmap)} weeks")
        
        return roadmap
    
    def define_sighted_live_success_metrics(self) -> Dict[str, Any]:
        """Define success metrics for SIGHTED_LIVE"""
        
        return {
            "primary_success_metrics": {
                "user_retention": {
                    "d7_retention": f"≥{self.sighted_live_targets['d7_retention_min']}%",
                    "d7_to_d30_conversion": f"≥{self.sighted_live_targets['d7_to_d30_conversion_min']}%",
                    "retention_stability": "±5% variance over 4 weeks"
                },
                "data_quality": {
                    "cohort_size": f"≥{self.sighted_live_targets['cohort_size_min']} users",
                    "significant_cohorts": f"≥{self.sighted_live_targets['significant_cohorts_min']}",
                    "data_quality_score": f"≥{self.sighted_live_targets['data_quality_score_min']}%"
                },
                "system_reliability": {
                    "identity_failures": f"≤{self.sighted_live_targets['identity_failures_max']}%",
                    "system_uptime": "≥99.9%",
                    "stress_test_pass": "All scenarios PASS"
                }
            },
            "business_success_metrics": {
                "user_engagement": "Daily active users growing 10% week-over-week",
                "feature_adoption": "Core value features adopted by 60%+ users",
                "user_satisfaction": "User satisfaction score ≥4.0/5.0",
                "operational_efficiency": "Automated governance decisions"
            },
            "technical_success_metrics": {
                "performance": "Event processing <100ms, queries <5s",
                "scalability": "Handle 10x current load without degradation",
                "security": "Zero security incidents, all audits PASS",
                "maintainability": "Code coverage ≥90%, documentation complete"
            },
            "governance_success_metrics": {
                "automated_decisions": "100% promotion decisions automated",
                "evidence_generation": "Complete audit trail for all decisions",
                "compliance": "All regulatory requirements met",
                "transparency": "Clear explanation for all governance decisions"
            }
        }
    
    def assess_sighted_live_risks(self) -> Dict[str, Any]:
        """Assess risks for SIGHTED_LIVE deployment"""
        
        return {
            "technical_risks": [
                {
                    "risk": "Insufficient user activity",
                    "probability": "Medium",
                    "impact": "High",
                    "mitigation": "Scale user base, improve onboarding, add synthetic users for testing"
                },
                {
                    "risk": "Identity resolution complexity",
                    "probability": "Low",
                    "impact": "Medium",
                    "mitigation": "Comprehensive testing, fallback mechanisms, manual override"
                },
                {
                    "risk": "System scaling issues",
                    "probability": "Low",
                    "impact": "High",
                    "mitigation": "Load testing, horizontal scaling, performance monitoring"
                }
            ],
            "business_risks": [
                {
                    "risk": "User adoption slower than expected",
                    "probability": "Medium",
                    "impact": "Medium",
                    "mitigation": "User feedback loops, feature improvements, incentives"
                },
                {
                    "risk": "Retention optimization challenges",
                    "probability": "Medium",
                    "impact": "High",
                    "mitigation": "A/B testing, user research, product improvements"
                }
            ],
            "operational_risks": [
                {
                    "risk": "Governance decision errors",
                    "probability": "Low",
                    "impact": "High",
                    "mitigation": "Manual review, validation, rollback procedures"
                },
                {
                    "risk": "Data quality degradation",
                    "probability": "Low",
                    "impact": "Medium",
                    "mitigation": "Continuous monitoring, automated alerts, data validation"
                }
            ],
            "risk_mitigation_strategies": {
                "monitoring": "Real-time dashboards and alerting",
                "testing": "Comprehensive automated and manual testing",
                "rollback": "Clear rollback procedures and checkpoints",
                "communication": "Regular stakeholder updates and transparency"
            }
        }
    
    def save_sighted_live_plan(self, plan: Dict[str, Any]):
        """Save SIGHTED_LIVE plan to file"""
        
        # Save JSON
        json_file = "sighted_live_plan.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2)
        
        # Save HTML report
        html_report = self.create_html_report(plan)
        html_file = "sighted_live_plan.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"\n📄 SIGHTED_LIVE plan saved to {json_file}")
        print(f"📄 HTML report saved to {html_file}")
    
    def create_html_report(self, plan: Dict[str, Any]) -> str:
        """Create HTML report for SIGHTED_LIVE plan"""
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{plan['title']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .section {{ margin: 30px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
        .phase {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-left: 4px solid #1976d2; }}
        .risk {{ background: #fff3e0; padding: 10px; margin: 5px 0; border-left: 3px solid #f57c00; }}
        .metric {{ background: #e8f5e8; padding: 10px; margin: 5px 0; border-left: 3px solid #4caf50; }}
        .gap {{ background: #ffebee; padding: 10px; margin: 5px 0; border-left: 3px solid #f44336; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{plan['title']}</h1>
        <p><em>{plan['subtitle']}</em></p>
        <p>Generated: {plan['generated_at']}</p>
        <p>Estimated Timeline: {plan['estimated_timeline']}</p>
    </div>
    
    <div class="section">
        <h2>Current Readiness Assessment</h2>
        <div class="metric">
            <strong>Readiness Score:</strong> {plan['current_assessment']['readiness_score']:.1f}%
        </div>
        <div class="metric">
            <strong>Status:</strong> {plan['current_assessment']['readiness_status']}
        </div>
        <div class="metric">
            <strong>Blocking Issues:</strong> {len(plan['current_assessment']['blocking_issues'])}
        </div>
    </div>
    
    <div class="section">
        <h2>Gap Analysis</h2>
        <div class="gap">
            <strong>Distance from SIGHTED_LIVE:</strong> {plan['gap_analysis']['readiness_distance']}
        </div>
        <div class="gap">
            <strong>Largest Gap:</strong> {plan['gap_analysis']['largest_gap'][0]} ({plan['gap_analysis']['largest_gap'][1]:.1f})
        </div>
        <h3>Individual Gaps:</h3>
"""
        
        for metric, gap in plan['gap_analysis']['individual_gaps'].items():
            html += f"        <div class='gap'><strong>{metric.replace('_', ' ').title()}:</strong> {gap:.1f}</div>\n"
        
        html += """
    </div>
    
    <div class="section">
        <h2>SIGHTED_LIVE Roadmap</h2>
"""
        
        for phase in plan['roadmap']:
            html += f"""
        <div class="phase">
            <h3>Phase {phase['phase']}: {phase['name']}</h3>
            <p><strong>Duration:</strong> {phase['duration']}</p>
            <p><strong>Focus:</strong> {phase['focus']}</p>
            <h4>Objectives:</h4>
            <ul>
"""
            for objective in phase['objectives']:
                html += f"                <li>{objective}</li>\n"
            html += """
            </ul>
        </div>
"""
        
        html += """
    </div>
    
    <div class="section">
        <h2>Success Metrics</h2>
        <h3>Primary Success Metrics</h3>
"""
        
        for category, metrics in plan['success_metrics']['primary_success_metrics'].items():
            html += f"        <h4>{category.replace('_', ' ').title()}</h4>\n"
            for metric, target in metrics.items():
                html += f"        <div class='metric'><strong>{metric}:</strong> {target}</div>\n"
        
        html += """
    </div>
    
    <div class="section">
        <h2>Risk Assessment</h2>
"""
        
        for risk_category, risks in plan['risk_assessment'].items():
            if risk_category.endswith('_risks'):
                html += f"        <h3>{risk_category.replace('_', ' ').title()}</h3>\n"
                for risk in risks:
                    html += f"""
        <div class="risk">
            <strong>{risk['risk']}</strong><br>
            Probability: {risk['probability']}, Impact: {risk['impact']}<br>
            Mitigation: {risk['mitigation']}
        </div>
"""
        
        html += """
    </div>
</body>
</html>
"""
        
        return html
    
    # Helper methods
    def _calculate_identity_failures(self) -> float:
        """Calculate current identity failure rate"""
        # This would be calculated from actual data
        return 17.6  # Current value from stress test
    
    def _count_significant_cohorts(self) -> int:
        """Count statistically significant cohorts"""
        # This would be calculated from actual data
        return 0  # Current value
    
    def _calculate_sighted_live_readiness(self, current_metrics: Dict[str, Any]) -> float:
        """Calculate readiness score for SIGHTED_LIVE"""
        scores = []
        
        # D7 retention score
        d7_score = min(100, (current_metrics["d7_retention"] / self.sighted_live_targets["d7_retention_min"]) * 100)
        scores.append(d7_score)
        
        # D7→D30 conversion score
        conversion_score = min(100, (current_metrics["d7_to_d30_conversion"] / self.sighted_live_targets["d7_to_d30_conversion_min"]) * 100)
        scores.append(conversion_score)
        
        # Cohort size score
        cohort_score = min(100, (current_metrics["cohort_size"] / self.sighted_live_targets["cohort_size_min"]) * 100)
        scores.append(cohort_score)
        
        # Data quality score
        quality_score = current_metrics["data_quality_score"]
        scores.append(quality_score)
        
        return sum(scores) / len(scores)
    
    def _get_readiness_status(self, score: float) -> str:
        """Get readiness status from score"""
        if score >= 80:
            return "READY"
        elif score >= 60:
            return "CONDITIONAL"
        elif score >= 40:
            return "PROGRESSING"
        else:
            return "NOT_READY"
    
    def _identify_blocking_issues(self, current_metrics: Dict[str, Any]) -> List[str]:
        """Identify blocking issues for SIGHTED_LIVE"""
        issues = []
        
        if current_metrics["d7_retention"] < self.sighted_live_targets["d7_retention_min"]:
            issues.append("D7 retention below target")
        
        if current_metrics["d7_to_d30_conversion"] < self.sighted_live_targets["d7_to_d30_conversion_min"]:
            issues.append("D7→D30 conversion below target")
        
        if current_metrics["cohort_size"] < self.sighted_live_targets["cohort_size_min"]:
            issues.append("Cohort size below target")
        
        if current_metrics["identity_failures"] > self.sighted_live_targets["identity_failures_max"]:
            issues.append("Identity failures above target")
        
        return issues
    
    def _evaluate_readiness_gates(self, current_metrics: Dict[str, Any]) -> Dict[str, str]:
        """Evaluate individual readiness gates"""
        gates = {}
        
        gates["d7_retention"] = "PASS" if current_metrics["d7_retention"] >= self.sighted_live_targets["d7_retention_min"] else "FAIL"
        gates["d7_to_d30_conversion"] = "PASS" if current_metrics["d7_to_d30_conversion"] >= self.sighted_live_targets["d7_to_d30_conversion_min"] else "FAIL"
        gates["cohort_size"] = "PASS" if current_metrics["cohort_size"] >= self.sighted_live_targets["cohort_size_min"] else "FAIL"
        gates["identity_failures"] = "PASS" if current_metrics["identity_failures"] <= self.sighted_live_targets["identity_failures_max"] else "FAIL"
        gates["data_quality"] = "PASS" if current_metrics["data_quality_score"] >= self.sighted_live_targets["data_quality_score_min"] else "FAIL"
        
        return gates

def main():
    """Generate SIGHTED_LIVE plan"""
    
    print("🚀 Starting MERID Medium-Term SIGHTED_LIVE Plan Generation")
    
    plan_generator = MediumTermSightedLivePlan()
    plan = plan_generator.generate_sighted_live_plan()
    
    print(f"\n✅ SIGHTED_LIVE Plan Generated")
    print(f"📊 Current Readiness: {plan['current_assessment']['readiness_score']:.1f}%")
    print(f"🎯 Distance to SIGHTED_LIVE: {plan['gap_analysis']['readiness_distance']}")
    print(f"🗺️ Roadmap Phases: {len(plan['roadmap'])}")
    print(f"📅 Estimated Timeline: {plan['estimated_timeline']}")
    
    return plan_generator

if __name__ == "__main__":
    main()
