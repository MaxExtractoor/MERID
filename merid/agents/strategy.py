"""§2 Strategy & Arbitrage Agents.

- StrategyDesignerAgent: translate research into strategy configs.
- ArbitrageAgent: scan for executable arb across all markets.
- ExecutionOptimizerAgent: choose order types, slicing, routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent
from merid.pipeline.proposal import OrderSide, OrderType, TradeDomain, TradeProposal

from utils.logger import get_logger

logger = get_logger("merid.agents.strategy")


# ── Strategy config dataclass ────────────────────────────────────────

@dataclass
class StrategyDefinition:
    """A concrete strategy definition produced by StrategyDesignerAgent."""
    strategy_id: str = ""
    domain: str = "crypto"
    instruments: List[str] = field(default_factory=list)
    entry_rules: List[str] = field(default_factory=list)
    exit_rules: List[str] = field(default_factory=list)
    position_sizing: str = "quarter_kelly"
    max_positions: int = 5
    # CRITICAL: max_notional_usd should be derived from live bankroll, not hardcoded
    # Default 0 means "derive from live bankroll" for trading strategies
    max_notional_usd: float = 0.0  # 0 = derive from live bankroll (was 5000.0 hardcoded)
    backtest_requested: bool = False
    status: str = "draft"  # draft, backtested, live, retired

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "domain": self.domain,
            "instruments": self.instruments,
            "entry_rules": self.entry_rules,
            "exit_rules": self.exit_rules,
            "position_sizing": self.position_sizing,
            "max_positions": self.max_positions,
            "max_notional_usd": self.max_notional_usd,
            "backtest_requested": self.backtest_requested,
            "status": self.status,
        }


# ======================================================================
# StrategyDesignerAgent
# ======================================================================

class StrategyDesignerAgent(CanonicalAgent):
    """Translates research theses into explicit strategy configs.

    Input: Research theses from MarketResearchAgent.
    Output: StrategyDefinition objects with rules, sizing, and instruments.
    """

    def __init__(self, agent_id: str = "strategy-designer-01"):
        super().__init__(agent_id, AgentCategory.STRATEGY)
        self._strategies: Dict[str, StrategyDefinition] = {}

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        theses = context.get("theses", [])
        new_strategies = []

        for thesis in theses:
            strat = self._thesis_to_strategy(thesis)
            if strat:
                self._strategies[strat.strategy_id] = strat
                new_strategies.append(strat)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="strategy_definitions",
            payload={
                "new_strategies": [s.to_dict() for s in new_strategies],
                "total_strategies": len(self._strategies),
            },
            confidence=0.6 if new_strategies else 0.3,
        )

    def _thesis_to_strategy(self, thesis: Dict[str, Any]) -> Optional[StrategyDefinition]:
        """Convert a thesis dict into a StrategyDefinition."""
        instrument = thesis.get("instrument", "")
        direction = thesis.get("direction", "neutral")
        if not instrument or direction == "neutral":
            return None

        sid = f"auto-{thesis.get('domain', 'crypto')}-{instrument.lower()}"
        entry = f"Enter {direction} on {instrument} when edge > 2%"
        exit_rule = "Exit at 10% profit or 5% stop loss"

        return StrategyDefinition(
            strategy_id=sid,
            domain=thesis.get("domain", "crypto"),
            instruments=[instrument],
            entry_rules=[entry],
            exit_rules=[exit_rule],
            backtest_requested=True,
            status="draft",
        )

    def get_strategy(self, strategy_id: str) -> Optional[StrategyDefinition]:
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> List[StrategyDefinition]:
        return list(self._strategies.values())


# ======================================================================
# ArbitrageAgent
# ======================================================================

@dataclass
class ArbOpportunity:
    """A detected arbitrage opportunity."""
    arb_id: str = ""
    arb_type: str = "cross_exchange"  # cross_exchange, basis, funding, pm_consistency
    domain: str = "crypto"
    buy_venue: str = ""
    sell_venue: str = ""
    instrument: str = ""
    buy_price: Decimal = Decimal("0")
    sell_price: Decimal = Decimal("0")
    spread_pct: Decimal = Decimal("0")
    estimated_profit_usd: Decimal = Decimal("0")
    confidence: float = 0.7
    legs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "arb_id": self.arb_id,
            "arb_type": self.arb_type,
            "domain": self.domain,
            "buy_venue": self.buy_venue,
            "sell_venue": self.sell_venue,
            "instrument": self.instrument,
            "buy_price": str(self.buy_price),
            "sell_price": str(self.sell_price),
            "spread_pct": str(self.spread_pct),
            "estimated_profit_usd": str(self.estimated_profit_usd),
            "confidence": self.confidence,
        }


class ArbitrageAgent(CanonicalAgent):
    """Scans for executable arb across all supported markets.

    Covers:
    - Prediction: same-market consistency, time-to-expiry plays (Kalshi).
    - Crypto: cross-exchange spot arb, basis/funding arb.
    Output: ArbOpportunity objects with explicit legs.
    """

    def __init__(
        self,
        agent_id: str = "arb-agent-01",
        min_spread_pct: Decimal = Decimal("0.002"),
    ):
        super().__init__(agent_id, AgentCategory.STRATEGY)
        self.min_spread_pct = min_spread_pct
        self._opportunities: List[ArbOpportunity] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Scan for arb opportunities across all domains.

        In production: fetches quotes from all adapters, computes spreads,
        and produces ArbOpportunity objects.
        """
        opps = await self._scan(context)
        self._opportunities.extend(opps)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="arb_opportunities",
            payload={
                "opportunities": [o.to_dict() for o in opps],
                "count": len(opps),
                "min_spread_pct": str(self.min_spread_pct),
            },
            confidence=0.8 if opps else 0.3,
        )

    async def _scan(self, context: Dict[str, Any]) -> List[ArbOpportunity]:
        """Override point for actual arb scanning."""
        return []

    def to_proposals(self, opp: ArbOpportunity, qty: Decimal) -> List[TradeProposal]:
        """Convert an ArbOpportunity into buy+sell TradeProposals."""
        domain = TradeDomain.CRYPTO if opp.domain == "crypto" else TradeDomain.PREDICTION
        buy = TradeProposal(
            domain=domain, venue=opp.buy_venue,
            instrument_id=opp.instrument,
            side=OrderSide.BUY, order_type=OrderType.LIMIT,
            qty=qty, price=opp.buy_price,
            strategy_id=f"arb-{opp.arb_type}",
            agent_id=self.agent_id,
            risk_tags=["arb", opp.arb_type],
            rationale=f"Arb buy leg: spread {opp.spread_pct:.4%}",
        )
        sell = TradeProposal(
            domain=domain, venue=opp.sell_venue,
            instrument_id=opp.instrument,
            side=OrderSide.SELL, order_type=OrderType.LIMIT,
            qty=qty, price=opp.sell_price,
            strategy_id=f"arb-{opp.arb_type}",
            agent_id=self.agent_id,
            risk_tags=["arb", opp.arb_type],
            rationale=f"Arb sell leg: spread {opp.spread_pct:.4%}",
        )
        return [buy, sell]


# ======================================================================
# ExecutionOptimizerAgent
# ======================================================================

@dataclass
class ExecutionPlan:
    """Optimized execution plan for a trade proposal."""
    proposal_id: str = ""
    order_type: str = "limit"
    time_in_force: str = "gtc"
    slices: int = 1
    venue_routing: str = ""
    tick_size: Decimal = Decimal("0.01")
    fee_tier: str = "maker"
    rate_limit_delay_ms: int = 0
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "slices": self.slices,
            "venue_routing": self.venue_routing,
            "tick_size": str(self.tick_size),
            "fee_tier": self.fee_tier,
            "rate_limit_delay_ms": self.rate_limit_delay_ms,
            "rationale": self.rationale,
        }


class ExecutionOptimizerAgent(CanonicalAgent):
    """Chooses order types, slicing, and routing for each proposal.

    Applies venue-specific microstructure knowledge:
    - Tick sizes, fee tiers, rate limits.
    - Limit vs market, time-in-force selection.
    - Order slicing for large orders.
    """

    # Venue-specific knowledge
    VENUE_PARAMS: Dict[str, Dict[str, Any]] = {
        "kalshi": {"tick_size": Decimal("0.01"), "fee_per_contract": Decimal("0.02"), "rate_limit_ms": 200},
        "binance": {"tick_size": Decimal("0.01"), "maker_fee": Decimal("0.001"), "rate_limit_ms": 100},
        "coinbase": {"tick_size": Decimal("0.01"), "maker_fee": Decimal("0.004"), "rate_limit_ms": 100},
        "kraken": {"tick_size": Decimal("0.01"), "maker_fee": Decimal("0.0016"), "rate_limit_ms": 3000},
        "okx": {"tick_size": Decimal("0.01"), "maker_fee": Decimal("0.0008"), "rate_limit_ms": 67},
        "alpaca": {"tick_size": Decimal("0.01"), "commission": Decimal("0"), "rate_limit_ms": 200},
        "ibkr": {"tick_size": Decimal("0.01"), "commission_per_share": Decimal("0.005"), "rate_limit_ms": 500},
    }

    def __init__(self, agent_id: str = "exec-optimizer-01"):
        super().__init__(agent_id, AgentCategory.STRATEGY)

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        proposals = context.get("proposals", [])
        plans = []
        for p in proposals:
            plan = self.optimize(p)
            plans.append(plan)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="execution_plans",
            payload={
                "plans": [p.to_dict() for p in plans],
                "count": len(plans),
            },
            confidence=0.7,
        )

    def optimize(self, proposal: TradeProposal) -> ExecutionPlan:
        """Produce an optimized execution plan for a single proposal."""
        venue = proposal.venue
        params = self.VENUE_PARAMS.get(venue, {})
        tick = params.get("tick_size", Decimal("0.01"))
        rate_limit = params.get("rate_limit_ms", 100)

        # Decide order type
        notional = float(proposal.notional_usd or 0)
        if notional > 5000:
            order_type = "limit"
            slices = max(1, int(notional / 2000))
            tif = "gtc"
        elif proposal.order_type == OrderType.MARKET:
            order_type = "market"
            slices = 1
            tif = "ioc"
        else:
            order_type = "limit"
            slices = 1
            tif = "gtc"

        # Fee tier
        fee_tier = "maker" if order_type == "limit" else "taker"

        return ExecutionPlan(
            proposal_id=proposal.proposal_id,
            order_type=order_type,
            time_in_force=tif,
            slices=slices,
            venue_routing=venue,
            tick_size=tick,
            fee_tier=fee_tier,
            rate_limit_delay_ms=rate_limit,
            rationale=f"{'Sliced' if slices > 1 else 'Single'} {order_type} on {venue}, {fee_tier} fee tier.",
        )
