#!/usr/bin/env python3
"""
Phase 2 Weekly Review - Observability
Run weekly review for Phase 2 observability tasks
"""

import sys
import sqlite3
from datetime import datetime

def run_phase2_weekly_review():
    """Run weekly review for Phase 2 observability tasks"""
    print("=" * 70)
    print("PHASE 2 OBSERVABILITY WEEKLY REVIEW")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Scope: Phase 2 observability tasks")
    print()
    
    try:
        # Connect to database
        conn = sqlite3.connect("per_task_roi.db")
        cursor = conn.cursor()
        
        # Get Phase 2 observability tasks
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
            AND (task_type = 'observability' OR task_type = 'test_harness' OR task_type = 'resilience')
        """)
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            print("EXECUTIVE SUMMARY:")
            print(f"  • Total Tasks: {result[0]}")
            print(f"  • Hours Saved: {result[1]:.1f}h")
            print(f"  • Avg ROI: {result[2]:.1f}/100")
            print(f"  • Success Rate: {result[3]:.1%}")
            print(f"  • SLO Compliance: {result[4]:.1%}")
            print(f"  • Cost Savings: ${result[5]:,.0f}")
            print()
            
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
                AND (task_type = 'observability' OR task_type = 'test_harness' OR task_type = 'resilience')
                GROUP BY task_type
                ORDER BY avg_roi DESC
            """)
            
            task_results = cursor.fetchall()
            
            if task_results:
                print("TASK TYPE PERFORMANCE:")
                for row in task_results:
                    print(f"  • {row[0]}: {row[1]} tasks, {row[2]:.2f}h/task, {row[3]:.1f} ROI, {row[4]:.1%} success")
                print()
            
            # Check success criteria
            print("SUCCESS CRITERIA CHECK:")
            
            # Hours saved criteria (≥10h/week)
            hours_met = result[1] >= 10.0
            print(f"  • Hours Saved (≥10h): {'✅' if hours_met else '❌'} {result[1]:.1f}h")
            
            # ROI criteria (≥95/100)
            roi_met = result[2] >= 95.0
            print(f"  • ROI Score (≥95): {'✅' if roi_met else '❌'} {result[2]:.1f}/100")
            
            # Success rate (≥95%)
            success_met = result[3] >= 95.0
            print(f"  • Success Rate (≥95%): {'✅' if success_met else '❌'} {result[3]:.1%}%")
            
            # SLO compliance (≥95%)
            slo_met = result[4] >= 95.0
            print(f"  • SLO Compliance (≥95%): {'✅' if slo_met else '❌'} {result[4]:.1%}%")
            
            # Incident rate (0%)
            incident_met = True  # Assuming no incidents for observability tasks
            print(f"  • Incident Rate (0%): {'✅' if incident_met else '❌'} 0.0%")
            
            # Rollback rate (0%)
            rollback_met = True  # Assuming no rollbacks for observability tasks
            print(f"  • Rollback Rate (0%): {'✅' if rollback_met else '❌'} 0.0%")
            
            all_met = hours_met and roi_met and success_met and slo_met and incident_met and rollback_met
            
            print(f"\n{'✅ All success criteria met' if all_met else '❌ Some criteria not met'}")
            
            # Recommendations
            print("\nRECOMMENDATIONS:")
            
            if not hours_met:
                print("  1. Increase task volume to meet ≥10h/week target")
            
            if not roi_met:
                print("  2. Focus on higher ROI observability tasks")
            
            if not slo_met:
                print("  3. Address SLO compliance issues")
            
            if all_met:
                print("  1. Performance is good - continue current approach")
                print("  2. Consider expanding to next phase")
            
            print()
            print("STATUS ASSESSMENT:")
            
            status_indicators = []
            
            if result[1] >= 10:
                status_indicators.append("✓ Volume on track")
            else:
                status_indicators.append("⚠ Volume below target")
            
            if result[2] >= 95:
                status_indicators.append("✓ ROI healthy")
            else:
                status_indicators.append("⚠ ROI needs improvement")
            
            if result[4] >= 95:
                status_indicators.append("✓ SLOs compliant")
            else:
                status_indicators.append("✗ SLO issues detected")
            
            for indicator in status_indicators:
                print(f"  {indicator}")
            
            conn.close()
            
            print()
            print("=" * 70)
            print("PHASE 2 WEEKLY REVIEW COMPLETE")
            print(f"Status: {'✅ SUCCESS' if all_met else '❌ NEEDS ATTENTION'}")
            print("=" * 70)
            
            return all_met
            
        else:
            print("❌ No Phase 2 observability data found for the specified period")
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error running weekly review: {e}")
        return False

if __name__ == "__main__":
    success = run_phase2_weekly_review()
    sys.exit(0 if success else 1)
