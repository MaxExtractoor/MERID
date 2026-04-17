"""
Dynamic reward pool adjustment service.

Adjusts reward emissions and pool weights based on KPIs like participation,
growth, and security incidents.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict
from datetime import datetime


@dataclass
class RewardPoolState:
    pool_id: str
    base_emission_per_day: Decimal
    multiplier: Decimal
    last_adjusted: datetime
    participation_rate: Decimal


class RewardPoolManager:
    def __init__(self) -> None:
        self._pools: Dict[str, RewardPoolState] = {}

    def register_pool(self, pool_id: str, emission_per_day: Decimal) -> None:
        self._pools[pool_id] = RewardPoolState(
            pool_id=pool_id,
            base_emission_per_day=emission_per_day,
            multiplier=Decimal("1.0"),
            last_adjusted=datetime.utcnow(),
            participation_rate=Decimal("0.0"),
        )

    def update_participation(self, pool_id: str, participation_rate: Decimal) -> None:
        state = self._pools[pool_id]
        state.participation_rate = participation_rate

    def adjust_rewards(self, pool_id: str) -> RewardPoolState:
        state = self._pools[pool_id]
        if state.participation_rate < Decimal("0.3"):
            state.multiplier = Decimal("1.2")
        elif state.participation_rate > Decimal("0.8"):
            state.multiplier = Decimal("0.9")
        else:
            state.multiplier = Decimal("1.0")
        state.last_adjusted = datetime.utcnow()
        return state

    def current_emission(self, pool_id: str) -> Decimal:
        state = self._pools[pool_id]
        return state.base_emission_per_day * state.multiplier
