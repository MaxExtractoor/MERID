#!/usr/bin/env python3
"""Generate Phase 5B completion report for execution tuning confirmation."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_PATH = Path("per_task_roi.db")
OUTPUT_PATH = Path("phase5b_completion_report.md")

BATCH_ID = "phase5b_execution_tuning"
VOLUME_TARGET = 8.0
MIN_EFFECTIVE = 7.5
LATENCY_GATE = 0.08
RELIABILITY_GATE = 0.04
LATENCY_STRETCH = 0.10
RELIABILITY_STRETCH = 0.05
ROI_GATE = 95.0
SLO_GATE = 95.0


@dataclass
class BatchMetrics:
    total_tasks: int
    total_hours: float
    avg_roi: float
    slo_green_rate: float
    incidents: int
    rollbacks: int
    avg_latency: float
    avg_reliability: float


class Phase5BReport:
    def __init__(self):
        if not DB_PATH.exists():
            raise FileNotFoundError(f"ROI database not found: {DB_PATH}")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def fetch_metrics(self) -> BatchMetrics:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT human_time_saved_hours,
                   roi_score,
                   slo_compliance,
                   incidents,
                   rollback_required,
                   latency_improvement,
                   reliability_improvement
              FROM per_task_roi_log
             WHERE batch_id = ?
             ORDER BY date
            """,
            (BATCH_ID,),
        )
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"No ROI entries found for batch {BATCH_ID}")

        total_tasks = len(rows)
        total_hours = sum(row["human_time_saved_hours"] for row in rows)
        avg_roi = sum(row["roi_score"] for row in rows) / total_tasks
        slo_green = sum(1 for row in rows if (row["slo_compliance"] or "").lower() == "green")
        slo_green_rate = slo_green / total_tasks * 100
        incidents = sum(row["incidents"] for row in rows)
        rollbacks = sum(1 for row in rows if row["rollback_required"])

        latency_values = [row["latency_improvement"] or 0.0 for row in rows]
        reliability_values = [row["reliability_improvement"] or 0.0 for row in rows]
        avg_latency = sum(latency_values) / total_tasks
        avg_reliability = sum(reliability_values) / total_tasks

        return BatchMetrics(
            total_tasks=total_tasks,
            total_hours=total_hours,
            avg_roi=avg_roi,
            slo_green_rate=slo_green_rate,
            incidents=incidents,
            rollbacks=rollbacks,
            avg_latency=avg_latency,
            avg_reliability=avg_reliability,
        )

    @staticmethod
    def _fmt_pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    def generate(self):
        metrics = self.fetch_metrics()

        volume_pass = metrics.total_hours + 1e-6 >= MIN_EFFECTIVE
        roi_pass = metrics.avg_roi >= ROI_GATE
        slo_pass = metrics.slo_green_rate >= SLO_GATE
        latency_pass = metrics.avg_latency >= LATENCY_GATE
        reliability_pass = metrics.avg_reliability >= RELIABILITY_GATE
        improvement_pass = latency_pass and reliability_pass
        incident_pass = metrics.incidents == 0 and metrics.rollbacks == 0
        stretch_latency_hit = metrics.avg_latency >= LATENCY_STRETCH
        stretch_reliability_hit = metrics.avg_reliability >= RELIABILITY_STRETCH

        report_lines = []
        report_lines.append("# Phase 5B Execution Tuning Completion Report")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        report_lines.append("")
        report_lines.append("## Batch Summary")
        report_lines.append("")
        report_lines.append(f"- Batch ID: {BATCH_ID}")
        report_lines.append(f"- Tasks executed: {metrics.total_tasks}")
        report_lines.append(f"- Hours saved: {metrics.total_hours:.2f}h")
        report_lines.append(f"- Average ROI: {metrics.avg_roi:.1f}/100")
        report_lines.append(f"- SLO compliance (green): {metrics.slo_green_rate:.1f}%")
        report_lines.append(f"- Incidents: {metrics.incidents}")
        report_lines.append(f"- Rollbacks: {metrics.rollbacks}")
        report_lines.append(f"- Average latency improvement: {self._fmt_pct(metrics.avg_latency)}")
        report_lines.append(f"- Average reliability improvement: {self._fmt_pct(metrics.avg_reliability)}")
        report_lines.append("")

        report_lines.append("## Gate Results")
        report_lines.append("")
        report_lines.append(f"- Volume gate (target {VOLUME_TARGET}h, effective ≥{MIN_EFFECTIVE}h): {'✅ PASS' if volume_pass else '❌ MISS'} ({metrics.total_hours:.2f}h)")
        report_lines.append(f"- ROI gate (≥{ROI_GATE}): {'✅ PASS' if roi_pass else '❌ MISS'} ({metrics.avg_roi:.1f})")
        report_lines.append(f"- SLO gate (green ≥{SLO_GATE}%): {'✅ PASS' if slo_pass else '❌ MISS'} ({metrics.slo_green_rate:.1f}%)")
        report_lines.append(f"- Improvement gate (latency ≥{LATENCY_GATE*100:.0f}%, reliability ≥{RELIABILITY_GATE*100:.0f}%): {'✅ PASS' if improvement_pass else '❌ MISS'}")
        report_lines.append(f"  - Latency: {'✅' if latency_pass else '❌'} {self._fmt_pct(metrics.avg_latency)}")
        report_lines.append(f"  - Reliability: {'✅' if reliability_pass else '❌'} {self._fmt_pct(metrics.avg_reliability)}")
        report_lines.append(f"- Incident gate (0 incidents & rollbacks): {'✅ PASS' if incident_pass else '❌ MISS'}")
        report_lines.append("")

        report_lines.append("## Stretch Metric Tracking")
        report_lines.append("")
        report_lines.append(f"- Latency stretch (≥{LATENCY_STRETCH*100:.0f}%): {'✅ hit' if stretch_latency_hit else '⚠️ miss'} ({self._fmt_pct(metrics.avg_latency)})")
        report_lines.append(f"- Reliability stretch (≥{RELIABILITY_STRETCH*100:.0f}%): {'✅ hit' if stretch_reliability_hit else '⚠️ miss'} ({self._fmt_pct(metrics.avg_reliability)})")
        report_lines.append("  - Note: stretch metrics tracked for aspirational comparison only")
        report_lines.append("")

        overall_pass = all([volume_pass, roi_pass, slo_pass, improvement_pass, incident_pass])
        report_lines.append("## Promotion Recommendation")
        report_lines.append("")
        if overall_pass:
            report_lines.append("✅ Phase 5B confirmed the tuned gates. Promote execution tuning to governed lane and proceed to Phase 6 planning.")
            if not stretch_latency_hit or not stretch_reliability_hit:
                report_lines.append("- Stretch metrics remain aspirational; continue tracking during Phase 6.")
        else:
            report_lines.append("❌ Hold promotion; investigate gate misses before Phase 6.")
        report_lines.append("")

        report_lines.append("## Next Steps")
        report_lines.append("- File this report with Phase 5 artifacts")
        if overall_pass:
            report_lines.append("- Launch Phase 6 combined lane experiment using the new playbook")
            report_lines.append("- Maintain joint SLO + incident monitoring per Phase 6 plan")
        else:
            report_lines.append("- Run remediation tasks and re-execute Phase 5B")
        report_lines.append("")

        OUTPUT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
        print("\n".join(report_lines))
        print(f"\n✅ Phase 5B completion report saved to {OUTPUT_PATH}")


def main():
    report = Phase5BReport()
    report.generate()


if __name__ == "__main__":
    main()
