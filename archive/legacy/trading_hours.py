"""Kalshi Trading Hours Guard — Enforces Kalshi market hours and maintenance windows.

Kalshi trading hours:
- Generally 24/7 for crypto markets
- Scheduled maintenance: Configured via SessionConfig from agent grid YAML

This guard ensures:
- Live orders are blocked during maintenance windows
- Paper trading continues uninterrupted during maintenance
- Clear logging and events for operator visibility
"""

from datetime import datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from utils.logger import get_logger

logger = get_logger("merid.guard.trading_hours")

# Kalshi operates on Eastern Time
ET = ZoneInfo("America/New_York")


class KalshiTradingHoursGuard:
    """Enforces Kalshi trading hours and maintenance windows.

    Usage:
        from merid.prediction.agent_grid_config import SessionConfig
        config = SessionConfig(maintenance_day=3, maintenance_start_et="03:00", maintenance_end_et="05:00")
        guard = KalshiTradingHoursGuard(config)

        # Check if live trading allowed
        if guard.is_live_trading_allowed():
            place_live_order()
        else:
            # Fallback to paper or reject
            log_maintenance_window()
    """

    def __init__(self, session_config):
        """Initialize with SessionConfig from agent grid YAML.

        Args:
            session_config: SessionConfig object with maintenance window settings (required).
                           This ensures single source of truth for maintenance window configuration.

        Raises:
            ValueError: If session_config is None or missing required fields.
        """
        if session_config is None:
            raise ValueError(
                "KalshiTradingHoursGuard requires SessionConfig from agent grid YAML. "
                "Hardcoded maintenance window values have been removed to ensure single source of truth. "
                "Pass SessionConfig(maintenance_day, maintenance_start_et, maintenance_end_et)."
            )

        self._maintenance_day = session_config.maintenance_day
        # Parse "HH:MM" format to time objects
        start_parts = session_config.maintenance_start_et.split(":")
        self._maintenance_start = time(int(start_parts[0]), int(start_parts[1]))
        end_parts = session_config.maintenance_end_et.split(":")
        self._maintenance_end = time(int(end_parts[0]), int(end_parts[1]))
    
    def get_current_et_time(self) -> datetime:
        """Get current time in Eastern Time."""
        return datetime.now(ET)
    
    def is_in_maintenance_window(self, dt: Optional[datetime] = None) -> bool:
        """Check if given time (or now) falls within Thursday maintenance window.
        
        Args:
            dt: Time to check (defaults to current ET time)
        
        Returns:
            True if in maintenance window (Thu 3-5am ET)
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        # Ensure we're working in ET
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        else:
            dt = dt.astimezone(ET)
        
        # Check if it's Thursday
        if dt.weekday() != self._maintenance_day:
            return False
        
        # Check if time falls within maintenance window
        current_time = dt.time()
        return self._maintenance_start <= current_time < self._maintenance_end
    
    def is_live_trading_allowed(self, dt: Optional[datetime] = None) -> bool:
        """Check if live trading is currently allowed.
        
        Live trading is blocked during:
        - Thursday 3:00–5:00 AM ET (scheduled maintenance)
        
        Args:
            dt: Time to check (defaults to current ET time)
        
        Returns:
            True if live trading is permitted
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        in_maintenance = self.is_in_maintenance_window(dt)
        
        if in_maintenance:
            logger.warning(
                "Live trading blocked: Kalshi maintenance window active",
                extra={
                    "window": "Thursday 3:00-5:00 AM ET",
                    "current_time_et": dt.isoformat(),
                    "reason": "maintenance_window_active",
                }
            )
            return False
        
        return True
    
    def check_order_allowed(self, is_live: bool, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Check if an order is allowed and provide reason.
        
        Args:
            is_live: True if live order, False if paper
            dt: Time to check (defaults to current ET time)
        
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        in_maintenance = self.is_in_maintenance_window(dt)
        
        if not in_maintenance:
            return True, "trading_allowed"
        
        # In maintenance window
        if is_live:
            return False, "maintenance_window_active"
        else:
            # Paper trading allowed during maintenance
            return True, "paper_trading_during_maintenance"
    
    def get_time_until_maintenance_end(self, dt: Optional[datetime] = None) -> Optional[float]:
        """Get seconds until current or next maintenance window ends.
        
        Args:
            dt: Time to check (defaults to current ET time)
        
        Returns:
            Seconds until maintenance ends, or None if not in maintenance
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        if not self.is_in_maintenance_window(dt):
            return None
        
        # Calculate time until 5:00 AM
        end_dt = dt.replace(hour=5, minute=0, second=0, microsecond=0)
        delta = end_dt - dt
        return max(0.0, delta.total_seconds())
    
    def get_next_maintenance_window(self, dt: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """Get the next scheduled maintenance window.
        
        Args:
            dt: Starting time (defaults to current ET time)
        
        Returns:
            Tuple of (start_datetime, end_datetime) in ET
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        # Ensure ET
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        else:
            dt = dt.astimezone(ET)
        
        # Find next Thursday
        days_until_thursday = (self._maintenance_day - dt.weekday()) % 7
        if days_until_thursday == 0 and dt.time() >= self._maintenance_end:
            # We're past today's maintenance, go to next week
            days_until_thursday = 7
        
        next_thursday = dt + __import__('datetime').timedelta(days=days_until_thursday)
        start = next_thursday.replace(hour=3, minute=0, second=0, microsecond=0)
        end = next_thursday.replace(hour=5, minute=0, second=0, microsecond=0)
        
        return start, end


# Singleton instance
_guard: Optional[KalshiTradingHoursGuard] = None


def get_trading_hours_guard() -> KalshiTradingHoursGuard:
    """Get the singleton trading hours guard.

    Loads SessionConfig from agent grid YAML to ensure single source of truth
    for maintenance window configuration.
    """
    global _guard
    if _guard is None:
        from merid.prediction.agent_grid_config import load_agent_grid_config
        config = load_agent_grid_config()
        _guard = KalshiTradingHoursGuard(config.session)
    return _guard


def is_live_trading_allowed(dt: Optional[datetime] = None) -> bool:
    """Convenience function to check if live trading is allowed."""
    return get_trading_hours_guard().is_live_trading_allowed(dt)
