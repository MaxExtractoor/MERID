"""
Kelly-VIX Backtest State and Publisher

State management and event publishing for Kelly-VIX backtest results.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class KellyVixBacktestState:
    """Kelly-VIX backtest state for real-time updates."""
    equity_curve: List[float]
    base_kelly: float
    hybrid_fraction: float
    final_capital: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    timestamp: float = field(default_factory=time.time)
    backtest_id: str = ""
    market_ticker: str = ""
    
    def to_event(self) -> Dict[str, Any]:
        """Convert to event payload for SSE streaming."""
        return {
            "type": "kelly_vix_backtest",
            "payload": {
                "equity_curve": self.equity_curve,
                "base_kelly": self.base_kelly,
                "hybrid_fraction": self.hybrid_fraction,
                "final_capital": self.final_capital,
                "total_return": self.total_return,
                "sharpe_ratio": self.sharpe_ratio,
                "max_drawdown": self.max_drawdown,
                "win_rate": self.win_rate,
                "num_trades": self.num_trades,
                "backtest_id": self.backtest_id,
                "market_ticker": self.market_ticker,
            },
            "ts": self.timestamp,
            "source": "kelly_vix_backtester",
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "equity_curve": self.equity_curve,
            "base_kelly": self.base_kelly,
            "hybrid_fraction": self.hybrid_fraction,
            "final_capital": self.final_capital,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "num_trades": self.num_trades,
            "timestamp": self.timestamp,
            "backtest_id": self.backtest_id,
            "market_ticker": self.market_ticker,
        }

# Global state
kelly_vix_state_current: Optional[KellyVixBacktestState] = None

class KellyVixBacktestManager:
    """Thread-safe manager for Kelly-VIX backtest state and history."""
    
    def __init__(self, max_history: int = 100):
        self._state: Optional[KellyVixBacktestState] = None
        self._history: List[KellyVixBacktestState] = []
        self._max_history = max_history
        self._update_count: int = 0
        self._last_updated: float = 0.0
    
    def update_state(self, state: KellyVixBacktestState) -> None:
        """
        Update current backtest state.
        
        Args:
            state: New backtest state
        """
        self._state = state
        self._last_updated = time.time()
        self._update_count += 1
        
        # Add to history
        self._history.append(state)
        
        # Limit history size
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        logger.info(f"Kelly-VIX backtest state updated: backtest_id={state.backtest_id}, "
                   f"return={state.total_return:.2%}, trades={state.num_trades}")
    
    def get_current_state(self) -> Optional[KellyVixBacktestState]:
        """
        Get current backtest state.
        
        Returns:
            Current state or None
        """
        return self._state
    
    def get_state_dict(self) -> Optional[Dict[str, Any]]:
        """
        Get current state as dictionary.
        
        Returns:
            State dictionary or None
        """
        if self._state is None:
            return None
        
        return self._state.to_dict()
    
    def is_available(self) -> bool:
        """
        Check if backtest state is available.
        
        Returns:
            True if state is available
        """
        return self._state is not None
    
    def get_age_seconds(self) -> float:
        """
        Get age of current state in seconds.
        
        Returns:
            Age in seconds
        """
        if self._last_updated == 0.0:
            return float('inf')
        
        return time.time() - self._last_updated
    
    def is_stale(self, max_age_seconds: float = 300) -> bool:
        """
        Check if state is stale.
        
        Args:
            max_age_seconds: Maximum age in seconds before considered stale
            
        Returns:
            True if state is stale
        """
        return self.get_age_seconds() > max_age_seconds
    
    def get_history(self, limit: int = 10) -> List[KellyVixBacktestState]:
        """
        Get recent backtest history.
        
        Args:
            limit: Number of recent states to return
            
        Returns:
            List of recent states
        """
        return self._history[-limit:] if self._history else []
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of backtest manager.
        
        Returns:
            Summary dictionary
        """
        summary = {
            "available": self.is_available(),
            "last_updated": self._last_updated,
            "age_seconds": self.get_age_seconds(),
            "update_count": self._update_count,
            "history_count": len(self._history),
            "is_stale": self.is_stale()
        }
        
        if self._state:
            summary["current_backtest_id"] = self._state.backtest_id
            summary["market_ticker"] = self._state.market_ticker
            summary["total_return"] = self._state.total_return
            summary["num_trades"] = self._state.num_trades
            summary["hybrid_fraction"] = self._state.hybrid_fraction
        
        return summary

# Global manager
_kelly_vix_manager = KellyVixBacktestManager()

def update_kelly_vix_state(state: KellyVixBacktestState) -> None:
    """
    Update global Kelly-VIX backtest state.
    
    Args:
        state: New backtest state
    """
    global kelly_vix_state_current
    kelly_vix_state_current = state
    _kelly_vix_manager.update_state(state)

def get_current_kelly_vix_state() -> Optional[KellyVixBacktestState]:
    """
    Get current Kelly-VIX backtest state from global store.
    
    Returns:
        Current state or None
    """
    return _kelly_vix_manager.get_current_state()

def get_kelly_vix_state_dict() -> Optional[Dict[str, Any]]:
    """
    Get current Kelly-VIX backtest state as dictionary.
    
    Returns:
        State dictionary or None
    """
    return _kelly_vix_manager.get_state_dict()

def are_kelly_vix_metrics_available() -> bool:
    """
    Check if Kelly-VIX backtest metrics are available.
    
    Returns:
        True if metrics are available
    """
    return _kelly_vix_manager.is_available()

def publish_kelly_vix_result(event_bus, equity: List[float], 
                           base_kelly: float, hybrid_fraction: float,
                           backtest_id: str = "", market_ticker: str = "",
                           additional_metrics: Dict[str, float] = None) -> None:
    """
    Publish Kelly-VIX backtest result to event bus.
    
    Args:
        event_bus: Event bus instance
        equity: Equity curve values
        base_kelly: Base Kelly fraction
        hybrid_fraction: Hybrid Kelly fraction
        backtest_id: Backtest identifier
        market_ticker: Market ticker used
        additional_metrics: Additional performance metrics
    """
    try:
        # Calculate basic metrics if not provided
        if not additional_metrics:
            additional_metrics = {}
        
        # Calculate returns
        if len(equity) > 1:
            total_return = (equity[-1] / equity[0]) - 1
            final_capital = equity[-1]
            
            # Calculate Sharpe ratio (simplified)
            returns = pd.Series(equity).pct_change().dropna()
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(365 * 24 * 4) if len(returns) > 1 and returns.std() > 0 else 0.0
            
            # Calculate max drawdown
            peak = pd.Series(equity).cummax()
            drawdown = (pd.Series(equity) - peak) / peak.replace(0, np.nan)
            max_drawdown = drawdown.min()
        else:
            total_return = 0.0
            final_capital = 1.0
            sharpe_ratio = 0.0
            max_drawdown = 0.0
        
        # Create state
        state = KellyVixBacktestState(
            equity_curve=equity,
            base_kelly=base_kelly,
            hybrid_fraction=hybrid_fraction,
            final_capital=final_capital,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=additional_metrics.get("win_rate", 0.0),
            num_trades=int(additional_metrics.get("num_trades", len(equity))),
            backtest_id=backtest_id,
            market_ticker=market_ticker
        )
        
        # Update global state
        update_kelly_vix_state(state)
        
        # Publish event
        from ..core.event_bus import KalshiEvent  # Import here to avoid circular imports
        
        event = KalshiEvent(
            type="kelly_vix_backtest",
            payload=state.to_event()["payload"],
            ts=state.timestamp,
            source="kelly_vix_backtester",
        )
        
        event_bus.publish(event)
        
        logger.info(f"Kelly-VIX backtest result published: backtest_id={backtest_id}, "
                   f"return={total_return:.2%}, trades={state.num_trades}")
        
    except ImportError:
        logger.warning("Event bus not available - result not published")
    except Exception as e:
        logger.error(f"Error publishing Kelly-VIX result: {e}")

def get_kelly_vix_manager() -> KellyVixBacktestManager:
    """
    Get the Kelly-VIX backtest manager instance.
    
    Returns:
        KellyVixBacktestManager instance
    """
    return _kelly_vix_manager

# Example usage for backtest runner:
"""
import numpy as np
import pandas as pd

# Assume you have an event bus instance
from merid.core.event_bus import KalshiEventBus
event_bus = KalshiEventBus()

# After running a Kelly-VIX backtest:
np.random.seed(42)
equity = (1 + np.random.normal(0.001, 0.02, 100)).cumprod().tolist()
base_kelly = 0.15
hybrid_fraction = 0.12

# Additional metrics from backtest
additional_metrics = {
    "win_rate": 0.55,
    "num_trades": 100
}

# Publish result
publish_kelly_vix_result(
    event_bus, equity, base_kelly, hybrid_fraction,
    backtest_id="backtest_001",
    market_ticker="KXBTC15M-EXAMPLE",
    additional_metrics=additional_metrics
)

# The result will be available via:
# 1. Global state: get_current_kelly_vix_state()
# 2. API endpoints: get_kelly_vix_state_dict()
# 3. Event bus: SSE streaming
"""
