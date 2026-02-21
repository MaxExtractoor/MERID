#!/usr/bin/env python3
"""Generate Phase 7 Production Completion Report."""

import sys
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.phase7_report")

DB_PATH = Path("per_task_roi.db")
BATCH_ID = "phase7_production_combined"
VOLUME_TARGET = 16.0
MIN_EFFECTIVE = 15.0
EPS = 1e-6
LATENCY_GATE = 0.08
RELIABILITY_GATE = 0.04
STRATEGY_ACCURACY_GATE = 0.97
ROI_GATE = 97.0
SLO_GATE = 95.0

# Production-specific gates
PNL_LOSS_GATE = 500.0
DRAWDOWN_GATE = 0.02
DECISION_LATENCY_GATE = 100
EXECUTION_LATENCY_GATE = 200
ERROR_RATE_GATE = 0.1
CONCENTRATION_GATE = 0.4


def get_phase7_metrics():
    """Fetch Phase 7 production metrics from ROI database."""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
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
            real_pnl_usd,
            daily_pnl_usd,
            max_drawdown_percent,
            execution_latency_ms,
            decision_latency_ms,
            error_rate_percent,
            position_concentration,
            kill_switch_triggered,
            kill_switch_reason,
            slo_compliance_percent,
            error_budget_used_percent,
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
            "real_pnl": row[11],
            "daily_pnl": row[12],
            "max_drawdown": row[13],
            "execution_latency": row[14],
            "decision_latency": row[15],
            "error_rate": row[16],
            "concentration": row[17],
            "kill_switch_triggered": bool(row[18]) if row[18] is not None else False,
            "kill_switch_reason": row[19],
            "slo_compliance_percent": row[20],
            "error_budget_used": row[21],
            "notes": row[22]
        })
    
    return metrics


def compute_production_metrics(metrics):
    """Compute aggregate production metrics."""
    if not metrics:
        return {}
    
    # Basic metrics
    total_hours = sum(m["hours_saved"] for m in metrics)
    avg_roi = sum(m["roi_score"] for m in metrics) / len(metrics)
    
    # Production P&L metrics
    total_pnl = sum(m["real_pnl"] for m in metrics if m["real_pnl"] is not None)
    daily_loss = max(0, -sum(m["daily_pnl"] for m in metrics if m["daily_pnl"] is not None and m["daily_pnl"] < 0))
    max_drawdown = max(m["max_drawdown"] for m in metrics if m["max_drawdown"] is not None)
    
    # Latency metrics
    decision_latencies = [m["decision_latency"] for m in metrics if m["decision_latency"] is not None]
    execution_latencies = [m["execution_latency"] for m in metrics if m["execution_latency"] is not None]
    avg_decision_latency = sum(decision_latencies) / len(decision_latencies) if decision_latencies else 0
    avg_execution_latency = sum(execution_latencies) / len(execution_latencies) if execution_latencies else 0
    
    # Error and concentration
    error_rates = [m["error_rate"] for m in metrics if m["error_rate"] is not None]
    avg_error_rate = sum(error_rates) / len(error_rates) if error_rates else 0
    concentrations = [m["concentration"] for m in metrics if m["concentration"] is not None]
    avg_concentration = sum(concentrations) / len(concentrations) if concentrations else 0
    
    # SLO compliance
    slo_compliant = sum(1 for m in metrics if m["slo_compliance"] == "green")
    slo_percentage = (slo_compliant / len(metrics)) * 100 if metrics else 0
    
    # Kill switch status
    kill_switch_triggered = any(m["kill_switch_triggered"] for m in metrics)
    kill_switch_reasons = [m["kill_switch_reason"] for m in metrics if m["kill_switch_reason"]]
    
    # Error budget usage
    error_budget_usage = sum(m["error_budget_used"] for m in metrics if m["error_budget_used"] is not None) / len(metrics) if metrics else 0
    
    # Lane breakdown
    strategy_tasks = [m for m in metrics if m["task_type"] in ["strategy_deployment", "risk_monitoring"]]
    execution_tasks = [m for m in metrics if m["task_type"] in ["execution_optimization", "monitoring_setup"]]
    
    return {
        "total_tasks": len(metrics),
        "total_hours": total_hours,
        "avg_roi": avg_roi,
        "total_pnl": total_pnl,
        "daily_loss": daily_loss,
        "max_drawdown": max_drawdown,
        "avg_decision_latency": avg_decision_latency,
        "avg_execution_latency": avg_execution_latency,
        "avg_error_rate": avg_error_rate,
        "avg_concentration": avg_concentration,
        "slo_percentage": slo_percentage,
        "kill_switch_triggered": kill_switch_triggered,
        "kill_switch_reasons": kill_switch_reasons,
        "error_budget_usage": error_budget_usage,
        "strategy_tasks": len(strategy_tasks),
        "execution_tasks": len(execution_tasks),
        "incidents": sum(m["incidents"] for m in metrics),
        "rollbacks": sum(1 for m in metrics if m["rollback_required"])
    }


def check_production_gates(metrics):
    """Check Phase 7 production-specific gates."""
    prod_metrics = compute_production_metrics(metrics)
    
    if not prod_metrics:
        return {
            "volume_met": False,
            "roi_met": False,
            "pnl_met": False,
            "slo_met": False,
            "risk_met": False,
            "incident_met": False,
            "kill_switch_met": False,
            "all_met": False
        }
    
    # Gate checks
    volume_met = (prod_metrics["total_hours"] + EPS) >= MIN_EFFECTIVE
    roi_met = prod_metrics["avg_roi"] >= ROI_GATE
    pnl_met = prod_metrics["daily_loss"] <= PNL_LOSS_GATE and prod_metrics["max_drawdown"] <= DRAWDOWN_GATE
    slo_met = (prod_metrics["avg_decision_latency"] <= DECISION_LATENCY_GATE and 
              prod_metrics["avg_execution_latency"] <= EXECUTION_LATENCY_GATE and
              prod_metrics["avg_error_rate"] <= ERROR_RATE_GATE)
    risk_met = prod_metrics["avg_concentration"] <= CONCENTRATION_GATE
    incident_met = prod_metrics["incidents"] == 0
    kill_switch_met = not prod_metrics["kill_switch_triggered"]
    
    all_met = volume_met and roi_met and pnl_met and slo_met and risk_met and incident_met and kill_switch_met
    
    return {
        "volume_met": volume_met,
        "roi_met": roi_met,
        "pnl_met": pnl_met,
        "slo_met": slo_met,
        "risk_met": risk_met,
        "incident_met": incident_met,
        "kill_switch_met": kill_switch_met,
        "all_met": all_met,
        "metrics": prod_metrics
    }


def generate_report():
    """Generate Phase 7 production completion report."""
    print("# Phase 7 Production Scaling Completion Report")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    # Fetch production metrics
    metrics = get_phase7_metrics()
    if not metrics:
        print("❌ No Phase 7 data found in ROI database")
        return False
    
    # Compute production metrics
    prod_metrics = compute_production_metrics(metrics)
    
    print("## Production Batch Summary")
    print()
    print(f"- Batch ID: {BATCH_ID}")
    print(f"- Tasks executed: {prod_metrics['total_tasks']}")
    print(f"- Hours saved: {prod_metrics['total_hours']:.2f}h")
    print(f"- Average ROI: {prod_metrics['avg_roi']:.1f}/100")
    print(f"- Total P&L: ${prod_metrics['total_pnl']:.2f}")
    print(f"- Daily Loss: ${prod_metrics['daily_loss']:.2f}")
    print(f"- Max Drawdown: {prod_metrics['max_drawdown']:.2%}")
    print(f"- SLO compliance (green): {prod_metrics['slo_percentage']:.1f}%")
    print(f"- Incidents: {prod_metrics['incidents']}")
    print(f"- Rollbacks: {prod_metrics['rollbacks']}")
    print()
    
    print("## Production Lane Breakdown")
    print()
    print(f"### Strategy Code Lane")
    print(f"- Tasks: {prod_metrics['strategy_tasks']}")
    print(f"- Focus: Production deployment and risk monitoring")
    print()
    
    print(f"### Execution Tuning Lane")
    print(f"- Tasks: {prod_metrics['execution_tasks']}")
    print(f"- Focus: Production execution optimization and monitoring")
    print()
    
    print("## Production Performance Metrics")
    print()
    print(f"- Average Decision Latency: {prod_metrics['avg_decision_latency']:.1f}ms")
    print(f"- Average Execution Latency: {prod_metrics['avg_execution_latency']:.1f}ms")
    print(f"- Average Error Rate: {prod_metrics['avg_error_rate']:.2%}")
    print(f"- Average Position Concentration: {prod_metrics['avg_concentration']:.1%}")
    print(f"- Error Budget Usage: {prod_metrics['error_budget_usage']:.1f}%")
    print(f"- Kill Switch Status: {'🚨 TRIGGERED' if prod_metrics['kill_switch_triggered'] else '✅ ARMED'}")
    if prod_metrics['kill_switch_reasons']:
        print(f"- Kill Switch Reasons: {', '.join(prod_metrics['kill_switch_reasons'])}")
    print()
    
    # Check production gates
    gate_results = check_production_gates(metrics)
    
    print("## Production Gate Results")
    print()
    print(f"- Volume gate (target {VOLUME_TARGET}h, effective ≥{MIN_EFFECTIVE}h): {'✅ PASS' if gate_results['volume_met'] else '❌ FAIL'} ({prod_metrics['total_hours']:.2f}h)")
    print(f"- ROI gate (≥{ROI_GATE}): {'✅ PASS' if gate_results['roi_met'] else '❌ FAIL'} ({prod_metrics['avg_roi']:.1f}/100)")
    print(f"- P&L gate (loss ≤${PNL_LOSS_GATE}, drawdown ≤{DRAWDOWN_GATE:.0%}): {'✅ PASS' if gate_results['pnl_met'] else '❌ FAIL'} loss=${prod_metrics['daily_loss']:.2f}, drawdown={prod_metrics['max_drawdown']:.2%}")
    print(f"- SLO gate (≤{DECISION_LATENCY_GATE}/{EXECUTION_LATENCY_GATE}ms, ≤{ERROR_RATE_GATE:.1%}): {'✅ PASS' if gate_results['slo_met'] else '❌ FAIL'}")
    print(f"  - Decision Latency: {'✅' if prod_metrics['avg_decision_latency'] <= DECISION_LATENCY_GATE else '❌'} {prod_metrics['avg_decision_latency']:.1f}ms")
    print(f"  - Execution Latency: {'✅' if prod_metrics['avg_execution_latency'] <= EXECUTION_LATENCY_GATE else '❌'} {prod_metrics['avg_execution_latency']:.1f}ms")
    print(f"  - Error Rate: {'✅' if prod_metrics['avg_error_rate'] <= ERROR_RATE_GATE else '❌'} {prod_metrics['avg_error_rate']:.2%}")
    print(f"- Risk gate (concentration ≤{CONCENTRATION_GATE:.0%}): {'✅ PASS' if gate_results['risk_met'] else '❌ FAIL'} {prod_metrics['avg_concentration']:.1%}")
    print(f"- Incident gate (zero incidents): {'✅ PASS' if gate_results['incident_met'] else '❌ FAIL'} {prod_metrics['incidents']}")
    print(f"- Kill Switch gate (armed): {'✅ PASS' if gate_results['kill_switch_met'] else '❌ FAIL'}")
    print()
    
    print("## SLO and Error Budget Assessment")
    print()
    print(f"- Overall SLO Compliance: {prod_metrics['slo_percentage']:.1f}%")
    print(f"- Error Budget Used: {prod_metrics['error_budget_usage']:.1f}%")
    print(f"- Burn Rate Status: {'🔥 HIGH' if prod_metrics['error_budget_usage'] > 50 else '⚠️ MODERATE' if prod_metrics['error_budget_usage'] > 20 else '✅ HEALTHY'}")
    print()
    
    print("## Production Safety Assessment")
    print()
    print(f"- Capital Constraints: {'✅ RESPECTED' if gate_results['pnl_met'] else '❌ VIOLATED'}")
    print(f"- Risk Limits: {'✅ WITHIN BOUNDS' if gate_results['risk_met'] else '❌ EXCEEDED'}")
    print(f"- Kill Switch: {'✅ READY' if gate_results['kill_switch_met'] else '❌ TRIGGERED'}")
    print(f"- Incident Response: {'✅ CLEAN' if gate_results['incident_met'] else '❌ INCIDENTS DETECTED'}")
    print()
    
    print("## Production Readiness Recommendation")
    print()
    
    if gate_results['all_met']:
        print("✅ Phase 7 production scaling successful. The combined strategy + execution lane is ready for:")
        print("  - Expanded production deployment with current constraints")
        print("  - Gradual capital increase within validated risk limits")
        print("  - Production monitoring and alerting based on SLO compliance")
        print("  - Continued joint SLO/incident policy enforcement")
        print()
        print("Production Scaling Path:")
        print("  1. Maintain current constraints for 2-week pilot validation")
        print("  2. Gradually increase notional caps by 25% per week")
        print("  3. Add additional venues after 4 weeks of stable operation")
        print("  4. Consider third domain (Analytics) integration after pilot")
    else:
        print("❌ Phase 7 production gates not met. Address constraints before scaling:")
        if not gate_results['volume_met']:
            print("  - Volume below minimum - increase task count or efficiency")
        if not gate_results['roi_met']:
            print("  - ROI below target - optimize execution or task selection")
        if not gate_results['pnl_met']:
            print("  - P&L/drawdown limits exceeded - tighten risk controls")
        if not gate_results['slo_met']:
            print("  - SLO violations - investigate latency/error rate issues")
        if not gate_results['risk_met']:
            print("  - Risk limits exceeded - adjust position sizing/limits")
        if not gate_results['incident_met']:
            print("  - Incidents detected - conduct post-mortem before retry")
        if not gate_results['kill_switch_met']:
            print("  - Kill switch triggered - investigate and resolve triggers")
    print()
    
    print("## Next Steps")
    print()
    if gate_results['all_met']:
        print("- File this report with Phase 7 production artifacts")
        print("- Schedule production expansion review with risk committee")
        print("- Update production monitoring dashboards with live metrics")
        print("- Begin Phase 8 planning (expanded production or new domain)")
    else:
        print("- Address failing gates and constraints")
        print("- Re-run Phase 7 with adjusted parameters")
        print("- Consider constraint relaxation if systemic issues")
        print("- Document lessons learned for production scaling")
    
    return gate_results['all_met']


def main():
    success = generate_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
