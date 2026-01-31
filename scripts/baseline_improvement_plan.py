#!/usr/bin/env python3
"""
MERID Baseline Improvement Plan
Week 1-2: Get non-zero D7 retention and meaningful cohort sizes
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from event_capture_system import EventCaptureSystem
from identity_resolution_service import IdentityResolutionService
from cohort_analysis_queries import CohortAnalysisQueries
from cohort_governance_integration import CohortGovernanceIntegration

class BaselineImprovementPlan:
    """Week 1-2: Improve baseline metrics to get non-zero D7 retention"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.event_system = EventCaptureSystem(db_path)
        self.identity_service = IdentityResolutionService(db_path)
        self.cohort_queries = CohortAnalysisQueries(db_path)
        self.governance_integration = CohortGovernanceIntegration(db_path)
        
        # Baseline improvement targets
        self.targets = {
            "min_d7_retention": 5.0,  # Get to 5% first, then aim for 40%
            "min_cohort_size": 10,   # Minimum users per cohort
            "max_identity_failures": 5.0,  # Reduce from 17.6%
            "min_significant_cohorts": 1   # At least 1 significant cohort
        }
    
    def generate_baseline_improvement_plan(self) -> Dict[str, Any]:
        """Generate comprehensive baseline improvement plan"""
        
        print("🎯 Generating Baseline Improvement Plan (Week 1-2)")
        print("=" * 60)
        
        # Current state analysis
        current_state = self.analyze_current_state()
        
        # Improvement strategies
        strategies = self.develop_improvement_strategies(current_state)
        
        # Action items by team
        action_items = self.generate_team_action_items(strategies)
        
        # Success metrics
        success_metrics = self.define_success_metrics()
        
        # Timeline
        timeline = self.create_2_week_timeline()
        
        plan = {
            "title": "MERID Baseline Improvement Plan",
            "subtitle": "Week 1-2: Get Non-Zero D7 Retention & Meaningful Cohorts",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_state": current_state,
            "targets": self.targets,
            "strategies": strategies,
            "action_items": action_items,
            "success_metrics": success_metrics,
            "timeline": timeline,
            "next_review": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        }
        
        # Save plan
        self.save_improvement_plan(plan)
        
        return plan
    
    def analyze_current_state(self) -> Dict[str, Any]:
        """Analyze current baseline state"""
        
        print("\n📊 Analyzing Current State...")
        
        # Get current governance report
        governance_report = self.governance_integration.evaluate_promotion_readiness(1)
        
        # Get current cohort data
        d7_d14_cohorts = self.cohort_queries.get_d7_d14_cohort_analysis()
        identity_stats = self.identity_service.get_identity_resolution_stats()
        
        # Calculate current metrics
        current_d7_retention = governance_report["key_metrics"]["latest_d7_retention"]
        current_cohort_size = d7_d14_cohorts[0]["cohort_size"] if d7_d14_cohorts else 0
        current_identity_failures = (identity_stats["security_validations"]["blocked_validations"] / 
                                   identity_stats["security_validations"]["total_validations"] * 100) if identity_stats["security_validations"]["total_validations"] > 0 else 0
        
        current_state = {
            "d7_retention_percent": current_d7_retention,
            "d7_to_d30_conversion": governance_report["key_metrics"]["latest_d7_to_d30_conversion"],
            "cohort_size": current_cohort_size,
            "identity_failure_rate": current_identity_failures,
            "total_cohorts": len(d7_d14_cohorts),
            "significant_cohorts": len([c for c in d7_d14_cohorts if c["cohort_size"] >= self.targets["min_cohort_size"]]),
            "overall_readiness": governance_report["promotion_readiness"],
            "blocking_gates": len(governance_report["promotion_decision"]["blocking_gates"]),
            "warning_gates": len(governance_report["promotion_decision"]["warning_gates"])
        }
        
        print(f"  • D7 Retention: {current_d7_retention}% (target: {self.targets['min_d7_retention']}%)")
        print(f"  • Cohort Size: {current_cohort_size} (target: {self.targets['min_cohort_size']})")
        print(f"  • Identity Failures: {current_identity_failures}% (target: {self.targets['max_identity_failures']}%)")
        print(f"  • Overall Status: {current_state['overall_readiness']}")
        
        return current_state
    
    def develop_improvement_strategies(self, current_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Develop improvement strategies based on current state"""
        
        print("\n🎯 Developing Improvement Strategies...")
        
        strategies = []
        
        # Strategy 1: Increase User Activity
        if current_state["d7_retention_percent"] == 0:
            strategies.append({
                "name": "Increase User Activity & Engagement",
                "priority": "CRITICAL",
                "focus": "Get users to return on Day 7",
                "tactics": [
                    "Increase internal user testing frequency",
                    "Extend cohort analysis window to 14+ days",
                    "Add more meaningful core value events",
                    "Improve onboarding flow to drive D7 return"
                ],
                "expected_impact": "Move D7 retention from 0% to 5-10%"
            })
        
        # Strategy 2: Grow Cohort Sizes
        if current_state["cohort_size"] < self.targets["min_cohort_size"]:
            strategies.append({
                "name": "Grow Cohort Sizes",
                "priority": "CRITICAL",
                "focus": "Increase number of users per cohort",
                "tactics": [
                    "Run internal user simulations",
                    "Extend data collection window",
                    "Aggregate multiple small cohorts",
                    "Add synthetic test users for validation"
                ],
                "expected_impact": "Increase cohort size from {current_state['cohort_size']} to 10+ users"
            })
        
        # Strategy 3: Reduce Identity Failures
        if current_state["identity_failure_rate"] > self.targets["max_identity_failures"]:
            strategies.append({
                "name": "Reduce Identity Resolution Failures",
                "priority": "HIGH",
                "focus": "Clean up identity and security validation",
                "tactics": [
                    "Review and adjust security validation rules",
                    "Improve client-side event validation",
                    "Fix rate limiting configuration",
                    "Enhance PII detection accuracy"
                ],
                "expected_impact": "Reduce identity failures from {current_state['identity_failure_rate']:.1f}% to <5%"
            })
        
        # Strategy 4: Improve Data Quality
        if current_state["significant_cohorts"] == 0:
            strategies.append({
                "name": "Improve Data Quality",
                "priority": "HIGH",
                "focus": "Ensure high-quality cohort data",
                "tactics": [
                    "Add data validation at event capture",
                    "Implement UTC timestamp consistency",
                    "Add event schema validation",
                    "Improve error handling and logging"
                ],
                "expected_impact": "Get at least 1 statistically significant cohort"
            })
        
        print(f"  • Developed {len(strategies)} improvement strategies")
        return strategies
    
    def generate_team_action_items(self, strategies: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate specific action items by team"""
        
        print("\n📋 Generating Team Action Items...")
        
        action_items = {
            "product_team": [],
            "engineering_team": [],
            "data_team": [],
            "analytics_team": []
        }
        
        for strategy in strategies:
            for tactic in strategy["tactics"]:
                action_item = {
                    "strategy": strategy["name"],
                    "tactic": tactic,
                    "priority": strategy["priority"],
                    "due_date": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
                    "status": "PENDING"
                }
                
                # Assign to appropriate team
                if "user" in tactic.lower() or "onboarding" in tactic.lower():
                    action_items["product_team"].append(action_item)
                elif "client-side" in tactic.lower() or "rate limiting" in tactic.lower():
                    action_items["engineering_team"].append(action_item)
                elif "data" in tactic.lower() or "validation" in tactic.lower():
                    action_items["data_team"].append(action_item)
                else:
                    action_items["analytics_team"].append(action_item)
        
        # Print summary
        for team, items in action_items.items():
            print(f"  • {team}: {len(items)} action items")
        
        return action_items
    
    def define_success_metrics(self) -> Dict[str, Any]:
        """Define success metrics for baseline improvement"""
        
        return {
            "primary_metrics": {
                "d7_retention": {
                    "target": f"≥{self.targets['min_d7_retention']}%",
                    "current": "0%",
                    "measurement": "Cohort analysis of user_first_active → session_active on Day 7"
                },
                "cohort_size": {
                    "target": f"≥{self.targets['min_cohort_size']} users",
                    "current": "2 users",
                    "measurement": "Number of users in latest cohort"
                },
                "identity_failures": {
                    "target": f"≤{self.targets['max_identity_failures']}%",
                    "current": "17.6%",
                    "measurement": "Security validation failure rate"
                }
            },
            "secondary_metrics": {
                "d7_to_d30_conversion": {
                    "target": "≥5%",
                    "current": "0%",
                    "measurement": "D7 retained users who return on D30"
                },
                "significant_cohorts": {
                    "target": "≥1",
                    "current": "0",
                    "measurement": "Cohorts with statistically significant retention"
                }
            },
            "governance_status": {
                "target": "CONDITIONAL",
                "current": "NOT_READY",
                "measurement": "Overall governance readiness assessment"
            }
        }
    
    def create_2_week_timeline(self) -> List[Dict[str, Any]]:
        """Create 2-week improvement timeline"""
        
        timeline = []
        start_date = datetime.now(timezone.utc)
        
        # Week 1
        timeline.extend([
            {
                "week": 1,
                "day": 1,
                "date": (start_date + timedelta(days=0)).strftime("%Y-%m-%d"),
                "focus": "Baseline Assessment & Planning",
                "activities": [
                    "Complete current state analysis",
                    "Assign team action items",
                    "Set up monitoring and alerting"
                ]
            },
            {
                "week": 1,
                "day": 3,
                "date": (start_date + timedelta(days=2)).strftime("%Y-%m-%d"),
                "focus": "User Activity Increase",
                "activities": [
                    "Increase internal user testing",
                    "Extend data collection window",
                    "Add core value events"
                ]
            },
            {
                "week": 1,
                "day": 5,
                "date": (start_date + timedelta(days=4)).strftime("%Y-%m-%d"),
                "focus": "Identity & Data Quality",
                "activities": [
                    "Fix security validation rules",
                    "Improve event validation",
                    "Enhance error handling"
                ]
            },
            {
                "week": 1,
                "day": 7,
                "date": (start_date + timedelta(days=6)).strftime("%Y-%m-%d"),
                "focus": "Week 1 Review",
                "activities": [
                    "Measure progress against targets",
                    "Adjust strategies as needed",
                    "Prepare Week 2 plan"
                ]
            }
        ])
        
        # Week 2
        timeline.extend([
            {
                "week": 2,
                "day": 8,
                "date": (start_date + timedelta(days=7)).strftime("%Y-%m-%d"),
                "focus": "Cohort Size Growth",
                "activities": [
                    "Run user simulations",
                    "Aggregate small cohorts",
                    "Add synthetic test users"
                ]
            },
            {
                "week": 2,
                "day": 10,
                "date": (start_date + timedelta(days=9)).strftime("%Y-%m-%d"),
                "focus": "Optimization",
                "activities": [
                    "Optimize event capture",
                    "Fine-tune identity resolution",
                    "Improve data quality"
                ]
            },
            {
                "week": 2,
                "day": 12,
                "date": (start_date + timedelta(days=11)).strftime("%Y-%m-%d"),
                "focus": "Validation",
                "activities": [
                    "Validate all improvements",
                    "Run stress tests",
                    "Document changes"
                ]
            },
            {
                "week": 2,
                "day": 14,
                "date": (start_date + timedelta(days=13)).strftime("%Y-%m-%d"),
                "focus": "Final Assessment",
                "activities": [
                    "Complete 2-week assessment",
                    "Run governance evaluation",
                    "Decide on next steps"
                ]
            }
        ])
        
        return timeline
    
    def save_improvement_plan(self, plan: Dict[str, Any]):
        """Save improvement plan to file"""
        
        # Save JSON
        json_file = "baseline_improvement_plan.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2)
        
        # Save HTML report
        html_report = self.create_html_report(plan)
        html_file = "baseline_improvement_plan.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"\n📄 Improvement plan saved to {json_file}")
        print(f"📄 HTML report saved to {html_file}")
    
    def create_html_report(self, plan: Dict[str, Any]) -> str:
        """Create HTML report for improvement plan"""
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{plan['title']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .section {{ margin: 30px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
        .critical {{ border-left: 5px solid #d32f2f; }}
        .high {{ border-left: 5px solid #f57c00; }}
        .medium {{ border-left: 5px solid #1976d2; }}
        .metric {{ background: #f9f9f9; padding: 10px; margin: 5px 0; border-radius: 3px; }}
        .target {{ color: #2e7d32; font-weight: bold; }}
        .current {{ color: #d32f2f; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
        .timeline-day {{ background: #f5f5f5; padding: 10px; margin: 5px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{plan['title']}</h1>
        <p><em>{plan['subtitle']}</em></p>
        <p>Generated: {plan['generated_at']}</p>
        <p>Next Review: {plan['next_review']}</p>
    </div>
    
    <div class="section">
        <h2>Current State Analysis</h2>
        <div class="metric">
            <strong>D7 Retention:</strong> <span class="current">{plan['current_state']['d7_retention_percent']}%</span> → <span class="target">{plan['targets']['min_d7_retention']}%</span>
        </div>
        <div class="metric">
            <strong>Cohort Size:</strong> <span class="current">{plan['current_state']['cohort_size']}</span> → <span class="target">{plan['targets']['min_cohort_size']}</span>
        </div>
        <div class="metric">
            <strong>Identity Failures:</strong> <span class="current">{plan['current_state']['identity_failure_rate']:.1f}%</span> → <span class="target">{plan['targets']['max_identity_failures']}%</span>
        </div>
        <div class="metric">
            <strong>Overall Status:</strong> {plan['current_state']['overall_readiness']}
        </div>
    </div>
    
    <div class="section">
        <h2>Improvement Strategies</h2>
"""
        
        for strategy in plan['strategies']:
            priority_class = strategy['priority'].lower()
            html += f"""
        <div class="section {priority_class}">
            <h3>{strategy['name']}</h3>
            <p><strong>Priority:</strong> {strategy['priority']}</p>
            <p><strong>Focus:</strong> {strategy['focus']}</p>
            <p><strong>Expected Impact:</strong> {strategy['expected_impact']}</p>
            <h4>Tactics:</h4>
            <ul>
"""
            for tactic in strategy['tactics']:
                html += f"                <li>{tactic}</li>\n"
            html += """
            </ul>
        </div>
"""
        
        html += """
    </div>
    
    <div class="section">
        <h2>Success Metrics</h2>
        <h3>Primary Metrics</h3>
"""
        
        for metric_name, metric_data in plan['success_metrics']['primary_metrics'].items():
            html += f"""
        <div class="metric">
            <strong>{metric_name.replace('_', ' ').title()}:</strong> 
            <span class="current">{metric_data['current']}</span> → <span class="target">{metric_data['target']}</span>
            <br><em>{metric_data['measurement']}</em>
        </div>
"""
        
        html += """
    </div>
    
    <div class="section">
        <h2>2-Week Timeline</h2>
"""
        
        for day_plan in plan['timeline']:
            html += f"""
        <div class="timeline-day">
            <strong>Week {day_plan['week']}, Day {day_plan['day']} ({day_plan['date']})</strong>
            <p><strong>Focus:</strong> {day_plan['focus']}</p>
            <ul>
"""
            for activity in day_plan['activities']:
                html += f"                <li>{activity}</li>\n"
            html += """
            </ul>
        </div>
"""
        
        html += """
    </div>
</body>
</html>
"""
        
        return html

def main():
    """Generate baseline improvement plan"""
    
    print("🚀 Starting MERID Baseline Improvement Plan Generation")
    
    plan_generator = BaselineImprovementPlan()
    plan = plan_generator.generate_baseline_improvement_plan()
    
    print(f"\n✅ Baseline Improvement Plan Generated")
    print(f"📊 Current D7 Retention: {plan['current_state']['d7_retention_percent']}%")
    print(f"🎯 Target D7 Retention: {plan['targets']['min_d7_retention']}%")
    print(f"📋 Total Action Items: {sum(len(items) for items in plan['action_items'].values())}")
    print(f"📅 Timeline: 2 weeks with detailed daily plan")
    
    return plan_generator

if __name__ == "__main__":
    main()
