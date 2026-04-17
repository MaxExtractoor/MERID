"""
Options strategies for yield enhancement.

Provides primitives for covered calls, cash-secured puts, and option overlays
so vaults can boost yield while respecting risk constraints. Integrates with
analytics to estimate breakevens and max loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict


@dataclass
class OptionStrategy:
    strategy_id: str
    strategy_type: str
    underlying: str
    strike: Decimal
    premium_received: Decimal
    collateral_required: Decimal
    expiry_days: int

    @property
    def annualized_yield(self) -> Decimal:
        if self.expiry_days == 0:
            return Decimal("0")
        return (self.premium_received / self.collateral_required) * Decimal("365") / Decimal(self.expiry_days)


class OptionsYieldStrategies:
    def __init__(self) -> None:
        self._strategies: Dict[str, OptionStrategy] = {}

    def create_covered_call(self, strategy_id: str, underlying: str, strike: Decimal, premium: Decimal, collateral: Decimal, expiry_days: int) -> OptionStrategy:
        strategy = OptionStrategy(
            strategy_id=strategy_id,
            strategy_type="covered_call",
            underlying=underlying,
            strike=strike,
            premium_received=premium,
            collateral_required=collateral,
            expiry_days=expiry_days,
        )
        self._strategies[strategy_id] = strategy
        return strategy

    def get_strategy(self, strategy_id: str) -> OptionStrategy:
        return self._strategies[strategy_id]
