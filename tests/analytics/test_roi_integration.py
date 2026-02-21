#!/usr/bin/env python3
"""
Test ROI Integration
Test the complete ROI integration flow
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from integrate_task_runner_roi import log_task_completion
from weekly_review_roi import run_weekly_review

def test_roi_integration():
    """Test the complete ROI integration flow"""
    print("=" * 70)
    print("TEST ROI INTEGRATION")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Purpose: Test complete ROI integration flow")
    print()
    
    print("STEP 1: LOG SAMPLE TASK")
    print("-" * 50)
    
    # Sample task data
    task_config = {
        "type": "test_expansion",
        "module": "swarm/quality",
        "risk_level": "low",
        "complexity": "medium"
    }
    
    execution_metrics = {
        "success": True,
        "execution_time_seconds": 600.0,
        "swarm_topology": "current_mesh",
        "agent_count": 3,
        "tool_count": 8,
        "enforcement_mode": "log_only",
        "slo_compliance": "green",
        "slo_violations": [],
        "incidents": 0,
        "near_misses": 0,
        "rollback_required": False,
        "rollback_time_hours": 0.0,
        "run_number": 1
    }
    
    roi_calculations = {
        "human_baseline_hours": 2.5,
        "human_time_saved_hours": 2.33,
        "token_cost": 15000.0,
        "infra_cost_usd": 0.05,
        "cost_savings_usd": 233.0,
        "quality_improvement": 0.93,
        "defects_found": 2,
        "defects_avoided": 2,
        "human_review_friction": 0.1,
        "business_value": "high",
        "impact_score": 85.0,
        "roi_score": 99.0,
        "revenue_impact_usd": 0.0,
        "risk_reduction_usd": 500.0,
        "human_verified": True,
        "evidence_links": ["dashboard_url", "diff_url"],
        "notes": "Standard test expansion task for quality module"
    }
    
    context = {
        "experiment_id": None,
        "batch_id": "week6_batch_1",
        "run_id": "run_2025_01_25_001"
    }
    
    try:
        task_id = log_task_completion(task_config, execution_metrics, roi_calculations, context)
        print(f"✅ Task logged successfully: {task_id}")
    except Exception as e:
        print(f"❌ Error logging task: {e}")
        return False
    
    print()
    
    print("STEP 2: RUN WEEKLY REVIEW")
    print("-" * 50)
    
    try:
        summary = run_weekly_review(1, "test_weekly_review.md")
        if summary:
            print("✅ Weekly review completed successfully")
            
            # Print key metrics
            overview = summary["weekly_overview"]
            print(f"  • Tasks: {overview['total_tasks']}")
            print(f"  • Hours Saved: {overview['total_hours_saved']:.1f}h")
            print(f"  • Avg ROI: {overview['avg_roi_score']:.1f}/100")
            print(f"  • Success Rate: {overview['success_rate']:.1%}")
            print(f"  • SLO Compliance: {overview['slo_compliance_rate']:.1%}")
            
            print()
            print("TOP RECOMMENDATIONS:")
            for i, rec in enumerate(summary["recommendations"][:3], 1):
                print(f"  {i}. {rec}")
            
            return True
        else:
            print("❌ Weekly review failed")
            return False
            
    except Exception as e:
        print(f"❌ Error running weekly review: {e}")
        return False

if __name__ == "__main__":
    success = test_roi_integration()
    
    print()
    print("=" * 70)
    print("ROI INTEGRATION TEST COMPLETE")
    print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}")
    print("Next: Ready for Week 6 scaling when SLOs are green")
    print("=" * 70)
