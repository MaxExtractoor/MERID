"""
Cross-chain yield aggregation orchestrator.

Discovers and tracks yield opportunities across multiple chains, normalizes
metrics, and proposes allocations for vaults. Provides deterministic routing
decisions so downstream execution can bridge liquidity with MEV-aware logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from decimal import Decimal
from datetime import datetime


@dataclass
class YieldOpportunity:
    chain: str
    protocol: str
    strategy: str
    apy: Decimal
    liquidity_usd: Decimal
    risk_score: float
    updated_at: datetime


class CrossChainYieldRouter:
    def __init__(self) -> None:
        self._opportunities: Dict[str, YieldOpportunity] = {}

    def register_opportunity(self, opportunity: YieldOpportunity) -> None:
        key = f"{opportunity.chain}:{opportunity.protocol}:{opportunity.strategy}"
        self._opportunities[key] = opportunity

    def best_opportunities(self, max_results: int = 5, max_risk: float = 0.7) -> List[YieldOpportunity]:
        filtered = [opp for opp in self._opportunities.values() if opp.risk_score <= max_risk]
        return sorted(filtered, key=lambda opp: opp.apy, reverse=True)[:max_results]
