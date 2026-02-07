"""
Cross-chain arbitrage detection engine.

Monitors price feeds across multiple chains/venues, computes adjusted spreads
after fees/bridging latency, and emits actionable opportunities for the HFT
swarm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from decimal import Decimal
from datetime import datetime


@dataclass
class ChainPrice:
    chain: str
    venue: str
    asset: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime


@dataclass
class ArbitrageOpportunity:
    buy_chain: str
    sell_chain: str
    asset: str
    spread_bps: Decimal
    size_usd: Decimal
    feasibility_score: float


class CrossChainArbitrageDetector:
    def __init__(self, fee_bps: Decimal = Decimal("5"), bridge_latency_s: float = 30.0) -> None:
        self.fee_bps = fee_bps
        self.bridge_latency_s = bridge_latency_s
        self._prices: Dict[str, ChainPrice] = {}

    def record_price(self, price: ChainPrice) -> None:
        key = f"{price.chain}:{price.venue}:{price.asset}"
        self._prices[key] = price

    def find_opportunities(self, asset: str) -> List[ArbitrageOpportunity]:
        relevant = [price for price in self._prices.values() if price.asset == asset]
        opportunities: List[ArbitrageOpportunity] = []
        for buy in relevant:
            for sell in relevant:
                if buy.chain == sell.chain:
                    continue
                raw_spread = sell.bid - buy.ask
                spread_bps = (raw_spread / buy.ask) * Decimal("10000")
                net_spread = spread_bps - self.fee_bps
                if net_spread > 0:
                    feasibility = max(0.0, float(net_spread) / 100 - self.bridge_latency_s / 100)
                    opportunities.append(
                        ArbitrageOpportunity(
                            buy_chain=buy.chain,
                            sell_chain=sell.chain,
                            asset=asset,
                            spread_bps=net_spread,
                            size_usd=Decimal("100000"),
                            feasibility_score=feasibility,
                        )
                    )
        return sorted(opportunities, key=lambda opp: opp.spread_bps, reverse=True)
