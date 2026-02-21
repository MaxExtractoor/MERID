#!/usr/bin/env python3
"""
Simple Weekly Review - Basic ASCII
Run core ROI queries and emit basic markdown summary
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

logger = get_logger("swarm.weekly_review_basic")

def run_weekly_review_basic(weeks_back: int = 1, output_file: str = "weekly_review_basic.md"):
    """Run weekly review and save basic markdown report"""
    print("=" * 70)
    print("WEEKLY ROI REVIEW (BASIC)")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Period: {weeks_back} week(s) back")
    print()
    
    try:
        # Connect to database
        conn = sqlite3.connect("per_task_roi.db")
        cursor = conn.cursor()
        
        # Get basic metrics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(human_time_saved_hours) as total_hours_saved,
                AVG(roi_score) as avg_roi_score,
                COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate,
                COUNT(*) FILTER (WHERE slo_compliance = 'green') * 100.0 / COUNT(*) as slo_compliance_rate,
                SUM(cost_savings_usd) as total_cost_savings
            FROM per_task_roi_log
            WHERE date >= date('now', '-7 days')
        """)
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            # Generate basic report
            report = []
            report.append("# Weekly ROI Review Report")
            report.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d')}")
            report.append(f"**Period:** {weeks_back} week(s) back")
            report.append("")
            report.append("## Executive Summary")
            report.append(f"- **Total Tasks:** {result[0]}")
            report.append(f"- **Hours Saved:** {result[1]:.1f}h")
            report.append(f"- **Avg ROI:** {result[2]:.1f}/100")
            report.append(f"- **Success Rate:** {result[3]:.1%}")
            report.append(f"- **SLO Compliance:** {result[4]:.1%}")
            report.append(f"- **Cost Savings:** ${result[5]:,.0f}")
            report.append("")
            
            # Get task type performance
            cursor.execute("""
                SELECT 
                    task_type,
                    COUNT(*) as task_count,
                    AVG(human_time_saved_hours) as avg_hours_saved,
                    AVG(roi_score) as avg_roi,
                    COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate
                FROM per_task_roi_log
                WHERE date >= date('now', '-7 days')
                GROUP BY task_type
                ORDER BY avg_roi DESC
            """)
            
            task_results = cursor.fetchall()
            
            if task_results:
                report.append("## Task Type Performance")
                report.append("| Task Type | Count | Hours/Task | ROI | Success Rate |")
                report.append("|-----------|-------|------------|-----|-------------|")
                
                for row in task_results:
                    report.append(f"| {row[0]} | {row[1]} | {row[2]:.2f} | {row[3]:.1f} | {row[4]:.1%} |")
                report.append("")
            
            # Basic recommendations
            report.append("## Recommendations")
            
            recommendations = []
            
            if result[1] < 10:
                recommendations.append("Increase task volume to meet 40h/month target")
            
            if result[2] < 85:
                recommendations.append("Focus on high-ROI task types to improve average ROI")
            
            if result[4] < 90:
                recommendations.append("Address SLO compliance issues")
            
            if result[0] > 0 and result[6] == 0:
                recommendations.append("Performance is good - continue current approach")
            
            for i, rec in enumerate(recommendations, 1):
                report.append(f"{i}. {rec}")
            
            report.append("")
            
            # Status assessment
            report.append("## Status Assessment")
            
            status_indicators = []
            
            if result[1] >= 10:
                status_indicators.append("✓ Volume on track")
            else:
                status_indicators.append("⚠ Volume below target")
            
            if result[2] >= 85:
                status_indicators.append("✓ ROI healthy")
            else:
                status_indicators.append("⚠ ROI needs improvement")
            
            if result[4] >= 90:
                status_indicators.append("✓ SLOs compliant")
            else:
                status_indicators.append("✗ SLO issues detected")
            
            for indicator in status_indicators:
                report.append(f"- {indicator}")
            
            report.append("")
            
            # Save report
            with open(output_file, 'w') as f:
                f.write("\n".join(report))
            
            print(f"✅ Weekly ROI review saved to {output_file}")
            
            # Print key metrics
            print("\nKEY METRICS:")
            print(f"  • Tasks: {result[0]}")
            print(f"  • Hours Saved: {result[1]:.1f}h")
            print(f"  • Avg ROI: {result[2]:.1f}/100")
            print(f"  • Success Rate: {result[3]:.1%}")
            print(f"  • SLO Compliance: {result[4]:.1%}")
            
            print("\nTOP RECOMMENDATIONS:")
            for i, rec in enumerate(recommendations[:3], 1):
                print(f"  {i}. {rec}")
            
            conn.close()
            
            print()
            print("=" * 70)
            print("WEEKLY ROI REVIEW COMPLETE")
            print(f"Report: {output_file}")
            print("=" * 70)
            
            return True
        else:
            print("❌ No data found for the specified period")
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error running weekly review: {e}")
        return False

if __name__ == "__main__":
    run_weekly_review_basic()
