"""
RiskAgent - Risk assessment per MASTER_SPEC v1.0

Agent ID: risk-agent-01
Role: Risk assessment and position sizing
Expertise: 0.85
Risk Factor: 0.2

This agent:
- Assesses risk across all proposals
- Evaluates position sizing and exposure
- Monitors portfolio risk metrics
- Votes conservatively on high-risk proposals

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
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

logger = get_logger("agents.risk_agent")


@dataclass
class RiskMetrics:
    """Current risk metrics snapshot."""
    timestamp: float
    volatility: float
    exposure_ratio: float
    max_drawdown: float
    sharpe_estimate: float
    var_95: float
    correlation_risk: float


@dataclass
class PositionRisk:
    """Risk assessment for a single position."""
    symbol: str
    size_usd: float
    leverage: float
    unrealized_pnl: float
    risk_score: float
    stop_distance_pct: float


class RiskAgent(AgentInterface):
    """
    Risk Agent - Specializes in risk assessment and management.
    
    Capabilities:
    - Volatility-based risk scoring
    - Position sizing recommendations
    - Drawdown monitoring
    - Correlation risk assessment
    - VaR estimation
    
    This agent acts as a conservative voice in consensus,
    rejecting proposals that exceed risk thresholds.
    """
    
    AGENT_ID = "risk-agent-01"
    EXPERTISE_SCORE = 0.85
    RISK_FACTOR = 0.2
    
    MAX_POSITION_SIZE_PCT = 0.10
    MAX_TOTAL_EXPOSURE_PCT = 0.50
    MAX_LEVERAGE = 3.0
    VOLATILITY_THRESHOLD = 0.05
    DRAWDOWN_THRESHOLD = 0.15
    
    def __init__(self) -> None:
        """Initialize risk agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._risk_history: List[RiskMetrics] = []
        self._position_risks: Dict[str, PositionRisk] = {}
        self._volatility_history: List[float] = []
        self._drawdown_history: List[float] = []
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
        
        self._portfolio_value: float = 100000.0
        self._current_exposure: float = 0.0
        self._peak_value: float = 100000.0
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state and update risk metrics.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self._volatility_history.append(market_state.volatility_index)
        if len(self._volatility_history) > 100:
            self._volatility_history = self._volatility_history[-100:]
        
        current_drawdown = self._calculate_drawdown()
        self._drawdown_history.append(current_drawdown)
        if len(self._drawdown_history) > 100:
            self._drawdown_history = self._drawdown_history[-100:]
        
        self.set_working_memory("current_volatility", market_state.volatility_index)
        self.set_working_memory("current_drawdown", current_drawdown)
        
        self._logger.debug(
            "Observed: volatility=%.4f, drawdown=%.4f",
            market_state.volatility_index, current_drawdown
        )
    
    async def analyze(self) -> Dict[str, object]:
        """
        Generate risk analysis.
        
        Returns:
            Risk assessment results
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        avg_volatility = (
            sum(self._volatility_history) / len(self._volatility_history)
            if self._volatility_history else 0.0
        )
        
        max_drawdown = max(self._drawdown_history) if self._drawdown_history else 0.0
        current_drawdown = self._drawdown_history[-1] if self._drawdown_history else 0.0
        
        exposure_ratio = self._current_exposure / self._portfolio_value
        
        var_95 = self._estimate_var(avg_volatility)
        
        sharpe = self._estimate_sharpe()
        
        overall_risk = self._calculate_overall_risk(
            avg_volatility, max_drawdown, exposure_ratio, var_95
        )
        
        if overall_risk > 0.8:
            risk_level = "critical"
        elif overall_risk > 0.6:
            risk_level = "high"
        elif overall_risk > 0.4:
            risk_level = "elevated"
        elif overall_risk > 0.2:
            risk_level = "moderate"
        else:
            risk_level = "low"
        
        metrics = RiskMetrics(
            timestamp=time.time(),
            volatility=avg_volatility,
            exposure_ratio=exposure_ratio,
            max_drawdown=max_drawdown,
            sharpe_estimate=sharpe,
            var_95=var_95,
            correlation_risk=0.0,
        )
        self._risk_history.append(metrics)
        if len(self._risk_history) > 100:
            self._risk_history = self._risk_history[-100:]
        
        self._last_analysis = {
            "timestamp": time.time(),
            "overall_risk": overall_risk,
            "risk_level": risk_level,
            "volatility": avg_volatility,
            "max_drawdown": max_drawdown,
            "current_drawdown": current_drawdown,
            "exposure_ratio": exposure_ratio,
            "var_95": var_95,
            "sharpe_estimate": sharpe,
            "position_count": len(self._position_risks),
            "can_take_risk": overall_risk < 0.6,
            "recommended_position_size": self._recommend_position_size(overall_risk),
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Risk analysis: level=%s, overall=%.2f, volatility=%.4f, drawdown=%.4f",
            risk_level, overall_risk, avg_volatility, max_drawdown
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on proposal based on risk assessment.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with reasoning
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
            "risk_level": self._last_analysis.get("risk_level", "unknown") if self._last_analysis else "unknown",
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
        
        if outcome.actual_value is not None:
            pnl = outcome.actual_value
            self._portfolio_value += pnl
            self._peak_value = max(self._peak_value, self._portfolio_value)
        
        self._state = AgentState.READY
    
    def update_position(
        self,
        symbol: str,
        size_usd: float,
        leverage: float = 1.0,
        unrealized_pnl: float = 0.0,
    ) -> None:
        """
        Update tracked position for risk calculation.
        
        Args:
            symbol: Position symbol
            size_usd: Position size in USD
            leverage: Position leverage
            unrealized_pnl: Unrealized P&L
        """
        risk_score = self._calculate_position_risk(size_usd, leverage)
        
        self._position_risks[symbol] = PositionRisk(
            symbol=symbol,
            size_usd=size_usd,
            leverage=leverage,
            unrealized_pnl=unrealized_pnl,
            risk_score=risk_score,
            stop_distance_pct=self._recommend_stop_distance(leverage),
        )
        
        self._current_exposure = sum(p.size_usd for p in self._position_risks.values())
    
    def close_position(self, symbol: str) -> None:
        """Remove position from tracking."""
        if symbol in self._position_risks:
            del self._position_risks[symbol]
            self._current_exposure = sum(p.size_usd for p in self._position_risks.values())
    
    def _calculate_drawdown(self) -> float:
        """Calculate current drawdown from peak."""
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - self._portfolio_value) / self._peak_value
    
    def _estimate_var(self, volatility: float) -> float:
        """
        Estimate Value at Risk (95% confidence).
        
        Args:
            volatility: Current volatility
            
        Returns:
            VaR as percentage of portfolio
        """
        z_score_95 = 1.645
        return self._current_exposure * volatility * z_score_95 / self._portfolio_value
    
    def _estimate_sharpe(self) -> float:
        """Estimate Sharpe ratio from recent performance."""
        if len(self._drawdown_history) < 10:
            return 0.0
        
        returns = [-d for d in self._drawdown_history[-20:]]
        if not returns:
            return 0.0
        
        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return 0.0
        
        risk_free_rate = 0.05 / 252
        return (avg_return - risk_free_rate) / std_dev
    
    def _calculate_overall_risk(
        self,
        volatility: float,
        max_drawdown: float,
        exposure_ratio: float,
        var_95: float,
    ) -> float:
        """
        Calculate overall risk score.
        
        Args:
            volatility: Average volatility
            max_drawdown: Maximum drawdown
            exposure_ratio: Current exposure ratio
            var_95: Value at Risk
            
        Returns:
            Overall risk score [0.0, 1.0]
        """
        vol_risk = min(volatility / self.VOLATILITY_THRESHOLD, 1.0)
        dd_risk = min(max_drawdown / self.DRAWDOWN_THRESHOLD, 1.0)
        exp_risk = min(exposure_ratio / self.MAX_TOTAL_EXPOSURE_PCT, 1.0)
        var_risk = min(var_95 / 0.10, 1.0)
        
        overall = (
            vol_risk * 0.25 +
            dd_risk * 0.30 +
            exp_risk * 0.25 +
            var_risk * 0.20
        )
        
        return min(overall, 1.0)
    
    def _calculate_position_risk(self, size_usd: float, leverage: float) -> float:
        """Calculate risk score for a single position."""
        size_risk = min(size_usd / (self._portfolio_value * self.MAX_POSITION_SIZE_PCT), 1.0)
        leverage_risk = min(leverage / self.MAX_LEVERAGE, 1.0)
        return (size_risk * 0.6 + leverage_risk * 0.4)
    
    def _recommend_position_size(self, overall_risk: float) -> float:
        """Recommend position size based on current risk."""
        if overall_risk > 0.8:
            return 0.0
        elif overall_risk > 0.6:
            return self._portfolio_value * 0.02
        elif overall_risk > 0.4:
            return self._portfolio_value * 0.05
        else:
            return self._portfolio_value * self.MAX_POSITION_SIZE_PCT
    
    def _recommend_stop_distance(self, leverage: float) -> float:
        """Recommend stop-loss distance based on leverage."""
        base_stop = 0.05
        return base_stop / max(leverage, 1.0)
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal from risk perspective."""
        if self._last_analysis is None:
            return (VoteDecision.ABSTAIN, 0.3, "No risk analysis available")
        
        risk_level = self._last_analysis.get("risk_level", "unknown")
        overall_risk = self._last_analysis.get("overall_risk", 0.5)
        can_take_risk = self._last_analysis.get("can_take_risk", False)
        
        proposed_size = float(payload.get("size_usd", 0))
        proposed_leverage = float(payload.get("leverage", 1.0))
        
        if proposal_type in ("buy", "sell", "long", "short"):
            if risk_level == "critical":
                return (
                    VoteDecision.REJECT,
                    0.95,
                    f"Risk level is CRITICAL ({overall_risk:.2f}). "
                    f"No new positions should be opened.",
                )
            
            if risk_level == "high":
                return (
                    VoteDecision.REJECT,
                    0.85,
                    f"Risk level is HIGH ({overall_risk:.2f}). "
                    f"Recommend reducing exposure before new positions.",
                )
            
            if proposed_leverage > self.MAX_LEVERAGE:
                return (
                    VoteDecision.REJECT,
                    0.90,
                    f"Proposed leverage ({proposed_leverage}x) exceeds maximum ({self.MAX_LEVERAGE}x).",
                )
            
            max_size = self._last_analysis.get("recommended_position_size", 0)
            if proposed_size > max_size * 1.5:
                return (
                    VoteDecision.REJECT,
                    0.80,
                    f"Proposed size (${proposed_size:,.0f}) exceeds recommended maximum (${max_size:,.0f}).",
                )
            
            if can_take_risk:
                return (
                    VoteDecision.APPROVE,
                    0.70,
                    f"Risk level is {risk_level} ({overall_risk:.2f}). "
                    f"Position within acceptable parameters.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.50,
                    f"Risk level is {risk_level} ({overall_risk:.2f}). "
                    f"Borderline acceptable - deferring to other agents.",
                )
        
        return (
            VoteDecision.ABSTAIN,
            0.4,
            f"Proposal type '{proposal_type}' not directly in risk domain.",
        )


_risk_agent: Optional[RiskAgent] = None
_risk_agent_lock = threading.Lock()


def get_risk_agent() -> RiskAgent:
    """Get or create risk agent singleton."""
    global _risk_agent
    if _risk_agent is None:
        with _risk_agent_lock:
            if _risk_agent is None:
                _risk_agent = RiskAgent()
    return _risk_agent
