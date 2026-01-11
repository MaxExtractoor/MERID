"""
StrategyAgent - Trade strategy per MASTER_SPEC v1.0

Agent ID: strategy-agent-01
Role: Trade strategy formulation
Expertise: 0.89
Risk Factor: 0.5

This agent:
- Formulates trade strategies based on signals
- Determines entry/exit points
- Calculates position sizing
- Manages trade lifecycle

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from agents.interface import (
    AgentInterface,
    AgentVote,
    VoteDecision,
    MarketState,
    Proposal,
    Outcome,
    AgentState,
)
from utils.logger import get_logger

logger = get_logger("agents.strategy")


class StrategyType(Enum):
    """Types of trading strategies."""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    RANGE_TRADING = "range_trading"


@dataclass
class TradeSetup:
    """A potential trade setup."""
    setup_id: str
    strategy_type: StrategyType
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float
    confidence: float
    reasoning: str
    timestamp: float = field(default_factory=time.time)


class StrategyAgent(AgentInterface):
    """
    Strategy Agent - Formulates trade strategies.
    
    Capabilities:
    - Trend following strategy detection
    - Mean reversion opportunity identification
    - Momentum-based entries
    - Breakout pattern recognition
    - Position sizing based on volatility
    
    This agent translates market analysis into
    actionable trade setups with defined risk parameters.
    """
    
    AGENT_ID = "strategy-agent-01"
    EXPERTISE_SCORE = 0.89
    RISK_FACTOR = 0.5
    
    DEFAULT_RISK_PER_TRADE = 0.02
    MAX_POSITION_SIZE = 0.10
    MIN_REWARD_RISK_RATIO = 2.0
    
    def __init__(self) -> None:
        """Initialize strategy agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._active_setups: Dict[str, TradeSetup] = {}
        self._setup_history: List[TradeSetup] = []
        self._market_context: Dict[str, object] = {}
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state for strategy formulation.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self._market_context = {
            "timestamp": market_state.timestamp,
            "prices": dict(market_state.prices),
            "volumes": dict(market_state.volumes),
            "volatility": market_state.volatility_index,
            "sentiment": market_state.news_sentiment,
        }
        
        self.set_working_memory("market_context", self._market_context)
    
    async def analyze(self) -> Dict[str, object]:
        """
        Analyze market for trade setups.
        
        Returns:
            Analysis with identified setups
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        setups: List[TradeSetup] = []
        
        for symbol, price in self._market_context.get("prices", {}).items():
            setup = self._evaluate_symbol_for_setup(symbol, price)
            if setup:
                setups.append(setup)
                self._active_setups[setup.setup_id] = setup
        
        best_setup = max(setups, key=lambda s: s.confidence) if setups else None
        
        self._last_analysis = {
            "timestamp": time.time(),
            "setups_found": len(setups),
            "best_setup": self._setup_to_dict(best_setup) if best_setup else None,
            "market_regime": self._detect_market_regime(),
            "recommended_strategy": self._recommend_strategy(),
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Analysis: %d setups found, regime=%s",
            len(setups), self._last_analysis.get("market_regime")
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote based on strategy analysis.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with strategy reasoning
        """
        self._state = AgentState.VOTING
        self.heartbeat()
        
        if proposal.is_expired():
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning="Proposal expired before vote could be cast",
            )
        
        if self._last_analysis is None:
            await self.analyze()
        
        decision, confidence, reasoning = self._evaluate_proposal(
            proposal.proposal_type, proposal.payload
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
        })
        
        if len(self._prediction_history) > 100:
            self._prediction_history = self._prediction_history[-100:]
        
        self._state = AgentState.READY
        
        return AgentVote(
            agent_id=self._agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        
        if outcome.proposal_id in self._active_setups:
            setup = self._active_setups.pop(outcome.proposal_id)
            self._setup_history.append(setup)
            if len(self._setup_history) > 100:
                self._setup_history = self._setup_history[-100:]
        
        self._state = AgentState.READY
    
    def _evaluate_symbol_for_setup(
        self,
        symbol: str,
        current_price: float,
    ) -> Optional[TradeSetup]:
        """
        Evaluate a symbol for potential trade setup.
        
        Args:
            symbol: Trading symbol
            current_price: Current price
            
        Returns:
            TradeSetup if valid setup found, None otherwise
        """
        volatility = self._market_context.get("volatility", 0.02)
        sentiment = self._market_context.get("sentiment", 0)
        
        atr_estimate = current_price * volatility
        
        if sentiment > 0.3 and volatility < 0.05:
            direction = "long"
            entry = current_price
            stop = entry - (atr_estimate * 1.5)
            target = entry + (atr_estimate * 3.0)
            strategy = StrategyType.TREND_FOLLOWING
            confidence = 0.6 + (sentiment * 0.2)
            
        elif sentiment < -0.3 and volatility < 0.05:
            direction = "short"
            entry = current_price
            stop = entry + (atr_estimate * 1.5)
            target = entry - (atr_estimate * 3.0)
            strategy = StrategyType.TREND_FOLLOWING
            confidence = 0.6 + (abs(sentiment) * 0.2)
            
        elif volatility > 0.05:
            direction = "long" if sentiment > 0 else "short"
            entry = current_price
            stop = entry - (atr_estimate * 2.0) if direction == "long" else entry + (atr_estimate * 2.0)
            target = entry + (atr_estimate * 4.0) if direction == "long" else entry - (atr_estimate * 4.0)
            strategy = StrategyType.BREAKOUT
            confidence = 0.5
            
        else:
            return None
        
        risk_amount = abs(entry - stop)
        reward_amount = abs(target - entry)
        
        if risk_amount == 0 or reward_amount / risk_amount < self.MIN_REWARD_RISK_RATIO:
            return None
        
        position_size = min(
            self.DEFAULT_RISK_PER_TRADE / (risk_amount / entry),
            self.MAX_POSITION_SIZE
        )
        
        return TradeSetup(
            setup_id=f"{symbol}_{int(time.time())}",
            strategy_type=strategy,
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            position_size_pct=position_size,
            confidence=min(confidence, 0.9),
            reasoning=f"{strategy.value} setup based on sentiment={sentiment:.2f}, volatility={volatility:.4f}",
        )
    
    def _detect_market_regime(self) -> str:
        """Detect current market regime."""
        volatility = self._market_context.get("volatility", 0)
        sentiment = self._market_context.get("sentiment", 0)
        
        if volatility > 0.06:
            return "high_volatility"
        elif volatility < 0.02:
            return "low_volatility"
        elif sentiment > 0.5:
            return "bullish_trend"
        elif sentiment < -0.5:
            return "bearish_trend"
        else:
            return "ranging"
    
    def _recommend_strategy(self) -> str:
        """Recommend strategy based on market regime."""
        regime = self._detect_market_regime()
        
        recommendations = {
            "high_volatility": "breakout",
            "low_volatility": "mean_reversion",
            "bullish_trend": "trend_following_long",
            "bearish_trend": "trend_following_short",
            "ranging": "range_trading",
        }
        
        return recommendations.get(regime, "wait")
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal from strategy perspective."""
        if self._last_analysis is None:
            return (VoteDecision.ABSTAIN, 0.3, "No analysis available")
        
        best_setup = self._last_analysis.get("best_setup")
        regime = self._last_analysis.get("market_regime", "unknown")
        recommended = self._last_analysis.get("recommended_strategy", "wait")
        
        if proposal_type in ("buy", "long"):
            if best_setup and best_setup.get("direction") == "long":
                return (
                    VoteDecision.APPROVE,
                    best_setup.get("confidence", 0.6),
                    f"Long setup identified: {best_setup.get('reasoning')}. "
                    f"Entry={best_setup.get('entry_price'):.2f}, "
                    f"Stop={best_setup.get('stop_loss'):.2f}, "
                    f"Target={best_setup.get('take_profit'):.2f}.",
                )
            elif regime == "bearish_trend":
                return (
                    VoteDecision.REJECT,
                    0.7,
                    f"Market regime is {regime}. Long positions not recommended.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"No clear long setup. Regime={regime}, recommended={recommended}.",
                )
        
        elif proposal_type in ("sell", "short"):
            if best_setup and best_setup.get("direction") == "short":
                return (
                    VoteDecision.APPROVE,
                    best_setup.get("confidence", 0.6),
                    f"Short setup identified: {best_setup.get('reasoning')}.",
                )
            elif regime == "bullish_trend":
                return (
                    VoteDecision.REJECT,
                    0.7,
                    f"Market regime is {regime}. Short positions not recommended.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"No clear short setup. Regime={regime}.",
                )
        
        return (
            VoteDecision.ABSTAIN,
            0.3,
            f"Proposal type '{proposal_type}' outside strategy domain.",
        )
    
    def _setup_to_dict(self, setup: TradeSetup) -> Dict[str, object]:
        """Convert setup to dictionary."""
        return {
            "setup_id": setup.setup_id,
            "strategy_type": setup.strategy_type.value,
            "symbol": setup.symbol,
            "direction": setup.direction,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "take_profit": setup.take_profit,
            "position_size_pct": setup.position_size_pct,
            "confidence": setup.confidence,
            "reasoning": setup.reasoning,
        }


_strategy_agent: Optional[StrategyAgent] = None


def get_strategy_agent() -> StrategyAgent:
    """Get or create strategy agent singleton."""
    global _strategy_agent
    if _strategy_agent is None:
        _strategy_agent = StrategyAgent()
    return _strategy_agent
