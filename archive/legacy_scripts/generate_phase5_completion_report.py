#!/usr/bin/env python3
"""Generate Phase 5 completion lab report for execution tuning."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_PATH = Path("per_task_roi.db")
OUTPUT_PATH = Path("phase5_completion_report.md")

BATCH_CONFIG = {
    "phase5_execution_tuning": {
        "title": "Phase 5 - Execution Tuning",
        "volume_target": 8.0,
        "min_effective": 7.5,
        "eps": 1e-6,
        "latency_target": 0.10,  # 10%
        "reliability_target": 0.05,  # 5%
        "notes": [
            "Execution tuning focus: latency, reliability, scaling",
            "Mandatory ROI fields: latency_improvement, reliability_improvement",
            "Improvement gates: latency >=10%, reliability >=5%"
        ],
    },
}


@dataclass
class BatchMetrics:
    batch_id: str
    title: str
    total_tasks: int
    total_hours_saved: float
    avg_roi: float
    slo_green_rate: float
    incidents: int
    rollbacks: int
    volume_target: float
    min_effective: float
    volume_passed: bool
    avg_latency_improvement: float
    avg_reliability_improvement: float
    latency_target: float
    reliability_target: float
    improvement_passed: bool
    notes: list[str]


class Phase5CompletionReport:
    def __init__(self):
        if not DB_PATH.exists():
            raise FileNotFoundError(f"ROI database not found: {DB_PATH}")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def _fetch_batch_metrics(self, batch_id: str) -> BatchMetrics:
        cfg = BATCH_CONFIG[batch_id]
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT task_id, human_time_saved_hours, roi_score, slo_compliance,
                   incidents, rollback_required, notes
            FROM per_task_roi_log
            WHERE batch_id = ?
            ORDER BY date
            """,
            (batch_id,),
        )
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"No ROI entries found for batch {batch_id}")

        total_tasks = len(rows)
        total_hours = sum(row["human_time_saved_hours"] for row in rows)
        avg_roi = sum(row["roi_score"] for row in rows) / total_tasks
        slo_green = sum(1 for row in rows if (row["slo_compliance"] or "").lower() == "green")
        slo_rate = (slo_green / total_tasks) * 100
        incidents = sum(row["incidents"] for row in rows)
        rollbacks = sum(1 for row in rows if row["rollback_required"])
        volume_passed = (total_hours + cfg["eps"]) >= cfg["min_effective"]
        
        # Extract improvements from notes (JSON-like strings)
        latency_improvements = []
        reliability_improvements = []
        for row in rows:
            notes = row["notes"] or ""
            # Try multiple patterns for Phase 5 specific notes
            try:
                import re
                # Pattern 1: JSON-style values
                latency_match = re.search(r'"latency_improvement":\s*([\d.]+)', notes)
                reliability_match = re.search(r'"reliability_improvement":\s*([\d.]+)', notes)
                
                # Pattern 2: Human-readable percentages
                if not latency_match:
                    latency_match = re.search(r"latency\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)%", notes, re.IGNORECASE)
                if not reliability_match:
                    reliability_match = re.search(r"reliabilit(y|ies)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)%", notes, re.IGNORECASE)
                
                # Pattern 3: Simple decimal values (multiply by 100 if needed)
                if not latency_match:
                    latency_match = re.search(r"latency_improvement_percent\s*=\s*([0-9]+(?:\.[0-9]+)?)", notes, re.IGNORECASE)
                if not reliability_match:
                    reliability_match = re.search(r"reliability_improvement_percent\s*=\s*([0-9]+(?:\.[0-9]+)?)", notes, re.IGNORECASE)
                
                if latency_match:
                    latency_val = float(latency_match.group(1))
                    # Convert to percentage if it looks like a decimal
                    if latency_val < 1:
                        latency_val *= 100
                    latency_improvements.append(latency_val)
                
                if reliability_match:
                    rel_group = reliability_match.group(2) if reliability_match.lastindex == 2 else reliability_match.group(1)
                    reliability_val = float(rel_group)
                    # Convert to percentage if it looks like a decimal
                    if reliability_val < 1:
                        reliability_val *= 100
                    reliability_improvements.append(reliability_val)
                    
            except Exception:
                pass
        avg_latency_improvement = sum(latency_improvements) / len(latency_improvements) if latency_improvements else 0.0
        avg_reliability_improvement = sum(reliability_improvements) / len(reliability_improvements) if reliability_improvements else 0.0
        
        improvement_passed = (avg_latency_improvement >= cfg["latency_target"] and 
                            avg_reliability_improvement >= cfg["reliability_target"])

        return BatchMetrics(
            batch_id=batch_id,
            title=cfg["title"],
            total_tasks=total_tasks,
            total_hours_saved=total_hours,
            avg_roi=avg_roi,
            slo_green_rate=slo_rate,
            incidents=incidents,
            rollbacks=rollbacks,
            volume_target=cfg["volume_target"],
            min_effective=cfg["min_effective"],
            volume_passed=volume_passed,
            avg_latency_improvement=avg_latency_improvement,
            avg_reliability_improvement=avg_reliability_improvement,
            latency_target=cfg["latency_target"],
            reliability_target=cfg["reliability_target"],
            improvement_passed=improvement_passed,
            notes=cfg["notes"],
        )

    @staticmethod
    def _format_batch_section(metrics: BatchMetrics) -> list[str]:
        lines = []
        lines.append(f"### {metrics.title} ({metrics.batch_id})")
        lines.append("")
        lines.append(f"- Tasks executed: {metrics.total_tasks}")
        lines.append(f"- Hours saved: {metrics.total_hours_saved:.2f}h")
        lines.append(f"- Average ROI: {metrics.avg_roi:.1f}/100")
        lines.append(f"- SLO compliance (green): {metrics.slo_green_rate:.1f}%")
        lines.append(f"- Incidents: {metrics.incidents}")
        lines.append(f"- Rollbacks: {metrics.rollbacks}")
        lines.append(f"- Average latency improvement: {metrics.avg_latency_improvement:.1%}")
        lines.append(f"- Average reliability improvement: {metrics.avg_reliability_improvement:.1%}")
        
        # Volume gate
        volume_status = "PASS" if metrics.volume_passed else "MISS"
        lines.append(
            f"- Volume gate: target {metrics.volume_target}h, effective >= {metrics.min_effective}h "
            f"-> {volume_status}"
        )
        
        # Improvement gate
        improvement_status = "PASS" if metrics.improvement_passed else "MISS"
        lines.append(
            f"- Improvement gate: latency >={metrics.latency_target:.0%}, reliability >={metrics.reliability_target:.0%} "
            f"-> {improvement_status}"
        )
        
        for note in metrics.notes:
            lines.append(f"- Note: {note}")
        lines.append("")
        return lines

    def generate(self):
        batch_sections = []
        batch_metrics = []
        for batch_id in BATCH_CONFIG:
            metrics = self._fetch_batch_metrics(batch_id)
            batch_metrics.append(metrics)
            batch_sections.extend(self._format_batch_section(metrics))

        # Since we only have one batch for Phase 5, combined metrics are the same as batch metrics
        metrics = batch_metrics[0]
        report_lines = []
        report_lines.append("# Phase 5 Completion Lab Report")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        report_lines.append("")
        report_lines.append("## Batch Summary")
        report_lines.append("")
        report_lines.extend(batch_sections)

        report_lines.append("## Phase 5 Assessment")
        report_lines.append("")
        report_lines.append(f"- Total tasks: {metrics.total_tasks}")
        report_lines.append(f"- Total hours saved: {metrics.total_hours_saved:.2f}h")
        report_lines.append(f"- Average ROI: {metrics.avg_roi:.1f}/100")
        report_lines.append(f"- Overall SLO compliance (green): {metrics.slo_green_rate:.1f}%")
        report_lines.append(f"- Total incidents: {metrics.incidents}")
        report_lines.append(f"- Total rollbacks: {metrics.rollbacks}")
        report_lines.append(f"- Volume gate: {'✅ PASS' if metrics.volume_passed else '❌ MISS'}")
        report_lines.append(f"- Improvement gate: {'✅ PASS' if metrics.improvement_passed else '❌ MISS'}")
        report_lines.append("")
        
        report_lines.append("## Promotion Recommendation")
        report_lines.append("")
        if metrics.volume_passed and metrics.avg_roi >= 95.0 and metrics.incidents == 0 and metrics.rollbacks == 0:
            if metrics.improvement_passed:
                report_lines.append("✅ Promote execution tuning to permanent lane with current targets.")
            else:
                report_lines.append("⚠️ Promote execution tuning to permanent lane with adjusted targets:")
                report_lines.append(f"   - Latency target: {metrics.avg_latency_improvement:.1%} (observed) vs {metrics.latency_target:.0%} (target)")
                report_lines.append(f"   - Reliability target: {metrics.avg_reliability_improvement:.1%} (observed) vs {metrics.reliability_target:.0%} (target)")
                report_lines.append("   - Volume and ROI gates remain strong.")
        else:
            report_lines.append("❌ Hold execution tuning; core gates not met.")
        report_lines.append("")
        
        report_lines.append("## Next Steps")
        if metrics.volume_passed and metrics.avg_roi >= 95.0 and metrics.incidents == 0:
            if metrics.improvement_passed:
                report_lines.append("- Integrate execution tuning into regular cadence")
                report_lines.append("- Prepare Phase 6 scope using execution tuning as guardrail")
            else:
                report_lines.append("- Adjust improvement targets to observed performance")
                report_lines.append("- Re-run Phase 5 with adjusted targets to validate")
                report_lines.append("- Consider Phase 6 scope once targets are validated")
        else:
            report_lines.append("- Investigate gate failures before proceeding")
            report_lines.append("- Address incidents or rollback issues")

        OUTPUT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
        print("\n".join(report_lines))
        print(f"\n✅ Phase 5 completion report saved to {OUTPUT_PATH}")


def main():
    report = Phase5CompletionReport()
    report.generate()


if __name__ == "__main__":
    main()
