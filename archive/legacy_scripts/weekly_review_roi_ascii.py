#!/usr/bin/env python3
"""
Simple Weekly Review - ASCII Only
Run core ROI queries and emit ASCII-only markdown summary
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.weekly_review_roi_ascii")

class WeeklyReviewROI_ASCII:
    """Weekly review ROI analysis and reporting - ASCII only"""
    
    def __init__(self, db_path: str = "per_task_roi.db"):
        self.db_path = db_path
        self._ensure_database()
    
    def _ensure_database(self):
        """Ensure database exists"""
        if not Path(self.db_path).exists():
            raise FileNotFoundError(f"ROI database not found: {self.db_path}")
    
    def run_weekly_summary(self, weeks_back: int = 1) -> Dict[str, Any]:
        """Generate weekly summary for review"""
        logger.info(f"Generating weekly summary for {weeks_back} week(s) back")
        
        # Calculate date range
        start_date = (datetime.now() - timedelta(weeks=weeks_back)).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Weekly Overview
        weekly_overview = self._get_weekly_overview(cursor, start_date)
        
        # 2. Task Type Performance
        task_type_performance = self._get_task_type_performance(cursor, start_date)
        
        # 3. Risk Level Analysis
        risk_analysis = self._get_risk_analysis(cursor, start_date)
        
        # 4. Quality and SLO Analysis
        quality_analysis = self._get_quality_analysis(cursor, start_date)
        
        # 5. Cost and ROI Analysis
        cost_analysis = self._get_cost_analysis(cursor, start_date)
        
        # 6. Incident and Safety Analysis
        incident_analysis = self._get_incident_analysis(cursor, start_date)
        
        conn.close()
        
        # Build summary
        summary = {
            "review_date": datetime.now().isoformat(),
            "period": f"{weeks_back} week(s) back",
            "date_range": {
                "start": start_date,
                "end": datetime.now().isoformat()
            },
            "weekly_overview": weekly_overview,
            "task_type_performance": task_type_performance,
            "risk_analysis": risk_analysis,
            "quality_analysis": quality_analysis,
            "cost_analysis": cost_analysis,
            "incident_analysis": incident_analysis,
            "recommendations": self._generate_recommendations(
                weekly_overview, task_type_performance, risk_analysis,
                quality_analysis, cost_analysis, incident_analysis
            )
        }
        
        return summary
    
    def _get_weekly_overview(self, cursor: sqlite3.Cursor, start_date: str) -> Dict[str, Any]:
        """Get weekly overview metrics"""
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(human_time_saved_hours) as total_hours_saved,
                AVG(roi_score) as avg_roi_score,
                AVG(quality_improvement) as avg_quality_improvement,
                SUM(cost_savings_usd) as total_cost_savings,
                COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'green') * 100.0 / COUNT(*) as slo_compliance_rate,
                AVG(human_time_saved_hours) as avg_hours_per_task,
                SUM(defects_avoided) as total_defects_avoided
            FROM per_task_roi_log
            WHERE date >= ?
        """, (start_date,))
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            return {
                "total_tasks": result[0],
                "total_hours_saved": result[1] or 0.0,
                "avg_roi_score": result[2] or 0.0,
                "avg_quality_improvement": result[3] or 0.0,
                "total_cost_savings": result[4] or 0.0,
                "success_rate": result[5] or 0.0,
                "slo_compliance_rate": result[6] or 0.0,
                "avg_hours_per_task": result[7] or 0.0,
                "total_defects_avoided": result[8] or 0
            }
        else:
            return {
                "total_tasks": 0,
                "total_hours_saved": 0.0,
                "avg_roi_score": 0.0,
                "avg_quality_improvement": 0.0,
                "total_cost_savings": 0.0,
                "success_rate": 0.0,
                "slo_compliance_rate": 0.0,
                "avg_hours_per_task": 0.0,
                "total_defects_avoided": 0
            }
    
    def _get_task_type_performance(self, cursor: sqlite3.Cursor, start_date: str) -> List[Dict[str, Any]]:
        """Get performance by task type"""
        cursor.execute("""
            SELECT 
                task_type,
                COUNT(*) as task_count,
                AVG(human_time_saved_hours) as avg_hours_saved,
                AVG(roi_score) as avg_roi,
                AVG(quality_improvement) as avg_quality,
                SUM(cost_savings_usd) as total_savings,
                COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate,
                SUM(defects_avoided) as total_defects_avoided
            FROM per_task_roi_log
            WHERE date >= ?
            GROUP BY task_type
            ORDER BY avg_roi DESC
        """, (start_date,))
        
        results = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        
        return [dict(zip(columns, row)) for row in results]
    
    def _get_risk_analysis(self, cursor: sqlite3.Cursor, start_date: str) -> List[Dict[str, Any]]:
        """Get risk level analysis"""
        cursor.execute("""
            SELECT 
                risk_level,
                COUNT(*) as task_count,
                AVG(human_time_saved_hours) as avg_hours_saved,
                SUM(incidents) as total_incidents,
                SUM(near_misses) as total_near_misses,
                COUNT(*) FILTER (WHERE rollback_required = true) * 100.0 / COUNT(*) as rollback_rate,
                AVG(roi_score) as avg_roi,
                COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate
            FROM per_task_roi_log
            WHERE date >= ?
            GROUP BY risk_level
            ORDER BY risk_level
        """, (start_date,))
        
        results = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        
        return [dict(zip(columns, row)) for row in results]
    
    def _get_quality_analysis(self, cursor: sqlite3.Cursor, start_date: str) -> Dict[str, Any]:
        """Get quality and SLO analysis"""
        cursor.execute("""
            SELECT 
                AVG(quality_improvement) as avg_quality,
                COUNT(*) FILTER (WHERE quality_improvement > 0.5) * 100.0 / COUNT(*) as high_quality_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'green') * 100.0 / COUNT(*) as slo_green_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'yellow') * 100.0 / COUNT(*) as slo_yellow_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'red') * 100.0 / COUNT(*) as slo_red_rate,
                AVG(human_review_friction) as avg_review_friction,
                SUM(defects_avoided) as total_defects_avoided,
                COUNT(*) FILTER (WHERE defects_avoided > 0) * 100.0 / COUNT(*) as defect_detection_rate
            FROM per_task_roi_log
            WHERE date >= ?
        """, (start_date,))
        
        result = cursor.fetchone()
        
        if result and result[0] is not None:
            return {
                "avg_quality_improvement": result[0] or 0.0,
                "high_quality_rate": result[1] or 0.0,
                "slo_green_rate": result[2] or 0.0,
                "slo_yellow_rate": result[3] or 0.0,
                "slo_red_rate": result[4] or 0.0,
                "avg_review_friction": result[5] or 0.0,
                "total_defects_avoided": result[6] or 0,
                "defect_detection_rate": result[7] or 0.0
            }
        else:
            return {
                "avg_quality_improvement": 0.0,
                "high_quality_rate": 0.0,
                "slo_green_rate": 0.0,
                "slo_yellow_rate": 0.0,
                "slo_red_rate": 0.0,
                "avg_review_friction": 0.0,
                "total_defects_avoided": 0,
                "defect_detection_rate": 0.0
            }
    
    def _get_cost_analysis(self, cursor: sqlite3.Cursor, start_date: str) -> Dict[str, Any]:
        """Get cost and ROI analysis"""
        cursor.execute("""
            SELECT 
                SUM(cost_savings_usd) as total_savings,
                AVG(roi_score) as avg_roi,
                COUNT(*) FILTER (WHERE roi_score >= 90) * 100.0 / COUNT(*) as high_roi_rate,
                COUNT(*) FILTER (WHERE roi_score >= 75) * 100.0 / COUNT(*) as acceptable_roi_rate,
                AVG(human_time_saved_hours) as avg_hours_saved,
                SUM(human_time_saved_hours) as total_hours_saved,
                COUNT(*) FILTER (WHERE business_value = 'high') * 100.0 / COUNT(*) as high_business_value_rate
            FROM per_task_roi_log
            WHERE date >= ?
        """, (start_date,))
        
        result = cursor.fetchone()
        
        if result and result[0] is not None:
            return {
                "total_cost_savings": result[0] or 0.0,
                "avg_roi_score": result[1] or 0.0,
                "high_roi_rate": result[2] or 0.0,
                "acceptable_roi_rate": result[3] or 0.0,
                "avg_hours_saved_per_task": result[4] or 0.0,
                "total_hours_saved": result[5] or 0.0,
                "high_business_value_rate": result[6] or 0.0
            }
        else:
            return {
                "total_cost_savings": 0.0,
                "avg_roi_score": 0.0,
                "high_roi_rate": 0.0,
                "acceptable_roi_rate": 0.0,
                "avg_hours_saved_per_task": 0.0,
                "total_hours_saved": 0.0,
                "high_business_value_rate": 0.0
            }
    
    def _get_incident_analysis(self, cursor: sqlite3.Cursor, start_date: str) -> Dict[str, Any]:
        """Get incident and safety analysis"""
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(incidents) as total_incidents,
                SUM(near_misses) as total_near_misses,
                COUNT(*) FILTER (WHERE rollback_required = true) as rollback_count,
                COUNT(*) FILTER (WHERE rollback_required = true) * 100.0 / COUNT(*) as rollback_rate,
                AVG(rollback_time_hours) as avg_rollback_time,
                COUNT(*) FILTER (WHERE incidents = 0 AND near_misses = 0) * 100.0 / COUNT(*) as clean_execution_rate
            FROM per_task_roi_log
            WHERE date >= ?
        """, (start_date,))
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            return {
                "total_tasks": result[0],
                "total_incidents": result[1] or 0,
                "total_near_misses": result[2] or 0,
                "rollback_count": result[3] or 0,
                "rollback_rate": result[4] or 0.0,
                "avg_rollback_time": result[5] or 0.0,
                "clean_execution_rate": result[6] or 0.0
            }
        else:
            return {
                "total_tasks": 0,
                "total_incidents": 0,
                "total_near_misses": 0,
                "rollback_count": 0,
                "rollback_rate": 0.0,
                "avg_rollback_time": 0.0,
                "clean_execution_rate": 0.0
            }
    
    def _generate_recommendations(self, *analyses) -> List[str]:
        """Generate recommendations based on analyses"""
        recommendations = []
        
        weekly_overview = analyses[0]
        task_type_performance = analyses[1]
        risk_analysis = analyses[2]
        quality_analysis = analyses[3]
        cost_analysis = analyses[4]
        incident_analysis = analyses[5]
        
        # Volume recommendations
        if weekly_overview["total_hours_saved"] < 10:
            recommendations.append("Increase task volume to meet 40h/month target")
        
        # ROI recommendations
        if cost_analysis["avg_roi_score"] < 85:
            recommendations.append("Focus on high-ROI task types to improve average ROI")
        
        # Quality recommendations
        if quality_analysis["slo_green_rate"] < 90:
            recommendations.append("Address SLO compliance issues - investigate misalignment")
        
        # Risk recommendations
        high_risk_tasks = [r for r in risk_analysis if r["risk_level"] == "high"]
        if high_risk_tasks and high_risk_tasks[0]["rollback_rate"] > 0:
            recommendations.append("Reduce high-risk task volume or improve safety measures")
        
        # Incident recommendations
        if incident_analysis["total_incidents"] > 0:
            recommendations.append("URGENT: Address incidents - pause scaling until resolved")
        
        # Task type recommendations
        if task_type_performance:
            best_type = max(task_type_performance, key=lambda x: x["avg_roi"])
            worst_type = min(task_type_performance, key=lambda x: x["avg_roi"])
            
            if best_type["avg_roi"] > 90 and worst_type["avg_roi"] < 75:
                recommendations.append(f"Scale {best_type['task_type']} tasks, reduce {worst_type['task_type']} tasks")
        
        # Quality recommendations
        if quality_analysis["avg_review_friction"] > 0.3:
            recommendations.append("Reduce human review friction through better automation")
        
        if not recommendations:
            recommendations.append("Performance is good - continue current approach")
        
        return recommendations
    
    def generate_ascii_report(self, summary: Dict[str, Any]) -> str:
        """Generate ASCII-only markdown report from summary"""
        report = []
        
        # Header
        report.append("# Weekly ROI Review Report")
        report.append(f"**Date:** {summary['review_date'][:10]}")
        report.append(f"**Period:** {summary['period']}")
        report.append(f"**Date Range:** {summary['date_range']['start'][:10]} to {summary['date_range']['end'][:10]}")
        report.append("")
        
        # Executive Summary
        overview = summary["weekly_overview"]
        report.append("## Executive Summary")
        report.append(f"- **Total Tasks:** {overview['total_tasks']}")
        report.append(f"- **Hours Saved:** {overview['total_hours_saved']:.1f}h")
        report.append(f"- **Cost Savings:** ${overview['total_cost_savings']:,.0f}")
        report.append(f"- **Avg ROI:** {overview['avg_roi_score']:.1f}/100")
        report.append(f"- **Success Rate:** {overview['success_rate']:.1%}")
        report.append(f"- **SLO Compliance:** {overview['slo_compliance_rate']:.1%}")
        report.append("")
        
        # Task Type Performance
        report.append("## Task Type Performance")
        report.append("| Task Type | Count | Hours/Task | ROI | Success Rate |")
        report.append("|-----------|-------|------------|-----|-------------|")
        
        for perf in summary["task_type_performance"]:
            report.append(f"| {perf['task_type']} | {perf['task_count']} | {perf['avg_hours_saved']:.2f} | {perf['avg_roi']:.1f} | {perf['success_rate']:.1%} |")
        report.append("")
        
        # Risk Analysis
        report.append("## Risk Analysis")
        report.append("| Risk Level | Count | Hours/Task | Incidents | Rollback Rate |")
        report.append("|-----------|-------|------------|----------|--------------|")
        
        for risk in summary["risk_analysis"]:
            report.append(f"| {risk['risk_level']} | {risk['task_count']} | {risk['avg_hours_saved']:.2f} | {risk['total_incidents']} | {risk['rollback_rate']:.1%} |")
        report.append("")
        
        # Quality & SLO Analysis
        quality = summary["quality_analysis"]
        report.append("## Quality & SLO Analysis")
        report.append(f"- **Avg Quality Improvement:** {quality['avg_quality_improvement']:.3f}")
        report.append(f"- **High Quality Rate (>0.5):** {quality['high_quality_rate']:.1%}")
        report.append(f"- **SLO Green Rate:** {quality['slo_green_rate']:.1%}")
        report.append(f"- **SLO Yellow Rate:** {quality['slo_yellow_rate']:.1%}")
        report.append(f"- **SLO Red Rate:** {quality['slo_red_rate']:.1%}")
        report.append(f"- **Avg Review Friction:** {quality['avg_review_friction']:.3f}")
        report.append(f"- **Total Defects Avoided:** {quality['total_defects_avoided']}")
        report.append(f"- **Defect Detection Rate:** {quality['defect_detection_rate']:.1%}")
        report.append("")
        
        # Cost Analysis
        cost = summary["cost_analysis"]
        report.append("## Cost & ROI Analysis")
        report.append(f"- **Total Cost Savings:** ${cost['total_cost_savings']:,.0f}")
        report.append(f"- **Avg ROI Score:** {cost['avg_roi_score']:.1f}/100")
        report.append(f"- **High ROI Rate (>=90):** {cost['high_roi_rate']:.1%}")
        report.append(f"- **Acceptable ROI Rate (>=75):** {cost['acceptable_roi_rate']:.1%}")
        report.append(f"- **Avg Hours/Task:** {cost['avg_hours_saved_per_task']:.2f}")
        report.append(f"- **High Business Value Rate:** {cost['high_business_value_rate']:.1%}")
        report.append("")
        
        # Incident Analysis
        incident = summary["incident_analysis"]
        report.append("## Incident & Safety Analysis")
        report.append(f"- **Total Incidents:** {incident['total_incidents']}")
        report.append(f"- **Total Near Misses:** {incident['total_near_misses']}")
        report.append(f"- **Rollback Count:** {incident['rollback_count']}")
        report.append(f"- **Rollback Rate:** {incident['rollback_rate']:.1%}")
        report.append(f"- **Clean Execution Rate:** {incident['clean_execution_rate']:.1%}")
        report.append("")
        
        # Recommendations
        report.append("## Recommendations")
        for i, rec in enumerate(summary["recommendations"], 1):
            report.append(f"{i}. {rec}")
        report.append("")
        
        # Status Assessment
        report.append("## Status Assessment")
        
        # Determine overall status
        status_indicators = []
        
        if overview["total_hours_saved"] >= 10:
            status_indicators.append("✓ Volume on track")
        else:
            status_indicators.append("⚠ Volume below target")
        
        if cost["avg_roi_score"] >= 85:
            status_indicators.append("✓ ROI healthy")
        else:
            status_indicators.append("⚠ ROI needs improvement")
        
        if quality["slo_green_rate"] >= 90:
            status_indicators.append("✓ SLOs compliant")
        else:
            status_indicators.append("✗ SLO issues detected")
        
        if incident["total_incidents"] == 0:
            status_indicators.append("✓ No incidents")
        else:
            status_indicators.append("✗ Incidents detected")
        
        for indicator in status_indicators:
            report.append(f"- {indicator}")
        
        report.append("")
        
        return "\n".join(report)

def run_weekly_review_ascii(weeks_back: int = 1, output_file: str = "weekly_roi_review_ascii.md"):
    """Run weekly review and save ASCII markdown report"""
    print("=" * 70)
    print("WEEKLY ROI REVIEW (ASCII)")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Period: {weeks_back} week(s) back")
    print()
    
    try:
        # Generate summary
        reviewer = WeeklyReviewROI_ASCII()
        summary = reviewer.run_weekly_summary(weeks_back)
        
        # Generate markdown report
        markdown = reviewer.generate_ascii_report(summary)
        
        # Save report
        with open(output_file, 'w') as f:
            f.write(markdown)
        
        print(f"✅ Weekly ROI review saved to {output_file}")
        
        # Print key metrics
        overview = summary["weekly_overview"]
        print("\nKEY METRICS:")
        print(f"  • Tasks: {overview['total_tasks']}")
        print(f"  • Hours Saved: {overview['total_hours_saved']:.1f}h")
        print(f"  • Avg ROI: {overview['avg_roi_score']:.1f}/100")
        print(f"  • Success Rate: {overview['success_rate']:.1%}")
        print(f"  • SLO Compliance: {overview['slo_compliance_rate']:.1%}")
        
        print("\nTOP RECOMMENDATIONS:")
        for i, rec in enumerate(summary["recommendations"][:3], 1):
            print(f"  {i}. {rec}")
        
        print()
        print("=" * 70)
        print("WEEKLY ROI REVIEW COMPLETE")
        print(f"Report: {output_file}")
        print("=" * 70)
        
        return summary
        
    except Exception as e:
        print(f"❌ Error running weekly review: {e}")
        return None

if __name__ == "__main__":
    run_weekly_review_ascii()
