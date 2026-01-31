"""
Automated compliance reporting engine for collaborative workflows.

Aggregates collaboration, messaging, and FL metrics, formats them into regulator
templates (SOC, GDPR, MAS), and emits machine-readable + PDF stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class ComplianceMetric:
    name: str
    value: str
    category: str


@dataclass
class ComplianceReport:
    report_id: str
    framework: str
    generated_at: datetime
    metrics: List[ComplianceMetric]
    attachments: Dict[str, str]


class AutomatedComplianceReporting:
    def __init__(self) -> None:
        self._reports: List[ComplianceReport] = []

    def generate_report(self, framework: str, metrics: List[ComplianceMetric]) -> ComplianceReport:
        report = ComplianceReport(
            report_id=f"comp_{len(self._reports) + 1}",
            framework=framework,
            generated_at=datetime.utcnow(),
            metrics=metrics,
            attachments={
                "json": f"/reports/{framework.lower()}_{len(self._reports)+1}.json",
                "pdf": f"/reports/{framework.lower()}_{len(self._reports)+1}.pdf",
            },
        )
        self._reports.append(report)
        return report

    def latest_reports(self, limit: int = 5) -> List[ComplianceReport]:
        return self._reports[-limit:]
