"""
MEV opportunity optimization engine.

Evaluates bundles/opportunities from searchers, estimates net benefit after gas,
bribes, and failure risk, and selects the optimal strategy per venue.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List


@dataclass
class MEVOpportunity:
    opportunity_id: str
    description: str
    expected_profit_usd: Decimal
    gas_cost_usd: Decimal
    bribe_cost_usd: Decimal
    failure_prob: float

    @property
    def net_value(self) -> Decimal:
        risk_adjustment = Decimal(1 - self.failure_prob)
        return (self.expected_profit_usd - self.gas_cost_usd - self.bribe_cost_usd) * risk_adjustment


class MEVOptimizer:
    def __init__(self) -> None:
        self._opportunities: Dict[str, MEVOpportunity] = {}

    def submit_opportunity(self, opportunity: MEVOpportunity) -> None:
        self._opportunities[opportunity.opportunity_id] = opportunity

    def best_opportunities(self, limit: int = 3) -> List[MEVOpportunity]:
        ranked = sorted(self._opportunities.values(), key=lambda opp: opp.net_value, reverse=True)
        return ranked[:limit]
