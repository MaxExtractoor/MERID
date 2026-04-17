"""
Cross-chain invariant enforcement engine.

Tracks invariants (e.g., supply parity, reserve ratios) across multiple
networks and raises alerts when deviations exceed tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List
from datetime import datetime


@dataclass
class ChainState:
    chain_id: str
    reserves_usd: Decimal
    liabilities_usd: Decimal
    circulating_supply: Decimal
    last_updated: datetime


@dataclass
class Invariant:
    invariant_id: str
    description: str
    tolerance_pct: Decimal


@dataclass
class InvariantBreach:
    invariant_id: str
    chain_a: str
    chain_b: str
    deviation_pct: Decimal
    detected_at: datetime


class CrossChainInvariantEnforcer:
    def __init__(self) -> None:
        self._states: Dict[str, ChainState] = {}
        self._invariants: Dict[str, Invariant] = {}

    def record_state(self, state: ChainState) -> None:
        self._states[state.chain_id] = state

    def register_invariant(self, invariant: Invariant) -> None:
        self._invariants[invariant.invariant_id] = invariant

    def check_supply_parity(self, invariant_id: str) -> List[InvariantBreach]:
        invariant = self._invariants[invariant_id]
        breaches: List[InvariantBreach] = []
        states = list(self._states.values())
        for i, a in enumerate(states):
            for b in states[i + 1 :]:
                if a.circulating_supply == 0:
                    continue
                deviation = abs((a.circulating_supply - b.circulating_supply) / a.circulating_supply) * Decimal("100")
                if deviation > invariant.tolerance_pct:
                    breaches.append(
                        InvariantBreach(
                            invariant_id=invariant_id,
                            chain_a=a.chain_id,
                            chain_b=b.chain_id,
                            deviation_pct=deviation,
                            detected_at=datetime.utcnow(),
                        )
                    )
        return breaches
