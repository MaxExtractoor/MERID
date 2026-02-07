"""
Bug bounty program integration scaffolding.

Tracks submissions, severity, payout recommendations, and status transitions.
Designed to sync with external bounty platforms while keeping deterministic
records for governance review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class BugReport:
    report_id: str
    researcher: str
    severity: str
    summary: str
    status: str = "triage"
    payout_recommendation: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


class BugBountyProgram:
    def __init__(self) -> None:
        self._reports: Dict[str, BugReport] = {}

    def submit_report(self, report_id: str, researcher: str, severity: str, summary: str) -> BugReport:
        report = BugReport(report_id=report_id, researcher=researcher, severity=severity, summary=summary)
        self._reports[report_id] = report
        return report

    def update_status(self, report_id: str, status: str, payout: float) -> BugReport:
        report = self._reports[report_id]
        report.status = status
        report.payout_recommendation = payout
        return report
