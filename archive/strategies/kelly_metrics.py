"""
Kelly Metrics Store for MERID

In-memory store for latest Kelly metrics and FastAPI integration.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class KellyMetrics:
    """Kelly metrics data structure."""
    fraction_full: float
    fraction_half: float
    fraction_quarter: float
    vol_targeted_fraction: float
    sharpe: float
    max_drawdown: float
    total_return: float
    win_rate: float
    win_loss_ratio: float
    total_trades: int
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "fraction_full": self.fraction_full,
            "fraction_half": self.fraction_half,
            "fraction_quarter": self.fraction_quarter,
            "vol_targeted_fraction": self.vol_targeted_fraction,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "total_return": self.total_return,
            "win_rate": self.win_rate,
            "win_loss_ratio": self.win_loss_ratio,
            "total_trades": self.total_trades,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KellyMetrics':
        """Create KellyMetrics from dictionary."""
        return cls(
            fraction_full=data.get("fraction_full", 0.0),
            fraction_half=data.get("fraction_half", 0.0),
            fraction_quarter=data.get("fraction_quarter", 0.0),
            vol_targeted_fraction=data.get("vol_targeted_fraction", 0.0),
            sharpe=data.get("sharpe", 0.0),
            max_drawdown=data.get("max_drawdown", 0.0),
            total_return=data.get("total_return", 0.0),
            win_rate=data.get("win_rate", 0.0),
            win_loss_ratio=data.get("win_loss_ratio", 0.0),
            total_trades=data.get("total_trades", 0),
            timestamp=data.get("timestamp", time.time())
        )

# Global in-memory store
kelly_metrics_current: Optional[KellyMetrics] = None

class KellyMetricsStore:
    """Thread-safe Kelly metrics store for MERID."""
    
    def __init__(self):
        self._metrics: Optional[KellyMetrics] = None
        self._last_updated: float = 0.0
        self._update_count: int = 0
    
    def update_metrics(self, metrics: KellyMetrics) -> None:
        """
        Update stored Kelly metrics.
        
        Args:
            metrics: New Kelly metrics to store
        """
        self._metrics = metrics
        self._last_updated = time.time()
        self._update_count += 1
        
        logger.info(f"Kelly metrics updated: f_full={metrics.fraction_full:.3f}, "
                   f"sharpe={metrics.sharpe:.2f}, trades={metrics.total_trades}")
    
    def get_metrics(self) -> Optional[KellyMetrics]:
        """
        Get current Kelly metrics.
        
        Returns:
            Current Kelly metrics or None if not available
        """
        return self._metrics
    
    def get_metrics_dict(self) -> Optional[Dict[str, Any]]:
        """
        Get current Kelly metrics as dictionary.
        
        Returns:
            Kelly metrics dictionary or None if not available
        """
        if self._metrics is None:
            return None
        
        return self._metrics.to_dict()
    
    def is_available(self) -> bool:
        """
        Check if Kelly metrics are available.
        
        Returns:
            True if metrics are available
        """
        return self._metrics is not None
    
    def get_age_seconds(self) -> float:
        """
        Get age of current metrics in seconds.
        
        Returns:
            Age in seconds
        """
        if self._last_updated == 0.0:
            return float('inf')
        
        return time.time() - self._last_updated
    
    def is_stale(self, max_age_seconds: float = 300) -> bool:
        """
        Check if metrics are stale.
        
        Args:
            max_age_seconds: Maximum age in seconds before considered stale
            
        Returns:
            True if metrics are stale
        """
        return self.get_age_seconds() > max_age_seconds
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of Kelly metrics store.
        
        Returns:
            Store summary
        """
        return {
            "available": self.is_available(),
            "last_updated": self._last_updated,
            "age_seconds": self.get_age_seconds(),
            "update_count": self._update_count,
            "is_stale": self.is_stale()
        }

# Global instance
_kelly_store = KellyMetricsStore()

def update_kelly_metrics(metrics: KellyMetrics) -> None:
    """
    Update global Kelly metrics store.
    
    Args:
        metrics: Kelly metrics to store
    """
    global kelly_metrics_current
    kelly_metrics_current = metrics
    _kelly_store.update_metrics(metrics)

def get_current_kelly_metrics() -> Optional[KellyMetrics]:
    """
    Get current Kelly metrics from global store.
    
    Returns:
        Current Kelly metrics or None
    """
    return _kelly_store.get_metrics()

def get_kelly_metrics_dict() -> Optional[Dict[str, Any]]:
    """
    Get current Kelly metrics as dictionary.
    
    Returns:
        Kelly metrics dictionary or None
    """
    return _kelly_store.get_metrics_dict()

def are_kelly_metrics_available() -> bool:
    """
    Check if Kelly metrics are available.
    
    Returns:
        True if metrics are available
    """
    return _kelly_store.is_available()

def publish_kelly_metrics_event(event_bus, metrics: KellyMetrics) -> None:
    """
    Publish Kelly metrics as event on event bus.
    
    Args:
        event_bus: Event bus instance
        metrics: Kelly metrics to publish
    """
    try:
        from ..core.event_bus import KalshiEvent  # Import here to avoid circular imports
        
        event = KalshiEvent(
            type="kelly_metrics",
            payload=metrics.to_dict(),
            ts=time.time(),
            source="kelly_backtest"
        )
        
        event_bus.publish(event)
        logger.info("Kelly metrics event published")
        
    except ImportError:
        logger.warning("Event bus not available - metrics not published")
    except Exception as e:
        logger.error(f"Error publishing Kelly metrics event: {e}")

def calculate_kelly_metrics_from_backtest(backtest_results) -> KellyMetrics:
    """
    Calculate Kelly metrics from backtest results.
    
    Args:
        backtest_results: Backtest results with trades and performance
        
    Returns:
        KellyMetrics object
    """
    # Extract trade PnLs
    trade_pnls = [t.pnl for t in backtest_results.trades]
    
    if not trade_pnls:
        logger.warning("No trades in backtest results")
        return KellyMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    
    # Calculate basic statistics
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p <= 0]
    
    win_rate = len(wins) / len(trade_pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Calculate Kelly fractions
    from .kelly import KellyStats, kelly_fraction
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_full = kelly_fraction(ks)
    
    # Calculate performance metrics
    equity = backtest_results.equity_curve
    if not equity.empty:
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
        
        # Sharpe ratio
        returns = equity.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            periods_per_year = 365 * 24 * 4  # 15m bars
            sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
    else:
        total_return = 0.0
        sharpe = 0.0
        max_dd = 0.0
    
    # Calculate volatility-targeted fraction (simplified)
    vol_targeted_fraction = 0.5 * f_full  # Simplified - use half Kelly as baseline
    
    return KellyMetrics(
        fraction_full=f_full,
        fraction_half=0.5 * f_full,
        fraction_quarter=0.25 * f_full,
        vol_targeted_fraction=vol_targeted_fraction,
        sharpe=sharpe,
        max_drawdown=max_dd,
        total_return=total_return,
        win_rate=win_rate,
        win_loss_ratio=win_loss_ratio,
        total_trades=len(trade_pnls)
    )

# Example usage for background job:
"""
def periodic_kelly_update():
    '''Background job to periodically update Kelly metrics.'''
    try:
        # Run backtest or load results
        backtest_results = run_latest_backtest()
        
        # Calculate metrics
        metrics = calculate_kelly_metrics_from_backtest(backtest_results)
        
        # Update store
        update_kelly_metrics(metrics)
        
        # Publish event if event bus available
        if event_bus:
            publish_kelly_metrics_event(event_bus, metrics)
            
    except Exception as e:
        logger.error(f"Error in periodic Kelly update: {e}")

# Schedule this job to run periodically (e.g., every hour)
import schedule
schedule.every(1).hours.do(periodic_kelly_update)
"""
