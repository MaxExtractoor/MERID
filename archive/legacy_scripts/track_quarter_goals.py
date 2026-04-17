#!/usr/bin/env python3
"""
Quarter Goal Tracking System
Track progress toward Q1 goal: ≥40 dev hours/month saved
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.quarter_tracking")

class QuarterGoalTracker:
    """Track progress toward quarter goals"""
    
    def __init__(self):
        self.quarter_goal = {
            "target": "By end of quarter, swarm saves ≥ 40 dev hours/month with defect rate ≤ 5% and 0 production incidents attributable to agents",
            "metrics": {
                "monthly_hours_saved": 40,
                "defect_rate_max": 0.05,
                "production_incidents": 0,
                "avg_roi_score": 85.0
            },
            "tracking": "Weekly ROI table + monthly checkpoint",
            "quarter_start": datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        }
    
    def get_current_progress(self) -> dict:
        """Get current progress toward quarter goals"""
        conn = sqlite3.connect("per_task_roi.db")
        cursor = conn.cursor()
        
        # Calculate quarter start date
        quarter_start = datetime.fromisoformat(self.quarter_goal["quarter_start"])
        current_date = datetime.now()
        
        # Get all tasks this quarter
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_tasks,
                SUM(human_time_saved_hours) as total_time_saved,
                AVG(roi_score) as avg_roi_score,
                AVG(quality_improvement) as avg_quality_improvement,
                SUM(cost_savings_usd) as total_cost_savings,
                SUM(defects_avoided) as total_defects_avoided,
                SUM(incidents) as total_incidents,
                SUM(near_misses) as total_near_misses,
                MIN(date) as first_task_date,
                MAX(date) as last_task_date
            FROM per_task_roi
            WHERE date >= ?
        """, (quarter_start.isoformat(),))
        
        result = cursor.fetchone()
        
        # Get monthly breakdown
        cursor.execute("""
            SELECT 
                strftime('%Y-%m', date) as month,
                SUM(human_time_saved_hours) as monthly_time_saved,
                COUNT(*) as monthly_tasks,
                AVG(roi_score) as monthly_avg_roi,
                SUM(incidents) as monthly_incidents
            FROM per_task_roi
            WHERE date >= ?
            GROUP BY strftime('%Y-%m', date)
            ORDER BY month
        """, (quarter_start.isoformat(),))
        
        monthly_breakdown = cursor.fetchall()
        
        conn.close()
        
        if result and result[0] > 0:
            # Calculate months in quarter so far
            months_elapsed = ((current_date.year - quarter_start.year) * 12 + 
                            current_date.month - quarter_start.month) + 1
            
            # Calculate monthly average
            avg_monthly_hours = result[2] / months_elapsed if months_elapsed > 0 else 0
            
            # Calculate defect rate (simplified - using incidents as proxy)
            defect_rate = result[7] / result[0] if result[0] > 0 else 0
            
            # Progress toward goals
            progress = {
                "quarter_period": f"{quarter_start.strftime('%Y-%m')} to {current_date.strftime('%Y-%m')}",
                "months_elapsed": months_elapsed,
                "total_metrics": {
                    "total_tasks": result[0],
                    "successful_tasks": result[1],
                    "success_rate": result[1] / result[0],
                    "total_time_saved_hours": result[2],
                    "avg_roi_score": result[3] or 0,
                    "avg_quality_improvement": result[4] or 0,
                    "total_cost_savings_usd": result[5] or 0,
                    "total_defects_avoided": result[6] or 0,
                    "total_incidents": result[7] or 0,
                    "total_near_misses": result[8] or 0
                },
                "monthly_averages": {
                    "avg_hours_saved_per_month": avg_monthly_hours,
                    "avg_tasks_per_month": result[0] / months_elapsed,
                    "avg_roi_per_month": result[3] or 0
                },
                "monthly_breakdown": [
                    {
                        "month": row[0],
                        "hours_saved": row[1],
                        "tasks": row[2],
                        "avg_roi": row[3],
                        "incidents": row[4]
                    }
                    for row in monthly_breakdown
                ],
                "goal_progress": {
                    "hours_saved_progress": avg_monthly_hours / self.quarter_goal["metrics"]["monthly_hours_saved"],
                    "roi_score_progress": (result[3] or 0) / self.quarter_goal["metrics"]["avg_roi_score"],
                    "defect_rate_compliance": defect_rate <= self.quarter_goal["metrics"]["defect_rate_max"],
                    "incident_compliance": (result[7] or 0) <= self.quarter_goal["metrics"]["production_incidents"]
                },
                "on_track": {
                    "hours_saved": avg_monthly_hours >= self.quarter_goal["metrics"]["monthly_hours_saved"],
                    "roi_score": (result[3] or 0) >= self.quarter_goal["metrics"]["avg_roi_score"],
                    "defect_rate": defect_rate <= self.quarter_goal["metrics"]["defect_rate_max"],
                    "incidents": (result[7] or 0) <= self.quarter_goal["metrics"]["production_incidents"]
                }
            }
            
            # Overall on track status
            progress["overall_on_track"] = all(progress["on_track"].values())
            
            return progress
        else:
            return {
                "quarter_period": f"{quarter_start.strftime('%Y-%m')} to {current_date.strftime('%Y-%m')}",
                "status": "no_data",
                "message": "No tasks completed this quarter"
            }
    
    def generate_status_report(self) -> dict:
        """Generate comprehensive quarter status report"""
        print("=" * 70)
        print("QUARTER GOAL TRACKING")
        print("=" * 70)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        print(f"Goal: {self.quarter_goal['target']}")
        print()
        
        progress = self.get_current_progress()
        
        if progress.get("status") == "no_data":
            print("❌ NO DATA - No tasks completed this quarter")
            print("Action: Start logging swarm tasks to track progress")
            return progress
        
        print("CURRENT PROGRESS:")
        print("-" * 50)
        
        total = progress["total_metrics"]
        monthly = progress["monthly_averages"]
        goal_progress = progress["goal_progress"]
        on_track = progress["on_track"]
        
        print(f"Quarter Period: {progress['quarter_period']}")
        print(f"Months Elapsed: {progress['months_elapsed']}")
        print()
        
        print("Total Metrics:")
        print(f"  • Tasks Completed: {total['total_tasks']} ({total['success_rate']:.1%} success)")
        print(f"  • Time Saved: {total['total_time_saved_hours']:.1f} hours")
        print(f"  • Cost Savings: ${total['total_cost_savings_usd']:,.0f}")
        print(f"  • Avg ROI: {total['avg_roi_score']:.1f}/100")
        print(f"  • Defects Avoided: {total['total_defects_avoided']}")
        print(f"  • Incidents: {total['total_incidents']}")
        print()
        
        print("Monthly Averages:")
        print(f"  • Hours Saved/Month: {monthly['avg_hours_saved_per_month']:.1f}h")
        print(f"  • Tasks/Month: {monthly['avg_tasks_per_month']:.1f}")
        print(f"  • Avg ROI: {monthly['avg_roi_per_month']:.1f}/100")
        print()
        
        print("Goal Progress:")
        print(f"  • Hours Saved: {goal_progress['hours_saved_progress']:.1%} of target")
        print(f"  • ROI Score: {goal_progress['roi_score_progress']:.1%} of target")
        print(f"  • Defect Rate: {'✅ COMPLIANT' if on_track['defect_rate'] else '❌ EXCEEDED'}")
        print(f"  • Incidents: {'✅ COMPLIANT' if on_track['incidents'] else '❌ EXCEEDED'}")
        print()
        
        print("Monthly Breakdown:")
        print("-" * 50)
        for month_data in progress["monthly_breakdown"]:
            print(f"{month_data['month']}:")
            print(f"  • Hours Saved: {month_data['hours_saved']:.1f}h")
            print(f"  • Tasks: {month_data['tasks']}")
            print(f"  • Avg ROI: {month_data['avg_roi']:.1f}/100")
            print(f"  • Incidents: {month_data['incidents']}")
            print()
        
        print("OVERALL STATUS:")
        print("-" * 50)
        if progress["overall_on_track"]:
            print("✅ ON TRACK - All metrics meeting targets")
            print("Action: Continue current scaling approach")
            status = "ON_TRACK"
        else:
            print("⚠️  OFF TRACK - Some metrics not meeting targets")
            print("Action: Adjust scaling strategy to meet goals")
            status = "OFF_TRACK"
        
        # Recommendations based on specific gaps
        print()
        print("RECOMMENDATIONS:")
        print("-" * 50)
        recommendations = []
        
        if not on_track["hours_saved"]:
            recommendations.append("Increase task volume or efficiency to meet 40h/month target")
        
        if not on_track["roi_score"]:
            recommendations.append("Focus on high-ROI tasks to meet 85/100 average")
        
        if not on_track["defect_rate"]:
            recommendations.append("Investigate incident causes and improve quality")
        
        if not on_track["incidents"]:
            recommendations.append("URGENT: Address production incidents immediately")
        
        if progress["overall_on_track"]:
            recommendations.append("Maintain current approach and consider scaling up")
        
        for i, rec in enumerate(recommendations, 1):
            print(f"{i}. {rec}")
        
        print()
        
        # Save status report
        status_report = {
            "report_date": datetime.now().isoformat(),
            "quarter_goal": self.quarter_goal,
            "progress": progress,
            "status": status,
            "recommendations": recommendations,
            "next_checkpoint": (datetime.now() + timedelta(weeks=1)).isoformat()
        }
        
        with open("quarter_goal_status.json", 'w') as f:
            json.dump(status_report, f, indent=2)
        
        print("✅ Status report saved to quarter_goal_status.json")
        
        print()
        print("=" * 70)
        print("QUARTER GOAL TRACKING COMPLETE")
        print(f"Status: {status}")
        print("Next: Execute recommendations and continue tracking")
        print("=" * 70)
        
        return status_report

if __name__ == "__main__":
    tracker = QuarterGoalTracker()
    tracker.generate_status_report()
