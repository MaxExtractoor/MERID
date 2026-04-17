"""
Social features for yield strategies.

Provides leaderboards, strategy sharing, and copy-trade style abstractions so
users can follow high-performing vault allocations while preserving privacy
constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from decimal import Decimal


@dataclass
class StrategyShare:
    share_id: str
    owner_id: str
    vault_id: str
    description: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    performance_30d: Decimal = Decimal("0")
    followers: int = 0


class SocialYieldNetwork:
    def __init__(self) -> None:
        self._shares: Dict[str, StrategyShare] = {}
        self._leaderboard: List[StrategyShare] = []

    def publish_strategy(self, share: StrategyShare) -> None:
        self._shares[share.share_id] = share
        self._update_leaderboard()

    def follow_strategy(self, share_id: str) -> StrategyShare:
        share = self._shares[share_id]
        share.followers += 1
        self._update_leaderboard()
        return share

    def leaderboard(self, limit: int = 10) -> List[StrategyShare]:
        return self._leaderboard[:limit]

    def _update_leaderboard(self) -> None:
        self._leaderboard = sorted(self._shares.values(), key=lambda share: (share.performance_30d, share.followers), reverse=True)
