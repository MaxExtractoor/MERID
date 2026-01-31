#!/usr/bin/env python3
"""
Week 4: Weekly Loop - Light but Strict
Three critical questions for operational excellence
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.operations.cadence import operations_cadence
from swarm.ci.reliability_monitor import CIReliabilityMonitor
from swarm.roi.tracker import roi_tracker
from utils.logger import get_logger

logger = get_logger("swarm.weekly_loop")

def run_weekly_strict_review():
    """Run light but strict weekly review"""
    print("=" * 60)
    print("WEEK 4: WEEKLY LOOP - LIGHT BUT STRICT")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: Three critical questions only")
    print()
    
    # Question 1: Did we meet SLOs?
    print("1️⃣  DID WE MEET SLOS?")
    print("-" * 40)
    
    ci_monitor = CIReliabilityMonitor()
    ci_passed = ci_monitor.run_ci_checks("week4_slo_check.json")
    
    try:
        with open("week4_slo_check.json", 'r') as f:
            ci_report = json.load(f)
        
        ci_metrics = ci_report["metrics"]
        
        # Check SLO compliance
        slo_compliance = operations_cadence.slos.check_compliance({
            "success_rate": ci_metrics["success_rate"],
            "avg_cascade_size": ci_metrics["avg_cascade_size"],
            "avg_branching_factor": ci_metrics["avg_branching_factor"],
            "quality_score": 0.0,  # Will check separately
            "avg_misalignment": ci_metrics["avg_misalignment"],
            "avg_retry_index": ci_metrics["avg_retry_index"]
        })
        
        slo_score = operations_cadence.slos.calculate_slo_score({
            "success_rate": ci_metrics["success_rate"],
            "avg_cascade_size": ci_metrics["avg_cascade_size"],
            "avg_branching_factor": ci_metrics["avg_branching_factor"],
            "quality_score": 0.0,
            "avg_misalignment": ci_metrics["avg_misalignment"],
            "avg_retry_index": ci_metrics["avg_retry_index"]
        })
        
        # Critical SLOs
        critical_slos = ["success_rate", "cascade_size", "branching_factor"]
        critical_compliance = {slo: slo_compliance[slo] for slo in critical_slos}
        
        all_critical_met = all(critical_compliance.values())
        
        print(f"  • Success Rate: {ci_metrics['success_rate']:.1%} {'✅' if slo_compliance['success_rate'] else '❌'}")
        print(f"  • Cascade Size: {ci_metrics['avg_cascade_size']:.2f} {'✅' if slo_compliance['cascade_size'] else '❌'}")
        print(f"  • Branching Factor: {ci_metrics['avg_branching_factor']:.2f} {'✅' if slo_compliance['branching_factor'] else '❌'}")
        print(f"  • Overall SLO Score: {slo_score:.1f}/100")
        print(f"  • Critical SLOs: {'✅ ALL MET' if all_critical_met else '❌ SOME FAILED'}")
        
        slo_answer = "YES" if all_critical_met else "NO"
        
    except Exception as e:
        print(f"  • Error checking SLOs: {e}")
        slo_answer = "ERROR"
    
    print(f"  Answer: {slo_answer}")
    print()
    
    # Question 2: Did we improve or regress quality/ROI?
    print("2️⃣  DID WE IMPROVE OR REGRESS QUALITY/ROI?")
    print("-" * 40)
    
    # Load previous week data for comparison
    try:
        with open("week3_review_log.json", 'r') as f:
            week3_data = json.load(f)
        
        week3_roi = week3_data.get("roi_metrics", {}).get("avg_roi_score", 0)
        week3_quality = week3_data.get("quality_metrics", {}).get("quality_score", 0) / 100
        
    except:
        week3_roi = 0
        week3_quality = 0
    
    # Get current metrics
    roi_impact = roi_tracker.get_productivity_impact()
    
    if "error" not in roi_impact:
        current_roi = roi_impact.get("avg_roi_score", 0)
        current_quality = roi_impact.get("avg_quality_improvement", 0)
        
        roi_trend = current_roi - week3_roi
        quality_trend = current_quality - week3_quality
        
        print(f"  • ROI Score: {week3_roi:.1f} → {current_roi:.1f} ({roi_trend:+.1f})")
        print(f"  • Quality: {week3_quality:+.2f} → {current_quality:+.2f} ({quality_trend:+.2f})")
        
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
        
        quality_answer = "IMPROVING" if roi_status == "IMPROVING" and quality_status == "IMPROVING" else "NEUTRAL"
        if roi_status == "REGRESSING" or quality_status == "REGRESSING":
            quality_answer = "REGRESSING"
        
    else:
        print("  • Building baseline...")
        quality_answer = "BASELINE"
    
    print(f"  Answer: {quality_answer}")
    print()
    
    # Question 3: Did any experiment show enough benefit to consider promotion?
    print("3️⃣  DID ANY EXPERIMENT SHOW ENOUGH BENEFIT TO CONSIDER PROMOTION?")
    print("-" * 40)
    
    # Check recent experiments
    try:
        with open("feature_flag_topology_experiment.json", 'r') as f:
            topology_exp = json.load(f)
        
        topology_recommendation = topology_exp.get("recommendation", "NO_DATA")
        
        print(f"  • Topology Experiment: {topology_recommendation}")
        
        if "RECOMMENDED" in topology_recommendation:
            experiment_answer = "YES"
        else:
            experiment_answer = "NO"
            
    except:
        print("  • No recent topology experiments")
        experiment_answer = "NO_DATA"
    
    # Check batch 2 scaling
    try:
        with open("test_expansion_batch_2_results.json", 'r') as f:
            batch2_data = json.load(f)
        
        batch2_decision = batch2_data.get("decision", {}).get("continue_scaling", False)
        
        print(f"  • Batch 2 Scaling: {'CONTINUE' if batch2_decision else 'STOP'}")
        
        if batch2_decision:
            experiment_answer = "YES"
        
    except:
        print("  • No batch 2 data")
    
    print(f"  Answer: {experiment_answer}")
    print()
    
    # Overall decision
    print("OVERALL DECISION:")
    print("-" * 40)
    
    decisions = {
        "slos_met": slo_answer == "YES",
        "quality_improving": quality_answer == "IMPROVING",
        "experiments_promising": experiment_answer == "YES"
    }
    
    if all(decisions.values()):
        print("✅ ALL CRITICAL QUESTIONS POSITIVE")
        print("  • Status: EXCELLENT - Continue scaling")
        print("  • Action: Expand successful patterns")
        overall_decision = "EXPAND"
    elif not decisions["slos_met"]:
        print("❌ SLO COMPLIANCE FAILED")
        print("  • Status: CRITICAL - Fix SLOs first")
        print("  • Action: Halt scaling, hardening sprint")
        overall_decision = "HALT"
    elif decisions["quality_improving"]:
        print("✅ QUALITY IMPROVING")
        print("  • Status: GOOD - Continue current approach")
        print("  • Action: Keep scaling, monitor quality")
        overall_decision = "CONTINUE"
    else:
        print("⚠️  MIXED RESULTS")
        print("  • Status: CAUTION - Optimize approach")
        print("  • Action: Fix regressions before scaling")
        overall_decision = "OPTIMIZE"
    
    print(f"  Overall Decision: {overall_decision}")
    print()
    
    # Action items based on decision
    print("ACTION ITEMS:")
    print("-" * 40)
    
    action_items = []
    
    if overall_decision == "EXPAND":
        action_items.extend([
            "Scale test expansion to batch 3",
            "Expand config refactor scope",
            "Run larger topology experiments",
            "Add third use case (documentation)"
        ])
    elif overall_decision == "HALT":
        action_items.extend([
            "URGENT: Fix SLO compliance issues",
            "Investigate critical failures",
            "Run hardening sprint",
            "Pause scaling until fixed"
        ])
    elif overall_decision == "CONTINUE":
        action_items.extend([
            "Continue current scaling approach",
            "Monitor quality trends closely",
            "Fix any regressions promptly",
            "Prepare for 4-week decision"
        ])
    else:  # OPTIMIZE
        action_items.extend([
            "Identify and fix quality regressions",
            "Optimize prompt/role improvements",
            "Review experiment methodology",
            "Retry failed experiments"
        ])
    
    for i, action in enumerate(action_items, 1):
        print(f"  {i}. {action}")
    
    print()
    
    # Save weekly review
    review_data = {
        "week": 4,
        "date": datetime.now().isoformat(),
        "strict_review": True,
        "questions": {
            "slos_met": decisions["slos_met"],
            "quality_improved": decisions["quality_improving"],
            "experiments_promising": decisions["experiments_promising"]
        },
        "decision": overall_decision,
        "action_items": action_items,
        "metrics": {
            "slo_score": slo_score if 'slo_score' in locals() else 0,
            "roi_score": current_roi if 'current_roi' in locals() else 0,
            "quality_score": current_quality if 'current_quality' in locals() else 0
        }
    }
    
    with open("week4_strict_review.json", 'w') as f:
        json.dump(review_data, f, indent=2)
    
    print("✅ Week 4 strict review saved")
    
    # Add changelog entry
    operations_cadence.add_changelog_entry(
        "weekly_review",
        f"Week 4 strict review - {overall_decision}",
        "improved" if overall_decision in ["EXPAND", "CONTINUE"] else "mixed",
        {"week": 3},
        {"week": 4, "decision": overall_decision}
    )
    
    print("✅ Changelog entry added")
    
    print()
    print("=" * 60)
    print("WEEK 4 STRICT REVIEW COMPLETE")
    print(f"Decision: {overall_decision}")
    print("Next: Execute action items and prepare for Week 5")
    print("=" * 60)
    
    return review_data

if __name__ == "__main__":
    run_weekly_strict_review()
