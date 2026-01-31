"""
Advanced slippage modeling for HFT execution.

Combines order book depth snapshots with volatility regime tags to estimate
expected and worst-case slippage for a given trade size.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List


@dataclass
class OrderBookLevel:
    price: Decimal
    size: Decimal


@dataclass
class SlippageEstimate:
    expected_slippage_bps: Decimal
    worst_case_slippage_bps: Decimal
    consumed_levels: int


class AdvancedSlippageModel:
    def __init__(self, volatility_multiplier: Decimal = Decimal("1.0")) -> None:
        self.volatility_multiplier = volatility_multiplier

    def estimate(self, side: str, size: Decimal, levels: List[OrderBookLevel]) -> SlippageEstimate:
        remaining = size
        cost = Decimal("0")
        base_price = levels[0].price if levels else Decimal("0")
        consumed_levels = 0
        for level in levels:
            take = min(level.size, remaining)
            cost += take * level.price
            remaining -= take
            consumed_levels += 1
            if remaining <= 0:
                break
        if size == 0 or base_price == 0:
            return SlippageEstimate(Decimal("0"), Decimal("0"), consumed_levels)
        avg_price = cost / size
        direction = Decimal("1") if side == "buy" else Decimal("-1")
        expected = (avg_price - base_price) / base_price * Decimal("10000") * direction
        worst_case = expected * self.volatility_multiplier
        return SlippageEstimate(expected_slippage_bps=expected, worst_case_slippage_bps=worst_case, consumed_levels=consumed_levels)
