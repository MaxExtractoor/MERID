"""
Automated IP filing and tracking service.

Generates trademark/patent filing stubs, tracks jurisdiction statuses, and
emits reminders for renewals or evidence submissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List


@dataclass
class IPFiling:
    filing_id: str
    jurisdiction: str
    filing_type: str
    status: str
    submitted_at: datetime
    next_deadline: datetime
    metadata: Dict[str, str] = field(default_factory=dict)


class IPFilingTracker:
    def __init__(self) -> None:
        self._filings: Dict[str, IPFiling] = {}

    def create_filing(self, filing_id: str, jurisdiction: str, filing_type: str) -> IPFiling:
        filing = IPFiling(
            filing_id=filing_id,
            jurisdiction=jurisdiction,
            filing_type=filing_type,
            status="draft",
            submitted_at=datetime.utcnow(),
            next_deadline=datetime.utcnow() + timedelta(days=30),
        )
        self._filings[filing_id] = filing
        return filing

    def update_status(self, filing_id: str, status: str, next_deadline: datetime | None = None) -> IPFiling:
        filing = self._filings[filing_id]
        filing.status = status
        if next_deadline:
            filing.next_deadline = next_deadline
        return filing

    def upcoming_deadlines(self, within_days: int = 14) -> List[IPFiling]:
        threshold = datetime.utcnow() + timedelta(days=within_days)
        return [filing for filing in self._filings.values() if filing.next_deadline <= threshold]
