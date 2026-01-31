#!/usr/bin/env python3
"""
Phase 2 Completion Report Script
Generate end-of-experiment report for Phase 2 observability
"""

import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.phase2_completion_report")

class Phase2CompletionReport:
    """Phase 2 Completion Report Generator"""
    
    def __init__(self):
        self.db_path = "per_task_roi.db"
        self.phase_id = "phase2_observability"
        self.phase_duration_weeks = 4
    
    def generate_report(self):
        """Generate Phase 2 completion report"""
        print("=" * 70)
        print("PHASE 2 COMPLETION REPORT")
        print("=" * 70)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        print(f"Phase: {self.phase_id}")
        print(f"Duration: {self.phase_duration_weeks} weeks")
        print()
        
        # Connect to database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get phase start date
            phase_start_date = datetime.now() - timedelta(weeks=self.phase_duration_weeks)
            
            # Core aggregations
            core_metrics = self._get_core_metrics(cursor, phase_start_date)
            
            if not core_metrics["total_tasks"]:
                print("❌ No Phase 2 data found in database")
                return False
            
            # Weekly breakdown
            weekly_data = self._get_weekly_breakdown(cursor, phase_start_date)
            
            # Decision hooks
            decisions = self._compute_decisions(core_metrics, weekly_data)
            
            # Generate report
            self._generate_markdown_report(core_metrics, weekly_data, decisions)
            
            conn.close()
            
            print(f"✅ Report saved to phase2_completion_report.md")
            print()
            print("=" * 70)
            print("PHASE 2 COMPLETION REPORT SUMMARY")
            print(f"Status: {decisions['status']}")
            print(f"Recommendation: {decisions['recommendation']}")
            print("=" * 70)
            
            return True
            
        except Exception as e:
            print(f"❌ Error generating report: {e}")
            return False
    
    def _get_core_metrics(self, cursor, start_date):
        """Get core metrics for Phase 2"""
        # Filter by Phase 2 tasks
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks_completed,
                SUM(human_time_saved_hours) as total_hours_saved,
                AVG(roi_score) as avg_roi_score,
                COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'green') * 100.0 / COUNT(*) as slo_compliance_rate,
                SUM(cost_savings_usd) as total_cost_savings,
                COUNT(*) FILTER (WHERE incidents > 0) as incident_count,
                COUNT(*) FILTER (WHERE rollback_required = true) as rollback_count
            FROM per_task_roi_log
            WHERE date >= date(?, '-4 weeks')
            AND batch_id LIKE 'phase2_observability_%'
        """, (start_date.strftime('%Y-%m-%d'),))
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            return {
                "total_tasks_completed": result[0],
                "total_hours_saved": result[1] or 0.0,
                "avg_roi_score": result[2] or 0.0,
                "success_rate": result[3] or 0.0,
                "slo_compliance_rate": result[4] or 0.0,
                "total_cost_savings": result[5] or 0.0,
                "incident_count": result[6] or 0,
                "rollback_count": result[7] or 0,
                "incident_rate": (result[6] or 0) / result[0] * 100,
                "rollback_rate": (result[7] or 0) / result[0] * 100
            }
        else:
            return {}
    
    def _get_weekly_breakdown(self, cursor, start_date):
        """Get weekly breakdown for Phase 2"""
        weekly_data = []
        
        for week_offset in range(self.phase_duration_weeks):
            week_start = start_date + timedelta(weeks=week_offset)
            week_end = week_start + timedelta(days=6)
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as tasks,
                    SUM(human_time_saved_hours) as hours_saved,
                    AVG(roi_score) as avg_roi,
                    COUNT(*) FILTER (WHERE slo_compliance = 'green') * 100.0 / COUNT(*) as slo_compliance,
                    COUNT(*) FILTER (WHERE incidents > 0) as incidents,
                    COUNT(*) FILTER (WHERE rollback_required = true) as rollbacks
                FROM per_task_roi_log
                WHERE date >= date(?, '-7 days')
                AND date <= date(?, '+7 days')
                AND batch_id LIKE 'phase2_observability_%'
            """, (week_start.strftime('%Y-%m-%d'), week_end.strftime('%Y-%m-%d')))
            
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                week_num = week_offset + 1
                weekly_data.append({
                    "week": f"Week {week_num}",
                    "tasks": result[0],
                    "hours_saved": result[1] or 0.0,
                    "avg_roi": result[2] or 0.0,
                    "slo_compliance": result[3] or 0.0,
                    "incidents": result[4] or 0,
                    "rollbacks": result[5] or 0,
                    "meets_volume_target": (result[1] or 0.0) >= 10.0
                })
        
        return weekly_data
    
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
            status = "❌ SAFETY REGRESSION"
            recommendation = "HOLD - Address safety regressions before proceeding"
        elif meets_roi_lane and meets_slo_lane:
            if meets_volume_lane or meets_volume_median:
                status = "✅ READY FOR EXPANSION"
                recommendation = "Promote and consider scope increase"
            else:
                status = "✅ READY FOR PROMOTION"
                recommendation = "Promote to permanent lane (volume below target but acceptable)"
        else:
            status = "⚠️ NEEDS IMPROVEMENT"
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
        """Generate markdown report"""
        report = []
        
        # Header
        report.append("# Phase 2 Observability Completion Report")
        report.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d')}")
        report.append(f"**Phase:** {self.phase_id}")
        report.append(f"**Duration:** {self.phase_duration_weeks} weeks")
        report.append("")
        
        # Executive Summary
        report.append("## Executive Summary")
        report.append(f"- **Total Tasks Completed:** {core_metrics['total_tasks_completed']}")
        report.append(f"- **Total Hours Saved:** {core_metrics['total_hours_saved']:.1f}h")
        report.append(f"- **Average ROI Score:** {core_metrics['avg_roi_score']:.1f}/100")
        report.append(f"- **Success Rate:** {core_metrics['success_rate']:.1%}")
        report.append(f"- **SLO Compliance Rate:** {core_metrics['slo_compliance_rate']:.1%}")
        report.append(f"- **Total Cost Savings:** ${core_metrics['total_cost_savings']:,.0f}")
        report.append(f"- **Incidents:** {core_metrics['incident_count']}")
        report.append(f"- **Rollbacks:** {core_metrics['rollback_count']}")
        report.append("")
        
        # Weekly Breakdown
        report.append("## Weekly Breakdown")
        report.append("| Week | Tasks | Hours Saved | Avg ROI | SLO Compliance | Volume Target Met |")
        report.append("|------|-------|-------------|---------|------------------|-------------------|")
        
        for week in weekly_data:
            volume_status = "✅" if week["meets_volume_target"] else "❌"
            report.append(f"| {week['week']} | {week['tasks']} | {week['hours_saved']:.1f}h | {week['avg_roi']:.1f} | {week['slo_compliance']:.1%} | {volume_status} |")
        
        report.append("")
        
        # Decision Framework
        report.append("## Decision Framework")
        report.append("### Decision Hooks")
        report.append(f"- **ROI Lane (≥95):** {'✅' if decisions['meets_roi_lane'] else '❌'} {core_metrics['avg_roi_score']:.1f}/100")
        report.append(f"- **SLO Lane (≥95%):** {'✅' if decisions['meets_slo_lane'] else '❌'} {core_metrics['slo_compliance_rate']:.1%}")
        report.append(f"- **Volume Lane (≥10h/week):** {'✅' if decisions['meets_volume_lane'] else '❌'} (any week)")
        report.append(f"- **Volume Median (≥10h):** {'✅' if decisions['meets_volume_median'] else '❌'} (median)")
        report.append("")
        
        report.append("### Safety Assessment")
        incidents_text = "✅ None" if not decisions['has_incidents'] else f"❌ {core_metrics['incident_count']}"
        rollbacks_text = "✅ None" if not decisions['has_rollbacks'] else f"❌ {core_metrics['rollback_count']}"
        report.append(f"- **Incidents:** {incidents_text}")
        report.append(f"- **Rollbacks:** {rollbacks_text}")
        report.append("")
        
        # Recommendation
        report.append("## Recommendation")
        report.append(f"**Status:** {decisions['status']}")
        report.append(f"**Action:** {decisions['recommendation']}")
        report.append("")
        
        # Key Insights
        report.append("## Key Insights")
        
        # Volume analysis
        weekly_hours = [week["hours_saved"] for week in weekly_data]
        avg_weekly = sum(weekly_hours) / len(weekly_hours)
        max_weekly = max(weekly_hours)
        min_weekly = min(weekly_hours)
        
        report.append(f"- **Average Weekly Hours:** {avg_weekly:.1f}h (target: 10h)")
        report.append(f"- **Weekly Range:** {min_weekly:.1f}h - {max_weekly:.1f}h")
        report.append(f"- **Volume Consistency:** {'High' if max_weekly - min_weekly <= 2.0 else 'Variable'}")
        
        # Quality analysis
        report.append(f"- **ROI Performance:** {'Excellent' if core_metrics['avg_roi_score'] >= 98 else 'Good'} ({core_metrics['avg_roi_score']:.1f}/100)")
        report.append(f"- **SLO Performance:** {'Excellent' if core_metrics['slo_compliance_rate'] >= 98 else 'Good'} ({core_metrics['slo_compliance_rate']:.1f}%)")
        report.append(f"- **Safety Record:** {'Perfect' if decisions['has_incidents'] == 0 and decisions['has_rollbacks'] == 0 else 'Needs attention'}")
        
        report.append("")
        
        # Next Steps
        report.append("## Next Steps")
        
        if decisions['status'].startswith("✅"):
            report.append("1. **Promote Phase 2 to permanent lane**")
            report.append("2. **Consider scope expansion** for next phase")
            report.append("3. **Document observability patterns** for reuse")
        else:
            report.append("1. **Address identified issues** before proceeding")
            report.append("2. **Review Phase 2 execution** and adjust approach")
            report.append("3. **Re-run Phase 2** with improved guardrails")
        
        report.append("")
        
        # Save report
        with open("phase2_completion_report.md", 'w') as f:
            f.write("\n".join(report))
        
        print("Report content:")
        print("\n".join(report))

def main():
    """Generate Phase 2 completion report"""
    reporter = Phase2CompletionReport()
    success = reporter.generate_report()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
