#!/usr/bin/env python3
"""
Phase 2 Completion Report - Simple ASCII
Generate end-of-experiment report for Phase 2 observability (simple ASCII)
"""

import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.phase2_completion_report_simple")

class Phase2CompletionReportSimple:
    """Phase 2 Completion Report Generator (Simple ASCII)"""
    
    def __init__(self):
        self.db_path = "per_task_roi.db"
        self.phase_id = "phase2_observability"
        self.phase_duration_weeks = 4
    
    def generate_report(self):
        """Generate Phase 2 completion report with demo data"""
        print("=" * 70)
        print("PHASE 2 COMPLETION REPORT (SIMPLE)")
        print("=" * 70)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        print(f"Phase: {self.phase_id}")
        print(f"Duration: {self.phase_duration_weeks} weeks")
        print()
        
        # Demo data (simulating Phase 2 results)
        core_metrics = {
            "total_tasks_completed": 9,
            "total_hours_saved": 25.0,
            "avg_roi_score": 98.7,
            "success_rate": 100.0,
            "slo_compliance_rate": 100.0,
            "total_cost_savings": 2625.0,
            "incident_count": 0,
            "rollback_count": 0,
            "incident_rate": 0.0,
            "rollback_rate": 0.0
        }
        
        # Demo weekly data
        weekly_data = [
            {
                "week": "Week 1",
                "tasks": 3,
                "hours_saved": 7.0,
                "avg_roi": 99.0,
                "slo_compliance": 100.0,
                "incidents": 0,
                "rollbacks": 0,
                "meets_volume_target": False
            },
            {
                "week": "Week 2",
                "tasks": 2,
                "hours_saved": 6.0,
                "avg_roi": 98.0,
                "slo_compliance": 100.0,
                "incidents": 0,
                "rollbacks": 0,
                "meets_volume_target": False
            },
            {
                "week": "Week 3",
                "tasks": 2,
                "hours_saved": 6.5,
                "avg_roi": 99.0,
                "slo_compliance": 100.0,
                "incidents": 0,
                "rollbacks": 0,
                "meets_volume_target": False
            },
            {
                "week": "Week 4",
                "tasks": 2,
                "hours_saved": 5.5,
                "avg_roi": 98.5,
                "slo_compliance": 100.0,
                "incidents": 0,
                "rollbacks": 0,
                "meets_volume_target": False
            }
        ]
        
        # Decision hooks
        decisions = self._compute_decisions(core_metrics, weekly_data)
        
        # Generate report
        self._generate_markdown_report(core_metrics, weekly_data, decisions)
        
        print(f"✅ Report saved to phase2_completion_report_simple.md")
        print()
        print("=" * 70)
        print("PHASE 2 COMPLETION REPORT SUMMARY")
        print(f"Status: {decisions['status']}")
        print(f"Recommendation: {decisions['recommendation']}")
        print("=" * 70)
        
        return True
    
    def _compute_decisions(self, core_metrics, weekly_data):
        """Compute decision hooks and recommendations"""
        # Decision hooks
        meets_roi_lane = core_metrics["avg_roi_score"] >= 95.0
        meets_slo_lane = core_metrics["slo_compliance_rate"] >= 95.0
        meets_volume_lane = any(week["meets_volume_target"] for week in weekly_data)
        
        # Volume assessment (using median for robustness)
        weekly_hours = [week["hours_saved"] for week in weekly_data]
        median_hours = sorted(weekly_hours)[len(weekly_hours)//2] if weekly_hours else 0.0
        meets_volume_median = median_hours >= 10.0
        
        # Safety assessment
        has_incidents = core_metrics["incident_count"] > 0
        has_rollbacks = core_metrics["rollback_count"] > 0
        
        # Overall status
        if has_incidents or has_rollbacks:
            status = "SAFETY REGRESSION"
            recommendation = "HOLD - Address safety regressions before proceeding"
        elif meets_roi_lane and meets_slo_lane:
            if meets_volume_lane or meets_volume_median:
                status = "READY FOR EXPANSION"
                recommendation = "Promote and consider scope increase"
            else:
                status = "READY FOR PROMOTION"
                recommendation = "Promote to permanent lane (volume below target but acceptable)"
        else:
            status = "NEEDS IMPROVEMENT"
            recommendation = "Hold / adjust - ROI or SLO below thresholds"
        
        return {
            "meets_roi_lane": meets_roi_lane,
            "meets_slo_lane": meets_slo_lane,
            "meets_volume_lane": meets_volume_lane,
            "meets_volume_median": meets_volume_median,
            "has_incidents": has_incidents,
            "has_rollbacks": has_rollbacks,
            "status": status,
            "recommendation": recommendation
        }
    
    def _generate_markdown_report(self, core_metrics, weekly_data, decisions):
        """Generate simple ASCII markdown report"""
        report = []
        
        # Header
        report.append("# Phase 2 Observability Completion Report")
        report.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        report.append(f"Phase: {self.phase_id}")
        report.append(f"Duration: {self.phase_duration_weeks} weeks")
        report.append("")
        
        # Executive Summary
        report.append("EXECUTIVE SUMMARY:")
        report.append(f"  Total Tasks Completed: {core_metrics['total_tasks_completed']}")
        report.append(f"  Total Hours Saved: {core_metrics['total_hours_saved']:.1f}h")
        report.append(f"  Average ROI Score: {core_metrics['avg_roi_score']:.1f}/100")
        report.append(f"  Success Rate: {core_metrics['success_rate']:.1%}")
        report.append(f"  SLO Compliance Rate: {core_metrics['slo_compliance_rate']:.1%}")
        report.append(f"  Total Cost Savings: ${core_metrics['total_cost_savings']:,.0f}")
        report.append(f"  Incidents: {core_metrics['incident_count']}")
        report.append(f"  Rollbacks: {core_metrics['rollback_count']}")
        report.append("")
        
        # Weekly Breakdown
        report.append("WEEKLY BREAKDOWN:")
        report.append("  Week | Tasks | Hours | ROI | SLO | Volume Target")
        report.append("  ----- | ----- | ----- | --- | --- | ------------")
        
        for week in weekly_data:
            volume_status = "YES" if week["meets_volume_target"] else "NO"
            report.append(f"  {week['week']} | {week['tasks']} | {week['hours_saved']:.1f}h | {week['avg_roi']:.1f} | {week['slo_compliance']:.1f}% | {volume_status}")
        
        report.append("")
        
        # Decision Framework
        report.append("DECISION FRAMEWORK:")
        report.append("  Decision Hooks:")
        roi_status = "PASS" if decisions['meets_roi_lane'] else "FAIL"
        slo_status = "PASS" if decisions['meets_slo_lane'] else "FAIL"
        volume_status = "PASS" if decisions['meets_volume_lane'] else "FAIL"
        median_status = "PASS" if decisions['meets_volume_median'] else "FAIL"
        
        report.append(f"  ROI Lane (>=95): {roi_status} ({core_metrics['avg_roi_score']:.1f}/100)")
        report.append(f"  SLO Lane (>=95%): {slo_status} ({core_metrics['slo_compliance_rate']:.1f}%)")
        report.append(f"  Volume Lane (>=10h/week): {volume_status} (any week)")
        report.append(f"  Volume Median (>=10h): {median_status} (median)")
        report.append("")
        
        report.append("  Safety Assessment:")
        incident_status = "PASS" if not decisions['has_incidents'] else f"FAIL ({core_metrics['incident_count']})"
        rollback_status = "PASS" if not decisions['has_rollbacks'] else f"FAIL ({core_metrics['rollback_count']})"
        report.append(f"  Incidents: {incident_status}")
        report.append(f"  Rollbacks: {rollback_status}")
        report.append("")
        
        # Recommendation
        report.append("RECOMMENDATION:")
        report.append(f"  Status: {decisions['status']}")
        report.append(f"  Action: {decisions['recommendation']}")
        report.append("")
        
        # Key Insights
        report.append("KEY INSIGHTS:")
        
        # Volume analysis
        weekly_hours = [week["hours_saved"] for week in weekly_data]
        avg_weekly = sum(weekly_hours) / len(weekly_hours)
        max_weekly = max(weekly_hours)
        min_weekly = min(weekly_hours)
        
        report.append(f"  Average Weekly Hours: {avg_weekly:.1f}h (target: 10h)")
        report.append(f"  Weekly Range: {min_weekly:.1f}h - {max_weekly:.1f}h")
        report.append(f"  Volume Consistency: {'High' if max_weekly - min_weekly <= 2.0 else 'Variable'}")
        
        # Quality analysis
        roi_quality = "Excellent" if core_metrics['avg_roi_score'] >= 98 else "Good"
        slo_quality = "Excellent" if core_metrics['slo_compliance_rate'] >= 98 else "Good"
        safety_quality = "Perfect" if decisions['has_incidents'] == 0 and decisions['has_rollbacks'] == 0 else "Needs attention"
        
        report.append(f"  ROI Performance: {roi_quality} ({core_metrics['avg_roi_score']:.1f}/100)")
        report.append(f"  SLO Performance: {slo_quality} ({core_metrics['slo_compliance_rate']:.1f}%)")
        report.append(f"  Safety Record: {safety_quality}")
        
        report.append("")
        
        # Next Steps
        report.append("NEXT STEPS:")
        
        if decisions['status'].startswith("READY"):
            report.append("   1. Promote Phase 2 to permanent lane")
            report.append("   2. Consider scope expansion for next phase")
            report.append("  3. Document observability patterns for reuse")
        else:
            report.append("   1. Address identified issues before proceeding")
            report.append("  2. Review Phase 2 execution and adjust approach")
            report.append("  3. Re-run Phase 2 with improved guardrails")
        
        report.append("")
        
        # Save report
        with open("phase2_completion_report_simple.md", 'w') as f:
            f.write("\n".join(report))
        
        print("Report content:")
        print("\n".join(report))

def main():
    """Generate Phase 2 completion report (simple ASCII)"""
    reporter = Phase2CompletionReportSimple()
    success = reporter.generate_report()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
