"""
Kelly MVRK Metrics Store for FastAPI Integration

Store and expose multivariate Kelly/MVRK metrics via API.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class KellyMVRKMetrics:
    """Multivariate Kelly and MVRK metrics data structure."""
    assets: List[str]
    kelly_weights: List[float]
    mvrk_weights: List[float]
    theta_used: float
    ruin_kelly: float
    ruin_mvrk: float
    sharpe_kelly: float
    sharpe_mvrk: float
    max_dd_kelly: float
    max_dd_mvrk: float
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "assets": self.assets,
            "kelly_weights": self.kelly_weights,
            "mvrk_weights": self.mvrk_weights,
            "theta_used": self.theta_used,
            "ruin_kelly": self.ruin_kelly,
            "ruin_mvrk": self.ruin_mvrk,
            "sharpe_kelly": self.sharpe_kelly,
            "sharpe_mvrk": self.sharpe_mvrk,
            "max_dd_kelly": self.max_dd_kelly,
            "max_dd_mvrk": self.max_dd_mvrk,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KellyMVRKMetrics':
        """Create KellyMVRKMetrics from dictionary."""
        return cls(
            assets=data.get("assets", []),
            kelly_weights=data.get("kelly_weights", []),
            mvrk_weights=data.get("mvrk_weights", []),
            theta_used=data.get("theta_used", 0.0),
            ruin_kelly=data.get("ruin_kelly", 0.0),
            ruin_mvrk=data.get("ruin_mvrk", 0.0),
            sharpe_kelly=data.get("sharpe_kelly", 0.0),
            sharpe_mvrk=data.get("sharpe_mvrk", 0.0),
            max_dd_kelly=data.get("max_dd_kelly", 0.0),
            max_dd_mvrk=data.get("max_dd_mvrk", 0.0),
            timestamp=data.get("timestamp", time.time())
        )

# Global in-memory store
kelly_mvrk_metrics_current: Optional[KellyMVRKMetrics] = None

class KellyMVRKStore:
    """Thread-safe Kelly/MVRK metrics store for MERID."""
    
    def __init__(self):
        self._metrics: Optional[KellyMVRKMetrics] = None
        self._last_updated: float = 0.0
        self._update_count: int = 0
    
    def update_metrics(self, metrics: KellyMVRKMetrics) -> None:
        """
        Update stored Kelly/MVRK metrics.
        
        Args:
            metrics: New Kelly/MVRK metrics to store
        """
        self._metrics = metrics
        self._last_updated = time.time()
        self._update_count += 1
        
        logger.info(f"Kelly/MVRK metrics updated: {len(metrics.assets)} assets, "
                   f"theta={metrics.theta_used:.2f}, sharpe_kelly={metrics.sharpe_kelly:.2f}, "
                   f"sharpe_mvrk={metrics.sharpe_mvrk:.2f}")
    
    def get_metrics(self) -> Optional[KellyMVRKMetrics]:
        """
        Get current Kelly/MVRK metrics.
        
        Returns:
            Current Kelly/MVRK metrics or None if not available
        """
        return self._metrics
    
    def get_metrics_dict(self) -> Optional[Dict[str, Any]]:
        """
        Get current Kelly/MVRK metrics as dictionary.
        
        Returns:
            Kelly/MVRK metrics dictionary or None if not available
        """
        if self._metrics is None:
            return None
        
        return self._metrics.to_dict()
    
    def is_available(self) -> bool:
        """
        Check if Kelly/MVRK metrics are available.
        
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
        Get summary of Kelly/MVRK metrics store.
        
        Returns:
            Store summary
        """
        summary = {
            "available": self.is_available(),
            "last_updated": self._last_updated,
            "age_seconds": self.get_age_seconds(),
            "update_count": self._update_count,
            "is_stale": self.is_stale()
        }
        
        if self._metrics:
            summary["assets"] = len(self._metrics.assets)
            summary["theta_used"] = self._metrics.theta_used
            summary["mvrk_better"] = self._metrics.sharpe_mvrk > self._metrics.sharpe_kelly
        
        return summary

# Global instance
_kelly_mvrk_store = KellyMVRKStore()

def update_kelly_mvrk_metrics(metrics: KellyMVRKMetrics) -> None:
    """
    Update global Kelly/MVRK metrics store.
    
    Args:
        metrics: Kelly/MVRK metrics to store
    """
    global kelly_mvrk_metrics_current
    kelly_mvrk_metrics_current = metrics
    _kelly_mvrk_store.update_metrics(metrics)

def get_current_kelly_mvrk_metrics() -> Optional[KellyMVRKMetrics]:
    """
    Get current Kelly/MVRK metrics from global store.
    
    Returns:
        Current Kelly/MVRK metrics or None
    """
    return _kelly_mvrk_store.get_metrics()

def get_kelly_mvrk_metrics_dict() -> Optional[Dict[str, Any]]:
    """
    Get current Kelly/MVRK metrics as dictionary.
    
    Returns:
        Kelly/MVRK metrics dictionary or None
    """
    return _kelly_mvrk_store.get_metrics_dict()

def are_kelly_mvrk_metrics_available() -> bool:
    """
    Check if Kelly/MVRK metrics are available.
    
    Returns:
        True if metrics are available
    """
    return _kelly_mvrk_store.is_available()

def publish_kelly_mvrk_metrics_event(event_bus, metrics: KellyMVRKMetrics) -> None:
    """
    Publish Kelly/MVRK metrics as event on event bus.
    
    Args:
        event_bus: Event bus instance
        metrics: Kelly/MVRK metrics to publish
    """
    try:
        from ..core.event_bus import KalshiEvent  # Import here to avoid circular imports
        
        event = KalshiEvent(
            type="kelly_mvrk",
            payload=metrics.to_dict(),
            ts=time.time(),
            source="kelly_mvrk_backtest"
        )
        
        event_bus.publish(event)
        logger.info("Kelly/MVRK metrics event published")
        
    except ImportError:
        logger.warning("Event bus not available - metrics not published")
    except Exception as e:
        logger.error(f"Error publishing Kelly/MVRK metrics event: {e}")

def calculate_kelly_mvrk_metrics_from_backtest(backtest_results, theta: float = 1.0) -> KellyMVRKMetrics:
    """
    Calculate Kelly/MVRK metrics from backtest results.
    
    Args:
        backtest_results: Backtest results with returns and weights
        theta: Theta value used for MVRK
        
    Returns:
        KellyMVRKMetrics object
    """
    # Extract data from backtest results
    if not hasattr(backtest_results, 'returns_df') or not hasattr(backtest_results, 'kelly_weights'):
        logger.error("Backtest results missing required data")
        return KellyMVRKMetrics([], [], [], theta, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    
    returns_df = backtest_results.returns_df
    kelly_weights = backtest_results.kelly_weights
    mvrk_weights = backtest_results.mvrk_weights
    
    # Calculate performance metrics
    def calculate_portfolio_metrics(weights):
        port_rets = returns_df.values @ weights
        equity = (1 + port_rets).cumprod()
        
        # Sharpe ratio
        returns = equity.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(365)  # Daily to annual
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
        
        return sharpe, max_dd
    
    sharpe_kelly, max_dd_kelly = calculate_portfolio_metrics(kelly_weights)
    sharpe_mvrk, max_dd_mvrk = calculate_portfolio_metrics(mvrk_weights)
    
    # Calculate risk of ruin (simplified)
    def calculate_risk_of_ruin(weights):
        port_rets = returns_df.values @ weights
        equity = (1 + port_rets).cumprod()
        # Simple ruin probability: probability equity falls below 50% at any point
        ruin_prob = (equity < 0.5).mean()
        return ruin_prob
    
    ruin_kelly = calculate_risk_of_ruin(kelly_weights)
    ruin_mvrk = calculate_risk_of_ruin(mvrk_weights)
    
    return KellyMVRKMetrics(
        assets=list(returns_df.columns),
        kelly_weights=kelly_weights.tolist(),
        mvrk_weights=mvrk_weights.tolist(),
        theta_used=theta,
        ruin_kelly=ruin_kelly,
        ruin_mvrk=ruin_mvrk,
        sharpe_kelly=sharpe_kelly,
        sharpe_mvrk=sharpe_mvrk,
        max_dd_kelly=max_dd_kelly,
        max_dd_mvrk=max_dd_mvrk
    )

def generate_sample_kelly_mvrk_metrics() -> KellyMVRKMetrics:
    """
    Generate sample Kelly/MVRK metrics for testing.
    
    Returns:
        Sample KellyMVRKMetrics object
    """
    return KellyMVRKMetrics(
        assets=["BTC", "ETH"],
        kelly_weights=[0.6, 0.4],
        mvrk_weights=[0.45, 0.35],
        theta_used=1.0,
        ruin_kelly=0.12,
        ruin_mvrk=0.08,
        sharpe_kelly=1.35,
        sharpe_mvrk=1.58,
        max_dd_kelly=-0.22,
        max_dd_mvrk=-0.18
    )

# Example usage for background job:
"""
def periodic_kelly_mvrk_update():
    '''Background job to periodically update Kelly/MVRK metrics.'''
    try:
        # Run backtest or load results
        backtest_results = run_latest_kelly_mvrk_backtest()
        
        # Calculate metrics
        metrics = calculate_kelly_mvrk_metrics_from_backtest(backtest_results, theta=1.0)
        
        # Update store
        update_kelly_mvrk_metrics(metrics)
        
        # Publish event if event bus available
        if event_bus:
            publish_kelly_mvrk_metrics_event(event_bus, metrics)
            
    except Exception as e:
        logger.error(f"Error in periodic Kelly/MVRK update: {e}")

# Schedule this job to run periodically (e.g., every hour)
import schedule
schedule.every(1).hours.do(periodic_kelly_mvrk_update)
"""
