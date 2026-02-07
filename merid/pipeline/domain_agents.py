"""§2 Domain Agents — PredictionMarketAgent, CryptoArbAgent, EquityAgent.

Each agent consumes market data from its domain's adapters and produces
TradeProposals tagged with the correct domain and strategy_id.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from merid.pipeline.proposal import (
    ExecutionResult,
    OrderSide,
    OrderType,
    ProposalStatus,
    TradeDomain,
    TradeProposal,
)

from utils.logger import get_logger

logger = get_logger("merid.pipeline.domain_agents")


class DomainAgent(ABC):
    """Base class for domain-specific trading agents."""

    def __init__(self, agent_id: str, domain: TradeDomain):
        self.agent_id = agent_id
        self.domain = domain
        self._active = True
        self._proposals_generated: int = 0

    @property
    def is_active(self) -> bool:
        return self._active

    def pause(self) -> None:
        self._active = False
        logger.info(f"Agent {self.agent_id} paused")

    def resume(self) -> None:
        self._active = True
        logger.info(f"Agent {self.agent_id} resumed")

    @abstractmethod
    async def generate_proposals(self) -> List[TradeProposal]:
        """Analyze market data and produce trade proposals."""

    def _make_proposal(self, **kwargs) -> TradeProposal:
        """Helper to create a proposal with agent/domain pre-filled."""
        self._proposals_generated += 1
        return TradeProposal(
            domain=self.domain,
            agent_id=self.agent_id,
            **kwargs,
        )

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "domain": self.domain.value,
            "active": self._active,
            "proposals_generated": self._proposals_generated,
        }


# ======================================================================
# Prediction Market Agent (Kalshi)
# ======================================================================

class PredictionMarketAgent(DomainAgent):
    """Agent that consumes Kalshi market data and produces PM proposals.

    Integrates with merid.prediction.strategy.KalshiStrategy for signal
    generation and merid.prediction.risk for PM-specific risk checks.
    """

    def __init__(
        self,
        agent_id: str = "pm-agent-01",
        venue: str = "kalshi",
        min_edge: Decimal = Decimal("0.03"),
        max_contracts: int = 25,
    ):
        super().__init__(agent_id, TradeDomain.PREDICTION)
        self.venue = venue
        self.min_edge = min_edge
        self.max_contracts = max_contracts
        self._watched_markets: List[str] = []

    def watch_market(self, market_id: str) -> None:
        if market_id not in self._watched_markets:
            self._watched_markets.append(market_id)

    def unwatch_market(self, market_id: str) -> None:
        self._watched_markets = [m for m in self._watched_markets if m != market_id]

    async def generate_proposals(self) -> List[TradeProposal]:
        """Scan watched Kalshi markets for edge and produce proposals.

        In production this would call KalshiStrategy.scan_markets().
        Here we define the interface; the actual data fetch + strategy
        evaluation is wired in the orchestrator.
        """
        if not self._active:
            return []
        # Placeholder: in production, fetch snapshots and run strategy
        return []

    def create_pm_proposal(
        self,
        market_id: str,
        side: str,
        contracts: int,
        price_cents: int,
        strategy_id: str = "kalshi-spec",
        rationale: str = "",
        confidence: Decimal = Decimal("0.6"),
    ) -> TradeProposal:
        """Create a prediction market trade proposal."""
        return self._make_proposal(
            venue=self.venue,
            instrument_id=f"PM:{market_id}",
            native_symbol=market_id,
            side=OrderSide.BUY if "buy" in side.lower() else OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=Decimal(contracts),
            price=Decimal(price_cents),
            notional_usd=(Decimal(contracts) * Decimal(price_cents) / Decimal("100")).quantize(Decimal("0.01")),
            strategy_id=strategy_id,
            rationale=rationale,
            confidence=confidence,
            risk_tags=["prediction", "kalshi"],
        )


# ======================================================================
# Crypto Arbitrage Agent
# ======================================================================

class CryptoArbAgent(DomainAgent):
    """Agent that detects cross-exchange crypto arbitrage opportunities.

    Monitors price discrepancies across venues (Binance, Coinbase, Kraken, OKX)
    for the same asset and produces buy/sell proposal pairs.
    """

    def __init__(
        self,
        agent_id: str = "crypto-arb-01",
        venues: Optional[List[str]] = None,
        min_spread_pct: Decimal = Decimal("0.002"),  # 0.2% min spread
        max_notional_usd: Decimal = Decimal("5000"),
    ):
        super().__init__(agent_id, TradeDomain.CRYPTO)
        self.venues = venues or ["binance", "coinbase", "kraken"]
        self.min_spread_pct = min_spread_pct
        self.max_notional_usd = max_notional_usd
        self._watched_pairs: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD"]

    def watch_pair(self, merid_symbol: str) -> None:
        if merid_symbol not in self._watched_pairs:
            self._watched_pairs.append(merid_symbol)

    async def generate_proposals(self) -> List[TradeProposal]:
        """Scan for cross-exchange arb opportunities.

        In production: fetch quotes from all venues, find spreads > min_spread_pct,
        produce buy+sell proposal pairs.
        """
        if not self._active:
            return []
        return []

    def create_arb_pair(
        self,
        merid_symbol: str,
        buy_venue: str,
        sell_venue: str,
        buy_price: Decimal,
        sell_price: Decimal,
        qty: Decimal,
        rationale: str = "",
    ) -> List[TradeProposal]:
        """Create a buy+sell proposal pair for cross-exchange arb."""
        spread_pct = (sell_price - buy_price) / buy_price
        notional = qty * buy_price

        buy = self._make_proposal(
            venue=buy_venue,
            instrument_id=merid_symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=qty,
            price=buy_price,
            notional_usd=notional,
            strategy_id="crypto-spot-arb",
            rationale=rationale or f"Arb buy on {buy_venue}: spread {spread_pct:.4%}",
            confidence=Decimal("0.8"),
            risk_tags=["crypto", "arb", "cross-exchange"],
        )
        sell = self._make_proposal(
            venue=sell_venue,
            instrument_id=merid_symbol,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=qty,
            price=sell_price,
            notional_usd=qty * sell_price,
            strategy_id="crypto-spot-arb",
            rationale=rationale or f"Arb sell on {sell_venue}: spread {spread_pct:.4%}",
            confidence=Decimal("0.8"),
            risk_tags=["crypto", "arb", "cross-exchange"],
        )
        return [buy, sell]


# ======================================================================
# Crypto Funding Arb Agent
# ======================================================================

class FundingArbAgent(DomainAgent):
    """Agent that exploits funding rate discrepancies on perp markets."""

    def __init__(
        self,
        agent_id: str = "funding-arb-01",
        venues: Optional[List[str]] = None,
        min_funding_spread: Decimal = Decimal("0.001"),
    ):
        super().__init__(agent_id, TradeDomain.CRYPTO)
        self.venues = venues or ["binance", "okx"]
        self.min_funding_spread = min_funding_spread

    async def generate_proposals(self) -> List[TradeProposal]:
        if not self._active:
            return []
        return []


# ======================================================================
# Equity Agent
# ======================================================================

class EquityAgent(DomainAgent):
    """Agent for equity/ETF trading via Alpaca and IBKR.

    Supports simple strategies: trend-following, mean reversion,
    or hedging against crypto/prediction exposures.
    """

    def __init__(
        self,
        agent_id: str = "equity-agent-01",
        venue: str = "alpaca",
        strategy: str = "trend-follow",
        max_position_usd: Decimal = Decimal("2000"),
    ):
        super().__init__(agent_id, TradeDomain.EQUITY)
        self.venue = venue
        self.strategy = strategy
        self.max_position_usd = max_position_usd
        self._watchlist: List[str] = ["SPY", "QQQ", "AAPL"]

    def set_watchlist(self, symbols: List[str]) -> None:
        self._watchlist = symbols

    async def generate_proposals(self) -> List[TradeProposal]:
        if not self._active:
            return []
        return []

    def create_equity_proposal(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Optional[Decimal] = None,
        order_type: OrderType = OrderType.MARKET,
        rationale: str = "",
    ) -> TradeProposal:
        """Create an equity trade proposal."""
        notional = qty * price if price else None
        return self._make_proposal(
            venue=self.venue,
            instrument_id=symbol,
            native_symbol=symbol,
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            order_type=order_type,
            qty=qty,
            price=price,
            notional_usd=notional,
            strategy_id=self.strategy,
            rationale=rationale,
            risk_tags=["equity", self.strategy],
        )
