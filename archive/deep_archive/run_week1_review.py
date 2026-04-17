#!/usr/bin/env python3
"""
Week 1 Swarm Review - First Real Data Point
Starting the operational cadence with actual metrics collection
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.operations.cadence import operations_cadence
from swarm.ci.reliability_monitor import CIReliabilityMonitor
from swarm.quality.metrics_collector import quality_collector
from swarm.roi.tracker import roi_tracker
from utils.logger import get_logger

logger = get_logger("swarm.weekly_review")

def run_week_1_review():
    """Run the first weekly swarm review - establishing baseline"""
    print("=" * 60)
    print("WEEK 1 SWARM REVIEW - BASELINE ESTABLISHMENT")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Status: Establishing operational baseline")
    print()
    
    # 1) CI Reliability Report
    print("1) CI RELIABILITY METRICS")
    print("-" * 30)
    ci_monitor = CIReliabilityMonitor()
    ci_passed = ci_monitor.run_ci_checks("week1_ci_report.json")
    
    try:
        with open("week1_ci_report.json", 'r') as f:
            ci_report = json.load(f)
        
        ci_metrics = ci_report["metrics"]
        print(f"   Success Rate: {ci_metrics['success_rate']:.2%}")
        print(f"   Avg Cascade Size: {ci_metrics['avg_cascade_size']:.2f}")
        print(f"   Avg Branching Factor: {ci_metrics['avg_branching_factor']:.2f}")
        print(f"   Avg Misalignment: {ci_metrics['avg_misalignment']:.2f}")
        print(f"   Avg Retry Index: {ci_metrics['avg_retry_index']:.2f}")
        print(f"   CI Status: {'✅ PASSED' if ci_passed else '❌ FAILED'}")
        
    except Exception as e:
        print(f"   Error loading CI report: {e}")
        ci_metrics = {}
    
    print()
    
    # 2) Quality Metrics Snapshot
    print("2) QUALITY METRICS SNAPSHOT")
    print("-" * 30)
    
    # Get quality trends (small window since we're just starting)
    quality_trends = quality_collector.analyze_quality_trends(window_size=5)
    
    if "error" not in quality_trends:
        averages = quality_trends.get("averages", {})
        print(f"   Test Coverage: {averages.get('test_coverage', 0):.1%}")
        print(f"   Defect Rate: {averages.get('defect_rate', 0):.1%}")
        print(f"   Developer Efficiency: {averages.get('developer_efficiency', 0):.1f} tokens/turn")
        print(f"   Quality Score: {quality_trends.get('quality_score', 0):.1f}/100")
    else:
        print("   No quality data available yet (baseline established)")
    
    print()
    
    # 3) ROI Snapshot
    print("3) ROI SNAPSHOT")
    print("-" * 30)
    
    roi_impact = roi_tracker.get_productivity_impact()
    
    if "error" not in roi_impact:
        print(f"   Total Tasks Completed: {roi_impact['total_tasks_completed']}")
        print(f"   Total Time Saved: {roi_impact['total_human_time_saved_hours']:.1f} hours")
        print(f"   Avg Time Saved per Task: {roi_impact['avg_time_saved_per_task_hours']:.1f} hours")
        print(f"   Avg ROI Score: {roi_impact['avg_roi_score']:.1f}/100")
        print(f"   Positive Quality Impact: {roi_impact['positive_quality_impact_percentage']:.1f}%")
    else:
        print("   No ROI data available yet (baseline established)")
    
    print()
    
    # 4) SLO Compliance Check
    print("4) SLO COMPLIANCE")
    print("-" * 30)
    
    # Combine metrics for SLO check
    combined_metrics = {
        "success_rate": ci_metrics.get("success_rate", 0),
        "avg_cascade_size": ci_metrics.get("avg_cascade_size", 0),
        "avg_branching_factor": ci_metrics.get("avg_branching_factor", 0),
        "quality_score": quality_trends.get("quality_score", 0) / 100 if "error" not in quality_trends else 0,
        "avg_misalignment": ci_metrics.get("avg_misalignment", 0),
        "avg_retry_index": ci_metrics.get("avg_retry_index", 0)
    }
    
    slo_compliance = operations_cadence.slos.check_compliance(combined_metrics)
    slo_score = operations_cadence.slos.calculate_slo_score(combined_metrics)
    
    print("   SLO Status:")
    for slo, compliant in slo_compliance.items():
        status = "✅" if compliant else "❌"
        print(f"   {status} {slo}: {combined_metrics.get(slo, 0):.2f}")
    
    print(f"   Overall SLO Score: {slo_score:.1f}/100")
    print(f"   SLO Status: {'✅ COMPLIANT' if slo_score >= 80 else '❌ NEEDS ATTENTION'}")
    
    print()
    
    # 5) Changes This Week
    print("5) CHANGES THIS WEEK")
    print("-" * 30)
    print("   • Swarm Operations framework implemented")
    print("   • CI reliability gates deployed")
    print("   • Quality metrics infrastructure created")
    print("   • ROI tracking system established")
    print("   • Topology lab environment ready")
    print("   • Enhanced watchdog rules implemented")
    print("   • Weekly review cadence started")
    
    print()
    
    # 6) Actions for Next Week
    print("6) ACTIONS FOR NEXT WEEK")
    print("-" * 30)
    
    actions = []
    
    if slo_score < 80:
        actions.append("URGENT: Address SLO compliance issues")
    
    if ci_metrics.get("success_rate", 0) < 0.9:
        actions.append("Investigate CI success rate below 90%")
    
    if "error" in quality_trends:
        actions.append("Start collecting quality metrics from real tasks")
    
    if "error" in roi_impact:
        actions.append("Run first ROI tracking experiment")
    
    # Always add standard actions
    actions.extend([
        "Select first high-ROI use case for production",
        "Run first prompt/role optimization experiment",
        "Document Swarm Ops v1 process"
    ])
    
    for i, action in enumerate(actions, 1):
        print(f"   {i}. {action}")
    
    print()
    
    # 7) Log the review
    print("7) REVIEW LOGGED")
    print("-" * 30)
    
    # Add changelog entry
    operations_cadence.add_changelog_entry(
        "infrastructure",
        "Swarm Operations framework implemented with weekly cadence",
        "improved",
        {"slo_score": 0},  # No baseline before
        {"slo_score": slo_score}
    )
    
    # Save review to operations cadence
    review_data = {
        "week": 1,
        "date": datetime.now().isoformat(),
        "ci_metrics": ci_metrics,
        "quality_metrics": quality_trends,
        "roi_metrics": roi_impact,
        "slo_score": slo_score,
        "slo_compliance": slo_compliance,
        "actions": actions,
        "status": "baseline_established"
    }
    
    with open("week1_review_log.json", 'w') as f:
        json.dump(review_data, f, indent=2)
    
    print("   ✅ Week 1 review logged to week1_review_log.json")
    print("   ✅ Changelog entry added")
    print("   ✅ Baseline established for trend analysis")
    
    print()
    print("=" * 60)
    print("WEEK 1 COMPLETE - BASELINE ESTABLISHED")
    print("Next review: Week 2 - Focus on first ROI use case")
    print("=" * 60)
    
    return review_data

if __name__ == "__main__":
    run_week_1_review()
