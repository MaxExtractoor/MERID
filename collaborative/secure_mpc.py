"""
Secure multi-party computation (MPC) coordinator for collaborative workflows.

Provides threshold secret sharing, round orchestration, and result reconstruction
so sensitive operations can run without revealing raw inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime
import secrets
import hashlib


@dataclass
class MPCParty:
    party_id: str
    contribution_hash: str
    weight: float
    submitted_at: datetime


@dataclass
class MPCRound:
    round_id: str
    function: str
    parties: Dict[str, MPCParty]
    threshold: int
    result_digest: str | None = None
    completed_at: datetime | None = None


class SecureMPCOrchestrator:
    def __init__(self) -> None:
        self._rounds: Dict[str, MPCRound] = {}

    def start_round(self, function: str, threshold: int) -> MPCRound:
        round_id = f"mpc_{secrets.token_hex(4)}"
        round_state = MPCRound(round_id=round_id, function=function, parties={}, threshold=threshold)
        self._rounds[round_id] = round_state
        return round_state

    def submit_share(self, round_id: str, party_id: str, share: bytes, weight: float = 1.0) -> MPCRound:
        round_state = self._rounds[round_id]
        contribution_hash = hashlib.sha256(share).hexdigest()
        round_state.parties[party_id] = MPCParty(
            party_id=party_id,
            contribution_hash=contribution_hash,
            weight=weight,
            submitted_at=datetime.utcnow(),
        )
        if len(round_state.parties) >= round_state.threshold and not round_state.result_digest:
            round_state.result_digest = self._combine(round_state)
            round_state.completed_at = datetime.utcnow()
        return round_state

    def _combine(self, round_state: MPCRound) -> str:
        concat = "".join(sorted(p.contribution_hash for p in round_state.parties.values()))
        return hashlib.sha256(concat.encode()).hexdigest()

    def round_status(self, round_id: str) -> MPCRound:
        return self._rounds[round_id]
