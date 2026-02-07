"""
On-chain dispute resolution scaffolding.

Captures disputes, assigns reviewers/delegates, and simulates multi-step
decision processes with quorum requirements. Designed to integrate with
governance delegation graph and oracle network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class DisputeRecord:
    dispute_id: str
    description: str
    filer: str
    status: str = "pending"
    reviewers: List[str] = field(default_factory=list)
    votes_for: int = 0
    votes_against: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


class OnChainDisputeResolution:
    def __init__(self, quorum: int = 3) -> None:
        self.quorum = quorum
        self._disputes: Dict[str, DisputeRecord] = {}

    def file_dispute(self, dispute_id: str, filer: str, description: str) -> DisputeRecord:
        record = DisputeRecord(dispute_id=dispute_id, filer=filer, description=description)
        self._disputes[dispute_id] = record
        return record

    def assign_reviewer(self, dispute_id: str, reviewer: str) -> None:
        record = self._disputes[dispute_id]
        record.reviewers.append(reviewer)

    def cast_vote(self, dispute_id: str, reviewer: str, support: bool) -> None:
        record = self._disputes[dispute_id]
        if reviewer not in record.reviewers:
            raise ValueError("Reviewer not assigned")
        if support:
            record.votes_for += 1
        else:
            record.votes_against += 1
        if record.votes_for + record.votes_against >= self.quorum:
            record.status = "resolved"
