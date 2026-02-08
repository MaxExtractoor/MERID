"""
Agent Performance Metrics for MERID.

Tracks Sharpe ratio, max drawdown, and other risk-adjusted metrics
per agent/strategy. Used for:
- Consensus weight calculation (better agents get more influence)
- Risk manager decisions (performance-based sizing)
- Dashboard visualization

Based on TradingAgents research patterns.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("risk.agent_metrics")


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance snapshot."""
    timestamp: float
    equity: float
    pnl: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    win_count: int
    loss_count: int


@dataclass
class AgentMetrics:
    """Comprehensive metrics for an agent."""
    agent_id: str
    role: str
    
    # Equity tracking
    initial_equity: float = 10000.0
    current_equity: float = 10000.0
    peak_equity: float = 10000.0
    
    # PnL
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # Consensus metrics
    total_opinions: int = 0
    correct_predictions: int = 0
    prediction_accuracy: float = 0.5
    
    # Time series for calculations
    returns_history: List[float] = field(default_factory=list)
    equity_history: List[Tuple[float, float]] = field(default_factory=list)  # (timestamp, equity)
    drawdown_history: List[Tuple[float, float]] = field(default_factory=list)  # (timestamp, drawdown)
    
    # Derived weight for consensus
    consensus_weight: float = 1.0
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "current_equity": self.current_equity,
            "total_pnl": self.total_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.winning_trades / max(1, self.total_trades),
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "prediction_accuracy": self.prediction_accuracy,
            "consensus_weight": self.consensus_weight,
            "last_updated": self.last_updated,
        }


class AgentMetricsTracker:
    """
    Tracks performance metrics for all agents.
    
    Used to:
    1. Calculate Sharpe, drawdown, and other risk metrics
    2. Adjust consensus weights based on performance
    3. Feed dashboard visualizations
    """
    
    _instance: Optional["AgentMetricsTracker"] = None
    
    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate  # Annual risk-free rate
        self._agents: Dict[str, AgentMetrics] = {}
        self._global_equity_history: List[Tuple[float, float]] = []
        
        logger.info("AgentMetricsTracker initialized")
    
    @classmethod
    def get_instance(cls) -> "AgentMetricsTracker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ============================================
    # AGENT REGISTRATION
    # ============================================
    
    def register_agent(
        self,
        agent_id: str,
        role: str = "analyst",
        initial_equity: float = 10000.0,
    ) -> AgentMetrics:
        """Register a new agent for tracking."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentMetrics(
                agent_id=agent_id,
                role=role,
                initial_equity=initial_equity,
                current_equity=initial_equity,
                peak_equity=initial_equity,
            )
            logger.info(f"Registered agent for metrics: {agent_id}")
        return self._agents[agent_id]
    
    def get_agent(self, agent_id: str) -> Optional[AgentMetrics]:
        """Get agent metrics."""
        return self._agents.get(agent_id)
    
    def get_or_create_agent(self, agent_id: str, role: str = "analyst") -> AgentMetrics:
        """Get or create agent metrics."""
        if agent_id not in self._agents:
            return self.register_agent(agent_id, role)
        return self._agents[agent_id]
    
    # ============================================
    # TRADE RECORDING
    # ============================================
    
    def record_trade(
        self,
        agent_id: str,
        pnl: float,
        is_win: bool,
        trade_size: float = 0.0,
    ) -> None:
        """Record a completed trade for an agent."""
        agent = self.get_or_create_agent(agent_id)
        
        # Update PnL
        agent.realized_pnl += pnl
        agent.total_pnl = agent.realized_pnl + agent.unrealized_pnl
        agent.current_equity = agent.initial_equity + agent.total_pnl
        
        # Update trade counts
        agent.total_trades += 1
        if is_win:
            agent.winning_trades += 1
        else:
            agent.losing_trades += 1
        
        # Record return
        if agent.current_equity > 0:
            ret = pnl / agent.current_equity
            agent.returns_history.append(ret)
            # Keep last 252 returns (roughly 1 year of daily)
            if len(agent.returns_history) > 252:
                agent.returns_history = agent.returns_history[-252:]
        
        # Update equity history
        now = time.time()
        agent.equity_history.append((now, agent.current_equity))
        if len(agent.equity_history) > 1000:
            agent.equity_history = agent.equity_history[-1000:]
        
        # Update peak and drawdown
        if agent.current_equity > agent.peak_equity:
            agent.peak_equity = agent.current_equity
        
        agent.current_drawdown = (agent.peak_equity - agent.current_equity) / agent.peak_equity
        if agent.current_drawdown > agent.max_drawdown:
            agent.max_drawdown = agent.current_drawdown
        
        agent.drawdown_history.append((now, agent.current_drawdown))
        if len(agent.drawdown_history) > 1000:
            agent.drawdown_history = agent.drawdown_history[-1000:]
        
        # Recalculate risk metrics
        self._update_risk_metrics(agent)
        
        agent.last_updated = now
        
        logger.debug(f"Trade recorded for {agent_id}: PnL={pnl:.2f}, Sharpe={agent.sharpe_ratio:.2f}")
    
    def update_unrealized_pnl(self, agent_id: str, unrealized_pnl: float) -> None:
        """Update unrealized PnL for an agent."""
        agent = self.get_or_create_agent(agent_id)
        agent.unrealized_pnl = unrealized_pnl
        agent.total_pnl = agent.realized_pnl + agent.unrealized_pnl
        agent.current_equity = agent.initial_equity + agent.total_pnl
        agent.last_updated = time.time()
    
    # ============================================
    # OPINION TRACKING
    # ============================================
    
    def record_opinion(
        self,
        agent_id: str,
        was_correct: Optional[bool] = None,
    ) -> None:
        """Record an opinion and optionally its outcome."""
        agent = self.get_or_create_agent(agent_id)
        agent.total_opinions += 1
        
        if was_correct is not None:
            if was_correct:
                agent.correct_predictions += 1
            agent.prediction_accuracy = agent.correct_predictions / agent.total_opinions
        
        # Update consensus weight
        self._update_consensus_weight(agent)
        agent.last_updated = time.time()
    
    # ============================================
    # RISK METRIC CALCULATIONS
    # ============================================
    
    def _update_risk_metrics(self, agent: AgentMetrics) -> None:
        """Recalculate all risk metrics for an agent."""
        returns = agent.returns_history
        
        if len(returns) < 2:
            return
        
        # Sharpe Ratio (annualized)
        agent.sharpe_ratio = self._calculate_sharpe(returns)
        
        # Sortino Ratio (downside deviation)
        agent.sortino_ratio = self._calculate_sortino(returns)
        
        # Calmar Ratio (return / max drawdown)
        if agent.max_drawdown > 0:
            annualized_return = sum(returns) * (252 / len(returns))
            agent.calmar_ratio = annualized_return / agent.max_drawdown
        
        # Update consensus weight based on performance
        self._update_consensus_weight(agent)
    
    def _calculate_sharpe(self, returns: List[float]) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        
        # Annualize (assuming daily returns)
        daily_rf = self.risk_free_rate / 252
        excess_return = mean_return - daily_rf
        annualized_sharpe = (excess_return / std_dev) * math.sqrt(252)
        
        return annualized_sharpe
    
    def _calculate_sortino(self, returns: List[float]) -> float:
        """Calculate Sortino ratio (uses downside deviation)."""
        if len(returns) < 2:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        
        # Downside deviation (only negative returns)
        downside_returns = [r for r in returns if r < 0]
        if not downside_returns:
            return float('inf') if mean_return > 0 else 0.0
        
        downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0.001
        
        daily_rf = self.risk_free_rate / 252
        excess_return = mean_return - daily_rf
        sortino = (excess_return / downside_std) * math.sqrt(252)
        
        return sortino
    
    def _update_consensus_weight(self, agent: AgentMetrics) -> None:
        """
        Calculate consensus weight based on performance.
        
        Weight = accuracy_factor * sharpe_factor * drawdown_factor
        """
        # Accuracy factor (0.5 to 1.5 based on prediction accuracy)
        accuracy_factor = 0.5 + agent.prediction_accuracy
        
        # Sharpe factor (0.5 to 1.5 based on Sharpe ratio)
        sharpe_factor = 1.0
        if agent.sharpe_ratio > 1.0:
            sharpe_factor = 1.0 + min(0.5, (agent.sharpe_ratio - 1.0) * 0.25)
        elif agent.sharpe_ratio < 0:
            sharpe_factor = max(0.5, 1.0 + agent.sharpe_ratio * 0.25)
        
        # Drawdown penalty (1.0 down to 0.5 based on max drawdown)
        drawdown_factor = max(0.5, 1.0 - agent.max_drawdown)
        
        agent.consensus_weight = accuracy_factor * sharpe_factor * drawdown_factor
    
    # ============================================
    # API METHODS
    # ============================================
    
    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all agent metrics."""
        return [agent.to_dict() for agent in self._agents.values()]
    
    def get_leaderboard(self, metric: str = "sharpe_ratio", limit: int = 10) -> List[Dict[str, Any]]:
        """Get top agents by a specific metric."""
        agents = list(self._agents.values())
        
        if metric == "sharpe_ratio":
            agents.sort(key=lambda a: a.sharpe_ratio, reverse=True)
        elif metric == "total_pnl":
            agents.sort(key=lambda a: a.total_pnl, reverse=True)
        elif metric == "win_rate":
            agents.sort(key=lambda a: a.winning_trades / max(1, a.total_trades), reverse=True)
        elif metric == "prediction_accuracy":
            agents.sort(key=lambda a: a.prediction_accuracy, reverse=True)
        else:
            agents.sort(key=lambda a: a.consensus_weight, reverse=True)
        
        return [a.to_dict() for a in agents[:limit]]
    
    def get_equity_history(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get equity history for an agent."""
        agent = self.get_agent(agent_id)
        if not agent:
            return []
        
        history = agent.equity_history[-limit:]
        return [{"timestamp": ts, "equity": eq} for ts, eq in history]
    
    def get_drawdown_history(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get drawdown history for an agent."""
        agent = self.get_agent(agent_id)
        if not agent:
            return []
        
        history = agent.drawdown_history[-limit:]
        return [{"timestamp": ts, "drawdown": dd} for ts, dd in history]
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get aggregate stats across all agents."""
        if not self._agents:
            return {
                "total_agents": 0,
                "avg_sharpe": 0,
                "avg_drawdown": 0,
                "total_pnl": 0,
                "total_trades": 0,
            }
        
        agents = list(self._agents.values())
        return {
            "total_agents": len(agents),
            "avg_sharpe": sum(a.sharpe_ratio for a in agents) / len(agents),
            "avg_drawdown": sum(a.max_drawdown for a in agents) / len(agents),
            "total_pnl": sum(a.total_pnl for a in agents),
            "total_trades": sum(a.total_trades for a in agents),
            "best_agent": max(agents, key=lambda a: a.sharpe_ratio).agent_id if agents else None,
            "worst_agent": min(agents, key=lambda a: a.sharpe_ratio).agent_id if agents else None,
        }


def get_agent_metrics_tracker() -> AgentMetricsTracker:
    """Get the singleton metrics tracker."""
    return AgentMetricsTracker.get_instance()
