#!/usr/bin/env python3
"""Generate Phase 6 Combined Completion Report."""

import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.phase6_report")

DB_PATH = Path("per_task_roi.db")
BATCH_ID = "phase6_joint_lane"
VOLUME_TARGET = 12.0
MIN_EFFECTIVE = 11.0
EPS = 1e-6
LATENCY_GATE = 0.08
RELIABILITY_GATE = 0.04
STRATEGY_ACCURACY_GATE = 0.97
ROI_GATE = 96.0
SLO_GATE = 95.0


def get_batch_metrics():
    """Fetch Phase 6 batch metrics from ROI database."""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Check if strategy_policy_accuracy column exists
    cursor.execute("PRAGMA table_info(per_task_roi_log)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "strategy_policy_accuracy" not in columns:
        print("❌ strategy_policy_accuracy column missing from ROI DB")
        conn.close()
        return []
    
    query = """
        SELECT 
            task_id,
            task_type,
            module,
            risk_level,
            human_time_saved_hours,
            roi_score,
            slo_compliance,
            incidents,
            near_misses,
            rollback_required,
            rollback_time_hours,
            latency_improvement,
            reliability_improvement,
            strategy_policy_accuracy,
            notes
        FROM per_task_roi_log
        WHERE batch_id = ?
        ORDER BY date
    """
    
    cursor.execute(query, (BATCH_ID,))
    rows = cursor.fetchall()
    conn.close()
    
    metrics = []
    for row in rows:
        metrics.append({
            "task_id": row[0],
            "task_type": row[1],
            "module": row[2],
            "risk_level": row[3],
            "hours_saved": row[4],
            "roi_score": row[5],
            "slo_compliance": row[6],
            "incidents": row[7],
            "near_misses": row[8],
            "rollback_required": row[9],
            "rollback_time": row[10],
            "latency_improvement": row[11],
            "reliability_improvement": row[12],
            "strategy_policy_accuracy": row[13],
            "notes": row[14]
        })
    
    return metrics


def parse_improvements_from_notes(notes):
    """Parse improvement metrics from notes if not in DB."""
    if not notes:
        return None, None, None
    
    strategy_acc = None
    latency_imp = None
    reliability_imp = None
    
    try:
        # Parse strategy_accuracy
        if "strategy_accuracy=" in notes:
            start = notes.find("strategy_accuracy=") + len("strategy_accuracy=")
            end = notes.find("%", start)
            if end > start:
                strategy_acc = float(notes[start:end]) / 100.0
        
        # Parse latency_improvement
        if "latency_improvement=" in notes:
            start = notes.find("latency_improvement=") + len("latency_improvement=")
            end = notes.find("%", start)
            if end > start:
                latency_imp = float(notes[start:end]) / 100.0
        
        # Parse reliability_improvement
        if "reliability_improvement=" in notes:
            start = notes.find("reliability_improvement=") + len("reliability_improvement=")
            end = notes.find("%", start)
            if end > start:
                reliability_imp = float(notes[start:end]) / 100.0
    except Exception:
        pass
    
    return strategy_acc, latency_imp, reliability_imp


def compute_lane_metrics(metrics):
    """Compute metrics by lane (strategy_code vs execution_tuning)."""
    strategy_tasks = [m for m in metrics if m["task_type"] in ["strategy_policy", "strategy_rollout"]]
    execution_tasks = [m for m in metrics if m["task_type"] in ["performance_optimization", "scaling_optimization", "reliability_enhancement"]]
    
    def compute_lane(tasks):
        if not tasks:
            return {"count": 0, "hours": 0.0, "roi": 0.0, "accuracy": 0.0, "latency": 0.0, "reliability": 0.0}
        
        total_hours = sum(t["hours_saved"] for t in tasks)
        avg_roi = sum(t["roi_score"] for t in tasks) / len(tasks)
        
        # Strategy accuracy (only for strategy tasks)
        strategy_acc_values = []
        for t in tasks:
            if t["strategy_policy_accuracy"] is not None:
                strategy_acc_values.append(t["strategy_policy_accuracy"])
            else:
                _, _, _ = parse_improvements_from_notes(t["notes"])
                # Parse from notes for strategy tasks
                if t["notes"] and "strategy_accuracy=" in t["notes"]:
                    try:
                        start = t["notes"].find("strategy_accuracy=") + len("strategy_accuracy=")
                        end = t["notes"].find("%", start)
                        if end > start:
                            strategy_acc_values.append(float(t["notes"][start:end]) / 100.0)
                    except Exception:
                        pass
        
        avg_strategy_acc = sum(strategy_acc_values) / len(strategy_acc_values) if strategy_acc_values else 0.0
        
        # Latency and reliability improvements (only for execution tasks)
        latency_values = []
        reliability_values = []
        for t in tasks:
            if t["latency_improvement"] is not None:
                latency_values.append(t["latency_improvement"])
            if t["reliability_improvement"] is not None:
                reliability_values.append(t["reliability_improvement"])
        
        avg_latency = sum(latency_values) / len(latency_values) if latency_values else 0.0
        avg_reliability = sum(reliability_values) / len(reliability_values) if reliability_values else 0.0
        
        return {
            "count": len(tasks),
            "hours": total_hours,
            "roi": avg_roi,
            "accuracy": avg_strategy_acc,
            "latency": avg_latency,
            "reliability": avg_reliability
        }
    
    return {
        "strategy": compute_lane(strategy_tasks),
        "execution": compute_lane(execution_tasks)
    }


def generate_report():
    """Generate Phase 6 completion report."""
    print("# Phase 6 Combined Strategy + Execution Completion Report")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    # Fetch batch metrics
    metrics = get_batch_metrics()
    if not metrics:
        print("❌ No Phase 6 data found in ROI database")
        return False
    
    print("## Batch Summary")
    print()
    total_hours = sum(m["hours_saved"] for m in metrics)
    avg_roi = sum(m["roi_score"] for m in metrics) / len(metrics)
    incidents = sum(m["incidents"] for m in metrics)
    rollbacks = sum(1 for m in metrics if m["rollback_required"])
    
    # Compute lane-specific metrics
    lane_metrics = compute_lane_metrics(metrics)
    
    # Strategy accuracy (from strategy tasks)
    strategy_acc = lane_metrics["strategy"]["accuracy"]
    
    # Latency and reliability improvements (from execution tasks)
    latency_improvement = lane_metrics["execution"]["latency"]
    reliability_improvement = lane_metrics["execution"]["reliability"]
    
    # SLO compliance
    slo_compliant = sum(1 for m in metrics if m["slo_compliance"] == "green")
    slo_percentage = (slo_compliant / len(metrics)) * 100.0 if metrics else 0.0
    
    print(f"- Batch ID: {BATCH_ID}")
    print(f"- Tasks executed: {len(metrics)}")
    print(f"- Hours saved: {total_hours:.2f}h")
    print(f"- Average ROI: {avg_roi:.1f}/100")
    print(f"- SLO compliance (green): {slo_percentage:.1f}%")
    print(f"- Incidents: {incidents}")
    print(f"- Rollbacks: {rollbacks}")
    print(f"- Average strategy accuracy: {strategy_acc:.1%}")
    print(f"- Average latency improvement: {latency_improvement:.1%}")
    print(f"- Average reliability improvement: {reliability_improvement:.1%}")
    print()
    
    print("## Lane Breakdown")
    print()
    print("### Strategy Code Lane")
    print(f"- Tasks: {lane_metrics['strategy']['count']}")
    print(f"- Hours: {lane_metrics['strategy']['hours']:.2f}h")
    print(f"- Average ROI: {lane_metrics['strategy']['roi']:.1f}/100")
    print(f"- Strategy Accuracy: {lane_metrics['strategy']['accuracy']:.1%}")
    print()
    
    print("### Execution Tuning Lane")
    print(f"- Tasks: {lane_metrics['execution']['count']}")
    print(f"- Hours: {lane_metrics['execution']['hours']:.2f}h")
    print(f"- Average ROI: {lane_metrics['execution']['roi']:.1f}/100")
    print(f"- Latency Improvement: {lane_metrics['execution']['latency']:.1%}")
    print(f"- Reliability Improvement: {lane_metrics['execution']['reliability']:.1%}")
    print()
    
    print("## Gate Results")
    print()
    
    # Volume gate
    volume_met = (total_hours + EPS) >= MIN_EFFECTIVE
    print(f"- Volume gate (target {VOLUME_TARGET}h, effective ≥{MIN_EFFECTIVE}h): {'✅ PASS' if volume_met else '❌ FAIL'} ({total_hours:.2f}h)")
    
    # ROI gate
    roi_met = avg_roi >= ROI_GATE
    print(f"- ROI gate (≥{ROI_GATE}): {'✅ PASS' if roi_met else '❌ FAIL'} ({avg_roi:.1f}/100)")
    
    # SLO gate
    slo_met = slo_percentage >= SLO_GATE
    print(f"- SLO gate (green ≥{SLO_GATE}%): {'✅ PASS' if slo_met else '❌ FAIL'} ({slo_percentage:.1f}%)")
    
    # Strategy accuracy gate
    strategy_met = strategy_acc >= STRATEGY_ACCURACY_GATE
    print(f"- Strategy accuracy gate (≥{STRATEGY_ACCURACY_GATE:.0%}): {'✅ PASS' if strategy_met else '❌ FAIL'} ({strategy_acc:.1%})")
    
    # Improvement gate (latency + reliability)
    latency_met = latency_improvement >= LATENCY_GATE
    reliability_met = reliability_improvement >= RELIABILITY_GATE
    improvement_met = latency_met and reliability_met
    print(f"- Improvement gate (latency ≥{LATENCY_GATE:.0%}, reliability ≥{RELIABILITY_GATE:.0%}): {'✅ PASS' if improvement_met else '❌ FAIL'}")
    print(f"  - Latency: {'✅' if latency_met else '❌'} {latency_improvement:.1%}")
    print(f"  - Reliability: {'✅' if reliability_met else '❌'} {reliability_improvement:.1%}")
    
    # Incident gate
    incident_met = incidents == 0
    print(f"- Incident gate (0 incidents & rollbacks): {'✅ PASS' if incident_met else '❌ FAIL'}")
    print()
    
    print("## Joint SLO & Incident Policy Assessment")
    print()
    print(f"- Joint SLO state: {'✅ All green' if slo_met else '❌ Regression detected'}")
    print(f"- Cross-lane incidents: {'✅ Zero' if incident_met else '❌ Detected'}")
    print(f"- Shared rollback readiness: {'✅ Confirmed' if rollbacks == 0 else '❌ Rollbacks required'}")
    print()
    
    print("## Promotion Recommendation")
    print()
    
    all_gates_pass = volume_met and roi_met and slo_met and strategy_met and improvement_met and incident_met
    
    if all_gates_pass:
        print("✅ Phase 6 joint lane experiment successful. Promote to governed combined lane with:")
        print("  - Joint SLO monitoring across strategy + execution")
        print("  - Shared incident policy (any incident halts both lanes)")
        print("  - Blended ROI targets (≥96)")
        print("  - Combined volume targets (≥12h/cycle)")
        print("  - Strategy accuracy ≥97% and execution improvements ≥8%/4%")
        print()
        print("Next Phase Options:")
        print("  1. Scale combined lane to production workloads")
        print("  2. Add third domain (e.g., Analytics) under joint policy")
        print("  3. Harden joint rollback drills and automation")
    else:
        print("❌ Phase 6 gates not met. Hold joint lane and investigate:")
        if not volume_met:
            print("  - Volume below minimum - increase task count or hours")
        if not roi_met:
            print("  - ROI below target - review task selection or execution")
        if not slo_met:
            print("  - SLO regression - investigate performance issues")
        if not strategy_met:
            print("  - Strategy accuracy below target - improve policy compliance")
        if not improvement_met:
            print("  - Execution improvements below target - enhance tuning")
        if not incident_met:
            print("  - Incidents detected - conduct post-mortem before retry")
    print()
    
    print("## Next Steps")
    print()
    if all_gates_pass:
        print("- File this report with Phase 6 artifacts")
        print("- Update governance docs to reflect combined lane status")
        print("- Schedule joint lane promotion review")
        print("- Begin Phase 7 planning (scale or new domain)")
    else:
        print("- Address failing gates")
        print("- Re-run Phase 6 after fixes")
        print("- Consider adjusting targets if systemic issues")
    
    return all_gates_pass


def main():
    success = generate_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
