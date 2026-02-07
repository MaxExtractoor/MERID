"""
Automated competitive advantage reporting.

Summarizes moat metrics, erosion alerts, and resource allocations into PDFs/JSON
to keep leadership and legal/compliance aligned on moat health.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class AdvantageMetric:
    metric: str
    current_value: float
    benchmark: float
    trend: float


@dataclass
class AdvantageReport:
    report_id: str
    generated_at: datetime
    highlights: List[str]
    attachments: Dict[str, str]


class AdvantageReportingService:
    def __init__(self) -> None:
        self._reports: List[AdvantageReport] = []

    def generate(self, metrics: List[AdvantageMetric]) -> AdvantageReport:
        highlights = []
        for metric in metrics:
            advantage = metric.current_value - metric.benchmark
            highlights.append(
                f"{metric.metric}: advantage {advantage:.2f} (trend {metric.trend:+.2f})"
            )
        report = AdvantageReport(
            report_id=f"adv_{len(self._reports)+1}",
            generated_at=datetime.utcnow(),
            highlights=highlights,
            attachments={
                "json": f"/reports/moat_advantage_{len(self._reports)+1}.json",
                "pdf": f"/reports/moat_advantage_{len(self._reports)+1}.pdf",
            },
        )
        self._reports.append(report)
        return report

    def latest(self, limit: int = 3) -> List[AdvantageReport]:
        return self._reports[-limit:]
