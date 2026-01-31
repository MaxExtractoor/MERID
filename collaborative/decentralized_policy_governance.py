"""
Decentralized governance for collaboration policies.

Implements token-weighted voting snapshots with quorum/threshold checks so
policy updates (e.g., scope limits, trust requirements) get community approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List


@dataclass
class GovernanceProposal:
    proposal_id: str
    title: str
    description: str
    policy_changes: Dict[str, str]
    snapshot_block: int
    start_time: datetime
    end_time: datetime
    votes_for: float = 0.0
    votes_against: float = 0.0
    executed: bool = False


class DecentralizedPolicyGovernance:
    def __init__(self, quorum_pct: float = 0.2, approval_pct: float = 0.6) -> None:
        self.quorum_pct = quorum_pct
        self.approval_pct = approval_pct
        self._token_supply = 1_000_000.0
        self._proposals: Dict[str, GovernanceProposal] = {}
        self._votes: Dict[str, Dict[str, float]] = {}  # proposal_id -> voter -> weight

    def submit_proposal(self, title: str, description: str, policy_changes: Dict[str, str], duration_hours: int = 72) -> GovernanceProposal:
        proposal_id = f"gov_{len(self._proposals) + 1}"
        proposal = GovernanceProposal(
            proposal_id=proposal_id,
            title=title,
            description=description,
            policy_changes=policy_changes,
            snapshot_block=0,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=duration_hours),
        )
        self._proposals[proposal_id] = proposal
        self._votes[proposal_id] = {}
        return proposal

    def cast_vote(self, proposal_id: str, voter: str, weight: float, support: bool) -> None:
        proposal = self._proposals[proposal_id]
        if datetime.utcnow() > proposal.end_time:
            raise ValueError("Voting period ended")
        self._votes[proposal_id][voter] = weight
        if support:
            proposal.votes_for += weight
        else:
            proposal.votes_against += weight

    def finalize(self, proposal_id: str) -> bool:
        proposal = self._proposals[proposal_id]
        if datetime.utcnow() < proposal.end_time:
            raise ValueError("Voting still active")
        total_votes = proposal.votes_for + proposal.votes_against
        quorum_met = total_votes >= self._token_supply * self.quorum_pct
        approval_met = proposal.votes_for >= total_votes * self.approval_pct if total_votes else False
        proposal.executed = quorum_met and approval_met
        return proposal.executed
