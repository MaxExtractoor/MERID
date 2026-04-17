#!/usr/bin/env python3
"""
Weekly Review with No-Thrash Enforcement
Three critical questions for operational excellence
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.operations.cadence import operations_cadence
from swarm.ci.reliability_monitor import CIReliabilityMonitor
from utils.logger import get_logger

logger = get_logger("swarm.no_thrash_review")

def run_no_thrash_weekly_review():
    """Run weekly review with no-thrash enforcement"""
    print("=" * 70)
    print("WEEKLY REVIEW - NO THRASH ENFORCEMENT")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: Three critical questions, no topology/role changes")
    print()
    
    # Load official roadmap
    try:
        with open("official_swarm_roadmap.json", 'r') as f:
            roadmap = json.load(f)
    except:
        print("❌ Roadmap not found - run define_official_roadmap.py first")
        return
    
    # Load ROI data
    try:
        with open("per_task_roi.db", 'r') as f:
            pass  # Database exists
    except:
        print("❌ ROI database not found - run implement_roi_logging.py first")
        return
    
    # Question 1: Did we meet SLOs and safety?
    print("1️⃣  DID WE MEET SLOS AND SAFETY?")
    print("-" * 50)
    
    ci_monitor = CIReliabilityMonitor()
    ci_passed = ci_monitor.run_ci_checks("weekly_slo_check.json")
    
    try:
        with open("weekly_slo_check.json", 'r') as f:
            ci_report = json.load(f)
        
        ci_metrics = ci_report["metrics"]
        
        # Critical SLOs
        critical_slos = ["success_rate", "cascade_size", "branching_factor"]
        critical_compliance = {}
        
        for slo in critical_slos:
            if slo == "success_rate":
                critical_compliance[slo] = ci_metrics[slo] >= 0.90
            elif slo == "cascade_size":
                critical_compliance[slo] = ci_metrics[slo] <= 2.0
            elif slo == "branching_factor":
                critical_compliance[slo] = ci_metrics[slo] <= 1.2
        
        all_critical_met = all(critical_compliance.values())
        
        print(f"  • Success Rate: {ci_metrics['success_rate']:.1%} {'✅' if critical_compliance['success_rate'] else '❌'}")
        print(f"  • Cascade Size: {ci_metrics['avg_cascade_size']:.2f} {'✅' if critical_compliance['cascade_size'] else '❌'}")
        print(f"  • Branching Factor: {ci_metrics['avg_branching_factor']:.2f} {'✅' if critical_compliance['branching_factor'] else '❌'}")
        print(f"  • Overall: {'✅ ALL CRITICAL SLOS MET' if all_critical_met else '❌ SOME CRITICAL SLOS FAILED'}")
        
        slo_answer = "YES" if all_critical_met else "NO"
        
    except Exception as e:
        print(f"  • Error checking SLOs: {e}")
        slo_answer = "ERROR"
    
    print(f"  Answer: {slo_answer}")
    print()
    
    # Question 2: Did quality and ROI improve, stay flat, or regress?
    print("2️⃣  DID QUALITY AND ROI IMPROVE, STAY FLAT, OR REGRESS?")
    print("-" * 50)
    
    # Get ROI data from database
    try:
        import sqlite3
        from datetime import timedelta
        
        conn = sqlite3.connect("per_task_roi.db")
        cursor = conn.cursor()
        
        # Get last 2 weeks of data
        start_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - 
                      timedelta(weeks=2))
        
        cursor.execute("""
            SELECT 
                AVG(roi_score) as avg_roi_score,
                AVG(quality_improvement) as avg_quality_improvement,
                COUNT(*) as task_count,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM per_task_roi
            WHERE date >= ?
            GROUP BY date
            ORDER BY date DESC
            LIMIT 2
        """, (start_date.isoformat(),))
        
        results = cursor.fetchall()
        conn.close()
        
        if len(results) >= 2:
            recent_avg_roi = results[0][0]
            recent_avg_quality = results[0][1]
            recent_success_rate = results[0][3]
            
            older_avg_roi = results[1][0]
            older_avg_quality = results[1][1]
            older_success_rate = results[1][3]
            
            roi_trend = recent_avg_roi - older_avg_roi
            quality_trend = recent_avg_quality - older_avg_quality
            
            print(f"  • ROI Score: {older_avg_roi:.1f} → {recent_avg_roi:.1f} ({roi_trend:+.1f})")
            print(f"  • Quality: {older_avg_quality:+.2f} → {recent_avg_quality:+.2f} ({quality_trend:+.2f})")
            print(f"  • Success Rate: {older_success_rate:.1%} → {recent_success_rate:.1%}")
            
            # Determine trend
            if roi_trend > 5:
                roi_status = "IMPROVING"
            elif roi_trend < -5:
                roi_status = "REGRESSING"
            else:
                roi_status = "STABLE"
            
            if quality_trend > 0.1:
                quality_status = "IMPROVING"
            elif quality_trend < -0.1:
                quality_status = "REGRESSING"
            else:
                quality_status = "STABLE"
            
            print(f"  • ROI Trend: {roi_status}")
            print(f"  • Quality Trend: {quality_status}")
            
            # Overall quality/ROI assessment
            if roi_status == "IMPROVING" and quality_status == "IMPROVING":
                quality_roi_answer = "IMPROVING"
            elif roi_status == "REGRESSING" or quality_status == "REGRESSING":
                quality_roi_answer = "REGRESSING"
            else:
                quality_roi_answer = "STABLE"
                
        else:
            print("  • Not enough data for trend analysis")
            quality_roi_answer = "INSUFFICIENT_DATA"
            
    except Exception as e:
        print(f"  • Error analyzing ROI/quality: {e}")
        quality_roi_answer = "ERROR"
    
    print(f"  Answer: {quality_roi_answer}")
    print()
    
    # Question 3: Did any experiment outperform current production behavior?
    print("3️⃣  DID ANY EXPERIMENT OUTPERFORM CURRENT PRODUCTION BEHAVIOR?")
    print("-" * 50)
    
    # Check for recent experiments
    try:
        with open("single_topology_experiment_results.json", 'r') as f:
            experiment = json.load(f)
        
        experiment_status = experiment.get("recommendation", "NO_DATA")
        clearly_better = experiment.get("comparison", {}).get("clearly_better", False)
        
        print(f"  • Recent Experiment: {experiment_status}")
        print(f"  • Clear Improvement: {'✅ YES' if clearly_better else '❌ NO'}")
        
        if clearly_better and "RECOMMENDED" in experiment_status:
            experiment_answer = "YES"
        else:
            experiment_answer = "NO"
            
    except:
        print("  • No recent experiments found")
        experiment_answer = "NO_DATA"
    
    print(f"  Answer: {experiment_answer}")
    print()
    
    # Overall decision based on roadmap enforcement rules
    print("OVERALL DECISION (BASED ON ROADMAP ENFORCEMENT):")
    print("-" * 50)
    
    decisions = {
        "slos_met": slo_answer == "YES",
        "quality_roi_improving": quality_roi_answer == "IMPROVING",
        "experiments_better": experiment_answer == "YES"
    }
    
    print("Enforcement Rules:")
    print("• No Thrash: No topology/role changes unless clearly better")
    print("• Focus: Scale existing lanes unless quality/ROI regress")
    print("• Experiments: One at a time, kill quickly if not better")
    print()
    
    if all(decisions.values()):
        print("✅ ALL CRITICAL QUESTIONS POSITIVE")
        print("  • Status: EXCELLENT - Continue scaling proven patterns")
        print("  • Action: Scale primary use cases, maintain current topology")
        print("  • Decision: SCALE_EXISTING_LANES")
        overall_decision = "SCALE_EXISTING_LANES"
        
    elif not decisions["slos_met"]:
        print("❌ SLO COMPLIANCE FAILED")
        print("  • Status: CRITICAL - Fix SLOs immediately")
        print("  • Action: Halt scaling, run hardening sprint")
        print("  • Decision: HALT_SCALING_FIX_SLOS")
        overall_decision = "HALT_SCALING_FIX_SLOS"
        
    elif decisions["quality_roi_improving"]:
        print("✅ QUALITY/ROI IMPROVING")
        print("  • Status: GOOD - Continue current approach")
        print("  • Action: Scale existing lanes, monitor closely")
        print("  • Decision: CONTINUE_CURRENT_APPROACH")
        overall_decision = "CONTINUE_CURRENT_APPROACH"
        
    elif decisions["experiments_better"]:
        print("✅ EXPERIMENT CLEARLY BETTER")
        print("  • Status: OPPORTUNITY - Consider controlled rollout")
        print("  • Action: Plan staged rollout with rollback capability")
        print("  • Decision: PLAN_CONTROLLED_ROLLOUT")
        overall_decision = "PLAN_CONTROLLED_ROLLOUT"
        
    else:
        print("⚠️  MIXED RESULTS")
        print("  • Status: CAUTION - Optimize before scaling")
        print("  • Action: Address regressions, focus on proven use cases")
        print("  • Decision: OPTIMIZE_BEFORE_SCALING")
        overall_decision = "OPTIMIZE_BEFORE_SCALING"
    
    print(f"  Overall Decision: {overall_decision}")
    print()
    
    # Action items based on decision and roadmap
    print("ACTION ITEMS (BASED ON ROADMAP):")
    print("-" * 50)
    
    action_items = []
    
    if overall_decision == "SCALE_EXISTING_LANES":
        action_items.extend([
            "Scale test expansion to batch 3 (optimize targets first)",
            "Expand config refactor to medium-risk configs",
            "Start documentation improvements pilot",
            "Maintain current topology (no changes needed)"
        ])
    elif overall_decision == "CONTINUE_CURRENT_APPROACH":
        action_items.extend([
            "Continue scaling test expansion with current targets",
            "Expand config refactor scope cautiously",
            "Monitor quality/ROI trends closely",
            "Keep current topology (performing well)"
        ])
    elif overall_decision == "PLAN_CONTROLLED_ROLLOUT":
        action_items.extend([
            "Plan staged rollout of successful experiment",
            "Define rollback criteria and monitoring",
            "Start with low-risk tasks only",
            "Prepare to revert if issues arise"
        ])
    elif overall_decision == "OPTIMIZE_BEFORE_SCALING":
        action_items.extend([
            "Address quality/ROI regressions immediately",
            "Optimize prompts/roles for weak use cases",
            "Refine scaling targets based on data",
            "Pause expansion until metrics improve"
        ])
    else:  # HALT_SCALING_FIX_SLOS
        action_items.extend([
            "URGENT: Fix critical SLO compliance issues",
            "Run hardening sprint to address failures",
            "Investigate root causes of SLO breaches",
            "Pause all scaling until fixed"
        ])
    
    for i, action in enumerate(action_items, 1):
        print(f"  {i}. {action}")
    
    print()
    
    # Save weekly review
    review_data = {
        "review_date": datetime.now().isoformat(),
        "review_type": "no_thrash_enforcement",
        "questions": decisions,
        "overall_decision": overall_decision,
        "action_items": action_items,
        "roadmap_locked": True,
        "slo_metrics": ci_metrics if 'ci_metrics' in locals() else {},
        "quality_roi_trends": {
            "roi_status": quality_roi_answer,
            "quality_status": quality_roi_answer if 'quality_status' in locals() else "UNKNOWN"
        },
        "experiment_status": experiment_answer
    }
    
    with open("weekly_no_thrash_review.json", 'w') as f:
        json.dump(review_data, f, indent=2)
    
    print("✅ Weekly review saved to weekly_no_thrash_review.json")
    
    # Add changelog entry
    operations_cadence.add_changelog_entry(
        "weekly_review",
        f"No-thash review - {overall_decision}",
        "improved" if overall_decision in ["SCALE_EXISTING_LANES", "CONTINUE_CURRENT_APPROACH"] else "mixed",
        {"week": "previous"},
        {"week": "current", "decision": overall_decision}
    )
    
    print("✅ Changelog entry added")
    
    print()
    print("=" * 70)
    print("WEEKLY REVIEW COMPLETE - NO THRASH ENFORCEMENT")
    print(f"Decision: {overall_decision}")
    print("Next: Execute action items and prepare for next week")
    print("=" * 70)
    
    return review_data

if __name__ == "__main__":
    run_no_thrash_weekly_review()
