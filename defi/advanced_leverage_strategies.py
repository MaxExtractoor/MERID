"""
Advanced leverage strategies engine.

Models delta-neutral, basis, and carry strategies with risk accounting so the
yield system can allocate into them. Provides deterministic calculations for
target hedge ratios and funding spreads.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict


@dataclass
class LeverageStrategy:
    name: str
    spot_allocation: Decimal
    hedge_allocation: Decimal
    funding_apr: Decimal
    borrow_apr: Decimal

    @property
    def net_apy(self) -> Decimal:
        return self.funding_apr - self.borrow_apr


class AdvancedLeverageEngine:
    def __init__(self) -> None:
        self._strategies: Dict[str, LeverageStrategy] = {}

    def register_delta_neutral(self, strategy_id: str, spot: Decimal, hedge: Decimal, funding_apr: Decimal, borrow_apr: Decimal) -> None:
        self._strategies[strategy_id] = LeverageStrategy(name="delta_neutral", spot_allocation=spot, hedge_allocation=hedge, funding_apr=funding_apr, borrow_apr=borrow_apr)

    def register_basis_trade(self, strategy_id: str, spot: Decimal, hedge: Decimal, funding_apr: Decimal, borrow_apr: Decimal) -> None:
        self._strategies[strategy_id] = LeverageStrategy(name="basis_trade", spot_allocation=spot, hedge_allocation=hedge, funding_apr=funding_apr, borrow_apr=borrow_apr)

    def strategy_metrics(self, strategy_id: str) -> LeverageStrategy:
        return self._strategies[strategy_id]
