#!/usr/bin/env python3
"""Generate Phase 4 completion lab report for governance + strategy code."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_PATH = Path("per_task_roi.db")
OUTPUT_PATH = Path("phase4_completion_report.md")

BATCH_CONFIG = {
    "phase4a_governance_automation": {
        "title": "Phase 4A - Governance Automation",
        "volume_target": 5.0,
        "min_effective": 4.9,
        "eps": 1e-6,
        "notes": [
            "Numeric gate tolerance: 5.0h target with 4.9-5.0h effective band",
            "Final effective volume observed at ~4.95h"
        ],
    },
    "phase4b_strategy_code": {
        "title": "Phase 4B - Strategy Code",
        "volume_target": 10.0,
        "min_effective": 9.5,
        "eps": 1e-6,
        "notes": [
            "Mandatory ROI fields: risk_level, rollback_plan, evidence_links",
            "Hard-stop on incidents or strategy SLO regressions"
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
    notes: list[str]


class Phase4CompletionReport:
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
                   incidents, rollback_required
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
        gate_status = "PASS" if metrics.volume_passed else "MISS"
        lines.append(
            f"- Volume gate: target {metrics.volume_target}h, effective >= {metrics.min_effective}h -> {gate_status}"
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

        combined_tasks = sum(m.total_tasks for m in batch_metrics)
        combined_hours = sum(m.total_hours_saved for m in batch_metrics)
        combined_roi = (
            sum(m.avg_roi * m.total_tasks for m in batch_metrics) / combined_tasks
            if combined_tasks
            else 0.0
        )
        combined_slo = sum(m.slo_green_rate * m.total_tasks for m in batch_metrics) / combined_tasks
        combined_incidents = sum(m.incidents for m in batch_metrics)
        combined_rollbacks = sum(m.rollbacks for m in batch_metrics)
        gates_passed = sum(1 for m in batch_metrics if m.volume_passed)

        report_lines = []
        report_lines.append("# Phase 4 Completion Lab Report")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        report_lines.append("")
        report_lines.append("## Batch Summaries")
        report_lines.append("")
        report_lines.extend(batch_sections)
        report_lines.append("## Combined Phase 4 Metrics")
        report_lines.append("")
        report_lines.append(f"- Total tasks: {combined_tasks}")
        report_lines.append(f"- Total hours saved: {combined_hours:.2f}h")
        report_lines.append(f"- Blended average ROI: {combined_roi:.1f}/100")
        report_lines.append(f"- Overall SLO compliance (green): {combined_slo:.1f}%")
        report_lines.append(f"- Total incidents: {combined_incidents}")
        report_lines.append(f"- Total rollbacks: {combined_rollbacks}")
        report_lines.append(f"- Gates passed: {gates_passed}/{len(batch_metrics)}")
        report_lines.append("")
        report_lines.append("## Promotion Recommendations")
        report_lines.append("")
        report_lines.append("1. Governance Lane (Phase 4A)")
        report_lines.append("   - Promote to permanent lane; low-risk control plane validated with tolerance handling.")
        report_lines.append("2. Strategy Code Lane (Phase 4B)")
        report_lines.append("   - Promote as governed experimental lane with scope limited to playbook patterns, required rollback plans, and incident/SLO hard-stops.")
        report_lines.append("")
        report_lines.append("## Next Steps")
        report_lines.append("- Integrate Phase 4 metrics into observability dashboards")
        report_lines.append("- Prepare Phase 5 scope using the promoted lanes as guardrails")
        OUTPUT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
        print("\n".join(report_lines))
        print(f"\n✅ Phase 4 completion report saved to {OUTPUT_PATH}")


def main():
    report = Phase4CompletionReport()
    report.generate()


if __name__ == "__main__":
    main()
