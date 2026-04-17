"""
VIX-Kelly State Management - Production FastAPI Endpoint

Production state management for real-time VIX-Kelly sizing.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class VixKellyState:
    """VIX-Kelly sizing state for production trading."""
    base_kelly: float
    hybrid_fraction: float
    vix_value: float
    vix_rank: float
    timestamp: float = field(default_factory=time.time)
    vix_lookback: int = 252
    low_vol_boost: float = 1.2
    high_vol_cut: float = 0.5
    max_fraction: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "base_kelly": self.base_kelly,
            "hybrid_fraction": self.hybrid_fraction,
            "vix_value": self.vix_value,
            "vix_rank": self.vix_rank,
            "timestamp": self.timestamp,
            "vix_lookback": self.vix_lookback,
            "low_vol_boost": self.low_vol_boost,
            "high_vol_cut": self.high_vol_cut,
            "max_fraction": self.max_fraction,
            "age_seconds": time.time() - self.timestamp
        }

# Global state
current_vix_kelly: Optional[VixKellyState] = None

class VixKellyStateManager:
    """Thread-safe VIX-Kelly state manager for production."""
    
    def __init__(self):
        self._state: Optional[VixKellyState] = None
        self._last_updated: float = 0.0
        self._update_count: int = 0
        self._update_history: list = []
        self._max_history = 100  # Keep last 100 updates
    
    def update_state(self, state: VixKellyState) -> None:
        """
        Update VIX-Kelly state.
        
        Args:
            state: New VIX-Kelly state
        """
        self._state = state
        self._last_updated = time.time()
        self._update_count += 1
        
        # Add to history
        self._update_history.append({
            "timestamp": state.timestamp,
            "base_kelly": state.base_kelly,
            "hybrid_fraction": state.hybrid_fraction,
            "vix_value": state.vix_value,
            "vix_rank": state.vix_rank
        })
        
        # Limit history size
        if len(self._update_history) > self._max_history:
            self._update_history = self._update_history[-self._max_history:]
        
        logger.info(f"VIX-Kelly state updated: base={state.base_kelly:.3f}, "
                   f"hybrid={state.hybrid_fraction:.3f}, vix={state.vix_value:.2f}, "
                   f"rank={state.vix_rank:.3f}")
    
    def get_state(self) -> Optional[VixKellyState]:
        """
        Get current VIX-Kelly state.
        
        Returns:
            Current VIX-Kelly state or None
        """
        return self._state
    
    def get_state_dict(self) -> Optional[Dict[str, Any]]:
        """
        Get current VIX-Kelly state as dictionary.
        
        Returns:
            VIX-Kelly state dictionary or None
        """
        if self._state is None:
            return None
        
        return self._state.to_dict()
    
    def is_available(self) -> bool:
        """
        Check if VIX-Kelly state is available.
        
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
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of VIX-Kelly state manager.
        
        Returns:
            State manager summary
        """
        summary = {
            "available": self.is_available(),
            "last_updated": self._last_updated,
            "age_seconds": self.get_age_seconds(),
            "update_count": self._update_count,
            "is_stale": self.is_stale(),
            "history_count": len(self._update_history)
        }
        
        if self._state:
            summary["current_vix"] = self._state.vix_value
            summary["current_rank"] = self._state.vix_rank
            summary["hybrid_fraction"] = self._state.hybrid_fraction
            summary["volatility_regime"] = self._get_volatility_regime()
        
        return summary
    
    def _get_volatility_regime(self) -> str:
        """Get volatility regime based on VIX rank."""
        if self._state is None:
            return "unknown"
        
        rank = self._state.vix_rank
        
        if rank < 0.2:
            return "low"
        elif rank < 0.4:
            return "normal"
        elif rank < 0.7:
            return "high"
        else:
            return "extreme"
    
    def get_recent_history(self, limit: int = 10) -> list:
        """
        Get recent update history.
        
        Args:
            limit: Number of recent updates to return
            
        Returns:
            List of recent state updates
        """
        return self._update_history[-limit:] if self._update_history else []
    
    def get_state_trend(self, window_minutes: int = 60) -> Dict[str, Any]:
        """
        Analyze state trend over recent window.
        
        Args:
            window_minutes: Time window in minutes
            
        Returns:
            Trend analysis
        """
        if not self._update_history:
            return {"error": "No history available"}
        
        # Filter recent history
        cutoff_time = time.time() - (window_minutes * 60)
        recent_updates = [u for u in self._update_history if u["timestamp"] >= cutoff_time]
        
        if len(recent_updates) < 2:
            return {"error": "Insufficient recent data"}
        
        # Calculate trends
        hybrid_fractions = [u["hybrid_fraction"] for u in recent_updates]
        vix_values = [u["vix_value"] for u in recent_updates]
        vix_ranks = [u["vix_rank"] for u in recent_updates]
        
        return {
            "window_minutes": window_minutes,
            "updates_in_window": len(recent_updates),
            "hybrid_fraction_trend": {
                "start": hybrid_fractions[0],
                "end": hybrid_fractions[-1],
                "change": hybrid_fractions[-1] - hybrid_fractions[0],
                "direction": "increasing" if hybrid_fractions[-1] > hybrid_fractions[0] else "decreasing"
            },
            "vix_trend": {
                "start": vix_values[0],
                "end": vix_values[-1],
                "change": vix_values[-1] - vix_values[0],
                "direction": "increasing" if vix_values[-1] > vix_values[0] else "decreasing"
            },
            "rank_trend": {
                "start": vix_ranks[0],
                "end": vix_ranks[-1],
                "change": vix_ranks[-1] - vix_ranks[0],
                "direction": "increasing" if vix_ranks[-1] > vix_ranks[0] else "decreasing"
            }
        }

# Global instance
_vix_kelly_manager = VixKellyStateManager()

def update_vix_kelly_state(state: VixKellyState) -> None:
    """
    Update global VIX-Kelly state.
    
    Args:
        state: New VIX-Kelly state
    """
    global current_vix_kelly
    current_vix_kelly = state
    _vix_kelly_manager.update_state(state)

def get_current_vix_kelly_state() -> Optional[VixKellyState]:
    """
    Get current VIX-Kelly state from global store.
    
    Returns:
        Current VIX-Kelly state or None
    """
    return _vix_kelly_manager.get_state()

def get_vix_kelly_state_dict() -> Optional[Dict[str, Any]]:
    """
    Get current VIX-Kelly state as dictionary.
    
    Returns:
        VIX-Kelly state dictionary or None
    """
    return _vix_kelly_manager.get_state_dict()

def are_vix_kelly_metrics_available() -> bool:
    """
    Check if VIX-Kelly metrics are available.
    
    Returns:
        True if metrics are available
    """
    return _vix_kelly_manager.is_available()

def refresh_vix_kelly(base_kelly: float,
                       vix_lookback: int = 252,
                       low_vol_boost: float = 1.2,
                       high_vol_cut: float = 0.5,
                       max_fraction: float = None) -> bool:
    """
    Refresh VIX-Kelly state with latest VIX data.
    
    Args:
        base_kelly: Base Kelly fraction
        vix_lookback: Lookback period for VIX rank
        low_vol_boost: Low volatility boost factor
        high_vol_cut: High volatility cut factor
        max_fraction: Maximum allowed fraction
        
    Returns:
        True if update successful
    """
    try:
        # Fetch VIX data
        from .vix_data import fetch_vix_with_fallback
        vix_data = fetch_vix_with_fallback()
        
        if vix_data.empty:
            logger.error("Failed to fetch VIX data")
            return False
        
        # Calculate VIX rank
        from .kelly_vix_hybrid import vix_rank, hybrid_kelly_fraction
        vr = vix_rank(vix_data, lookback=vix_lookback)
        
        # Calculate hybrid fraction
        f_hybrid = hybrid_kelly_fraction(
            base_kelly, vix_data, lookback=vix_lookback,
            low_vol_boost=low_vol_boost, high_vol_cut=high_vol_cut,
            max_fraction=max_fraction
        )
        
        # Create and update state
        state = VixKellyState(
            base_kelly=base_kelly,
            hybrid_fraction=f_hybrid,
            vix_value=vix_data.iloc[-1],
            vix_rank=vr,
            vix_lookback=vix_lookback,
            low_vol_boost=low_vol_boost,
            high_vol_cut=high_vol_cut,
            max_fraction=max_fraction
        )
        
        update_vix_kelly_state(state)
        
        logger.info(f"VIX-Kelly state refreshed: hybrid={f_hybrid:.3f}, vix={vix_data.iloc[-1]:.2f}, rank={vr:.3f}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error refreshing VIX-Kelly state: {e}")
        return False

def publish_vix_kelly_event(event_bus, state: VixKellyState) -> None:
    """
    Publish VIX-Kelly state as event on event bus.
    
    Args:
        event_bus: Event bus instance
        state: VIX-Kelly state to publish
    """
    try:
        from ..core.event_bus import KalshiEvent  # Import here to avoid circular imports
        
        event = KalshiEvent(
            type="vix_kelly_sizing",
            payload=state.to_dict(),
            ts=time.time(),
            source="vix_kelly_manager"
        )
        
        event_bus.publish(event)
        logger.info("VIX-Kelly state event published")
        
    except ImportError:
        logger.warning("Event bus not available - state not published")
    except Exception as e:
        logger.error(f"Error publishing VIX-Kelly event: {e}")

def get_vix_kelly_manager() -> VixKellyStateManager:
    """
    Get the VIX-Kelly state manager instance.
    
    Returns:
        VixKellyStateManager instance
    """
    return _vix_kelly_manager

# Example usage for background job:
"""
import schedule
import time

def periodic_vix_kelly_update():
    '''Background job to periodically update VIX-Kelly sizing.'''
    try:
        success = refresh_vix_kelly(base_kelly=0.15)
        
        if success:
            # Publish event if event bus available
            state = get_current_vix_kelly_state()
            if state and event_bus:
                publish_vix_kelly_event(event_bus, state)
                
    except Exception as e:
        logger.error(f"Error in periodic VIX-Kelly update: {e}")

# Schedule this job to run periodically (e.g., every hour)
schedule.every(1).hours.do(periodic_vix_kelly_update)

# Keep the scheduler running
while True:
    schedule.run_pending()
    time.sleep(60)  # Check every minute
"""
