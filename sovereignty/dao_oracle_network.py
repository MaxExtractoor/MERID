"""
DAO-operated decentralized oracle network scaffolding.

Simulates registered oracle reporters, stake, performance metrics, and quorum
based value publication. Intended as a drop-in replacement for centralized
feeds once on-chain contracts are ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
import statistics


@dataclass
class OracleReporter:
    reporter_id: str
    stake: float
    reputation: float = 1.0
    last_submission: datetime = field(default_factory=datetime.utcnow)


class DAOOracleNetwork:
    def __init__(self, quorum: int = 3) -> None:
        self.quorum = quorum
        self._reporters: Dict[str, OracleReporter] = {}
        self._price_history: List[Dict[str, object]] = []

    def register_reporter(self, reporter_id: str, stake: float) -> None:
        self._reporters[reporter_id] = OracleReporter(reporter_id=reporter_id, stake=stake)

    def submit_price(self, reporter_id: str, asset: str, price: float) -> None:
        reporter = self._reporters[reporter_id]
        reporter.last_submission = datetime.utcnow()
        self._price_history.append({"asset": asset, "price": price, "reporter": reporter_id, "timestamp": reporter.last_submission})

    def get_consensus_price(self, asset: str) -> float:
        submissions = [entry for entry in self._price_history[-10:] if entry["asset"] == asset]
        if len(submissions) < self.quorum:
            raise ValueError("Not enough submissions")
        return statistics.median(entry["price"] for entry in submissions)
