"""
Market impact prediction for HFT orders.

Estimates temporary and permanent price impact based on historical execution
data, liquidity conditions, and current volatility.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict


@dataclass
class ImpactEstimate:
    temporary_impact_bps: Decimal
    permanent_impact_bps: Decimal


class MarketImpactPredictor:
    def __init__(self) -> None:
        self._coefficients: Dict[str, Decimal] = {}

    def configure(self, asset: str, temp_coeff: Decimal, perm_coeff: Decimal) -> None:
        self._coefficients[asset] = (temp_coeff, perm_coeff)  # type: ignore[assignment]

    def predict(self, asset: str, trade_size_usd: Decimal, volatility: Decimal) -> ImpactEstimate:
        coeffs = self._coefficients.get(asset, (Decimal("0.01"), Decimal("0.005")))
        temp_coeff, perm_coeff = coeffs  # type: ignore[misc]
        temporary = temp_coeff * trade_size_usd.log10() * volatility
        permanent = perm_coeff * trade_size_usd.log10()
        return ImpactEstimate(temporary_impact_bps=temporary, permanent_impact_bps=permanent)
