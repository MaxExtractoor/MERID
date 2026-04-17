"""
Cross-Domain Portfolio Engine for MERID
Unified portfolio management across crypto, perps, DeFi, xStocks, memecoins, and predictions.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np

from utils.logger import get_logger

logger = get_logger("core.cross_domain_portfolio")


class AssetClass(Enum):
    """Asset classes in portfolio."""
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    DEFI_LP = "defi_lp"
    DEFI_LENDING = "defi_lending"
    XSTOCKS = "xstocks"
    MEMECOIN = "memecoin"
    PREDICTION_MARKET = "prediction_market"


@dataclass
class Position:
    """Portfolio position."""
    position_id: str
    asset_class: AssetClass
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    allocation: float
    risk_contribution: float
    timestamp: float


@dataclass
class PortfolioMetrics:
    """Portfolio-level metrics."""
    total_value_usd: float
    total_pnl: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    volatility: float
    var_95: float
    cvar_95: float
    correlation_matrix: Dict[str, Dict[str, float]]
    timestamp: float


class CrossAssetPortfolioEngine:
    """Manages portfolio across all asset classes."""
    
    def __init__(self):
        self._positions: Dict[str, Position] = {}
        self._position_history: List[Dict[str, Position]] = []
        self._pnl_history: List[float] = []
        
        # Risk limits by asset class
        self._allocation_limits = {
            AssetClass.CRYPTO_SPOT: 0.40,
            AssetClass.CRYPTO_PERP: 0.20,
            AssetClass.DEFI_LP: 0.15,
            AssetClass.DEFI_LENDING: 0.10,
            AssetClass.XSTOCKS: 0.10,
            AssetClass.MEMECOIN: 0.05,
            AssetClass.PREDICTION_MARKET: 0.05
        }
    
    def add_position(self, position: Position) -> bool:
        """Add a position to portfolio."""
        # Check allocation limits
        if not self._check_allocation_limit(position):
            logger.warning(f"Position exceeds allocation limit: {position.asset_class.value}")
            return False
        
        self._positions[position.position_id] = position
        logger.info(f"Added position: {position.symbol} ({position.asset_class.value})")
        return True
    
    def remove_position(self, position_id: str) -> None:
        """Remove a position."""
        if position_id in self._positions:
            position = self._positions[position_id]
            del self._positions[position_id]
            logger.info(f"Removed position: {position.symbol}")
    
    def update_position(self, position_id: str, current_price: float) -> None:
        """Update position with current price."""
        if position_id not in self._positions:
            return
        
        position = self._positions[position_id]
        position.current_price = current_price
        position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
        position.timestamp = time.time()
    
    def _check_allocation_limit(self, new_position: Position) -> bool:
        """Check if adding position would exceed allocation limit."""
        total_value = self.get_total_value()
        
        if total_value == 0:
            return True
        
        # Calculate current allocation for asset class
        current_allocation = sum(
            p.quantity * p.current_price
            for p in self._positions.values()
            if p.asset_class == new_position.asset_class
        ) / total_value
        
        # Calculate new allocation
        new_value = new_position.quantity * new_position.current_price
        new_allocation = (current_allocation * total_value + new_value) / (total_value + new_value)
        
        limit = self._allocation_limits.get(new_position.asset_class, 0.1)
        
        return new_allocation <= limit
    
    def get_total_value(self) -> float:
        """Get total portfolio value."""
        return sum(p.quantity * p.current_price for p in self._positions.values())
    
    def get_total_pnl(self) -> float:
        """Get total PnL."""
        return sum(p.unrealized_pnl + p.realized_pnl for p in self._positions.values())
    
    def get_allocation_by_class(self) -> Dict[AssetClass, float]:
        """Get allocation breakdown by asset class."""
        total_value = self.get_total_value()
        
        if total_value == 0:
            return {}
        
        allocation = {}
        for asset_class in AssetClass:
            class_value = sum(
                p.quantity * p.current_price
                for p in self._positions.values()
                if p.asset_class == asset_class
            )
            allocation[asset_class] = class_value / total_value
        
        return allocation
    
    def calculate_metrics(self) -> PortfolioMetrics:
        """Calculate portfolio metrics."""
        total_value = self.get_total_value()
        total_pnl = self.get_total_pnl()
        
        # Calculate returns
        if len(self._pnl_history) > 1:
            returns = np.diff(self._pnl_history)
            
            # Sharpe ratio
            sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
            
            # Sortino ratio (downside deviation)
            downside_returns = returns[returns < 0]
            downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1e-6
            sortino = np.mean(returns) / downside_std * np.sqrt(252)
            
            # Max drawdown
            cumulative = np.cumsum(returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0.0
            
            # Volatility
            volatility = np.std(returns) * np.sqrt(252)
            
            # VaR and CVaR (95%)
            var_95 = np.percentile(returns, 5)
            cvar_95 = np.mean(returns[returns <= var_95]) if len(returns[returns <= var_95]) > 0 else 0.0
        else:
            sharpe = 0.0
            sortino = 0.0
            max_drawdown = 0.0
            volatility = 0.0
            var_95 = 0.0
            cvar_95 = 0.0
        
        # Correlation matrix (simplified)
        correlation_matrix = {}
        
        return PortfolioMetrics(
            total_value_usd=total_value,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            volatility=volatility,
            var_95=var_95,
            cvar_95=cvar_95,
            correlation_matrix=correlation_matrix,
            timestamp=time.time()
        )
    
    def get_positions_by_class(self, asset_class: AssetClass) -> List[Position]:
        """Get all positions for an asset class."""
        return [p for p in self._positions.values() if p.asset_class == asset_class]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get portfolio summary."""
        metrics = self.calculate_metrics()
        allocation = self.get_allocation_by_class()
        
        return {
            "total_value": metrics.total_value_usd,
            "total_pnl": metrics.total_pnl,
            "positions": len(self._positions),
            "allocation": {k.value: v for k, v in allocation.items()},
            "sharpe_ratio": metrics.sharpe_ratio,
            "max_drawdown": metrics.max_drawdown,
            "volatility": metrics.volatility
        }


class CrossVenueHedging:
    """Manages hedging across CEX, DEX, and chains."""
    
    def __init__(self):
        self._hedges: Dict[str, Dict[str, Any]] = {}
    
    def create_hedge(
        self,
        position_id: str,
        hedge_venue: str,
        hedge_symbol: str,
        hedge_quantity: float
    ) -> str:
        """Create a hedge for a position."""
        hedge_id = f"hedge_{int(time.time())}_{position_id}"
        
        self._hedges[hedge_id] = {
            "position_id": position_id,
            "venue": hedge_venue,
            "symbol": hedge_symbol,
            "quantity": hedge_quantity,
            "created_at": time.time()
        }
        
        logger.info(f"Created hedge: {hedge_quantity} {hedge_symbol} on {hedge_venue}")
        
        return hedge_id
    
    def remove_hedge(self, hedge_id: str) -> None:
        """Remove a hedge."""
        if hedge_id in self._hedges:
            del self._hedges[hedge_id]
            logger.info(f"Removed hedge: {hedge_id}")
    
    def get_hedges_for_position(self, position_id: str) -> List[Dict[str, Any]]:
        """Get all hedges for a position."""
        return [
            hedge for hedge in self._hedges.values()
            if hedge["position_id"] == position_id
        ]


class StrategyProposal:
    """Strategy proposal from swarm agents."""
    
    def __init__(
        self,
        strategy_id: str,
        proposing_agent: str,
        asset_classes: List[AssetClass],
        target_allocation: Dict[AssetClass, float],
        expected_return: float,
        expected_risk: float,
        rationale: str
    ):
        self.strategy_id = strategy_id
        self.proposing_agent = proposing_agent
        self.asset_classes = asset_classes
        self.target_allocation = target_allocation
        self.expected_return = expected_return
        self.expected_risk = expected_risk
        self.rationale = rationale
        self.timestamp = time.time()
        self.approved = False


class CrossDomainStrategyCoordinator:
    """Coordinates cross-domain strategies from swarm agents."""
    
    def __init__(self):
        self._proposals: List[StrategyProposal] = []
        self._active_strategies: Dict[str, StrategyProposal] = {}
        self._portfolio_engine = CrossAssetPortfolioEngine()
    
    def submit_proposal(self, proposal: StrategyProposal) -> None:
        """Submit a strategy proposal."""
        self._proposals.append(proposal)
        logger.info(
            f"Strategy proposal from {proposal.proposing_agent}: "
            f"{proposal.strategy_id} (return: {proposal.expected_return:.2%}, risk: {proposal.expected_risk:.2%})"
        )
    
    def approve_proposal(self, strategy_id: str) -> bool:
        """Approve a strategy proposal."""
        proposal = next((p for p in self._proposals if p.strategy_id == strategy_id), None)
        
        if not proposal:
            return False
        
        proposal.approved = True
        self._active_strategies[strategy_id] = proposal
        
        logger.info(f"Approved strategy: {strategy_id}")
        return True
    
    def allocate_capital(
        self,
        strategy_id: str,
        total_capital: float
    ) -> Dict[AssetClass, float]:
        """Allocate capital to a strategy."""
        if strategy_id not in self._active_strategies:
            return {}
        
        strategy = self._active_strategies[strategy_id]
        
        allocation = {}
        for asset_class, target_pct in strategy.target_allocation.items():
            allocation[asset_class] = total_capital * target_pct
        
        logger.info(f"Allocated ${total_capital} to strategy {strategy_id}")
        
        return allocation
    
    def get_pending_proposals(self) -> List[StrategyProposal]:
        """Get pending proposals."""
        return [p for p in self._proposals if not p.approved]
    
    def get_active_strategies(self) -> List[StrategyProposal]:
        """Get active strategies."""
        return list(self._active_strategies.values())


# Global instances
_portfolio_engine: Optional[CrossAssetPortfolioEngine] = None
_portfolio_engine_lock = threading.Lock()
_hedging_manager: Optional[CrossVenueHedging] = None
_hedging_manager_lock = threading.Lock()
_strategy_coordinator: Optional[CrossDomainStrategyCoordinator] = None
_strategy_coordinator_lock = threading.Lock()


def get_portfolio_engine() -> CrossAssetPortfolioEngine:
    """Get the global portfolio engine."""
    global _portfolio_engine
    if _portfolio_engine is None:
        with _portfolio_engine_lock:
            if _portfolio_engine is None:
                _portfolio_engine = CrossAssetPortfolioEngine()
    return _portfolio_engine


def get_hedging_manager() -> CrossVenueHedging:
    """Get the global hedging manager."""
    global _hedging_manager
    if _hedging_manager is None:
        with _hedging_manager_lock:
            if _hedging_manager is None:
                _hedging_manager = CrossVenueHedging()
    return _hedging_manager


def get_strategy_coordinator() -> CrossDomainStrategyCoordinator:
    """Get the global strategy coordinator."""
    global _strategy_coordinator
    if _strategy_coordinator is None:
        with _strategy_coordinator_lock:
            if _strategy_coordinator is None:
                _strategy_coordinator = CrossDomainStrategyCoordinator()
    return _strategy_coordinator
