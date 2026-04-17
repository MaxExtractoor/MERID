"""Kalshi Session Guard — Trading hours and maintenance window enforcement.

Kalshi is 24/7 except a weekly maintenance window (Thu 3–5 AM ET).
This module provides a guard that agents check before placing orders.
"""

from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import Optional

from merid.prediction.agent_grid_config import SessionConfig
from utils.logger import get_logger
import threading

logger = get_logger("merid.prediction.session_guard")

# US Eastern timezone offset (UTC-5 standard, UTC-4 DST)
_ET_OFFSET_STANDARD = timedelta(hours=-5)
_ET_OFFSET_DST = timedelta(hours=-4)


def _is_us_dst(dt_utc: datetime) -> bool:
    """Approximate US DST check (2nd Sun Mar – 1st Sun Nov).
    
    DST starts at 2:00 AM local time (7:00 AM UTC) on 2nd Sunday of March.
    DST ends at 2:00 AM local time (6:00 AM UTC) on 1st Sunday of November.
    """
    year = dt_utc.year
    # 2nd Sunday of March
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    days_to_first_sun_mar = (6 - mar1.weekday()) % 7
    second_sun_mar = mar1 + timedelta(days=days_to_first_sun_mar + 7)
    # DST starts at 2:00 AM ET = 7:00 AM UTC (when not in DST yet, ET = UTC-5)
    dst_start = second_sun_mar + timedelta(hours=7)
    
    # 1st Sunday of November
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    days_to_first_sun_nov = (6 - nov1.weekday()) % 7
    first_sun_nov = nov1 + timedelta(days=days_to_first_sun_nov)
    # DST ends at 2:00 AM ET = 6:00 AM UTC (when still in DST, ET = UTC-4)
    dst_end = first_sun_nov + timedelta(hours=6)
    
    return dst_start <= dt_utc < dst_end


def _utc_to_et(dt_utc: datetime) -> datetime:
    """Convert UTC datetime to US Eastern."""
    offset = _ET_OFFSET_DST if _is_us_dst(dt_utc) else _ET_OFFSET_STANDARD
    et_tz = timezone(offset)
    return dt_utc.astimezone(et_tz)


class SessionGuard:
    """Enforces Kalshi trading session rules.

    Usage::

        guard = SessionGuard(session_config)
        if guard.is_trading_allowed():
            # place order
        else:
            reason = guard.block_reason()
    """

    def __init__(self, config: Optional[SessionConfig] = None):
        self._config = config or SessionConfig()
        # Parse maintenance window times
        parts_start = self._config.maintenance_start_et.split(":")
        parts_end = self._config.maintenance_end_et.split(":")
        self._maint_start = time(int(parts_start[0]), int(parts_start[1]))
        self._maint_end = time(int(parts_end[0]), int(parts_end[1]))
        self._maint_day = self._config.maintenance_day

    def is_trading_allowed(self, now_utc: Optional[datetime] = None) -> bool:
        """Return True if Kalshi is open for trading right now."""
        now_utc = now_utc or datetime.now(timezone.utc)
        return not self._in_maintenance(now_utc)

    def block_reason(self, now_utc: Optional[datetime] = None) -> Optional[str]:
        """Return human-readable reason if trading is blocked, else None."""
        now_utc = now_utc or datetime.now(timezone.utc)
        if self._in_maintenance(now_utc):
            et = _utc_to_et(now_utc)
            return (
                f"Kalshi maintenance window: "
                f"{self._config.maintenance_start_et}–{self._config.maintenance_end_et} ET "
                f"(current ET: {et.strftime('%H:%M')})"
            )
        return None

    def time_until_open(self, now_utc: Optional[datetime] = None) -> Optional[timedelta]:
        """If currently blocked, return timedelta until trading resumes."""
        now_utc = now_utc or datetime.now(timezone.utc)
        if not self._in_maintenance(now_utc):
            return None
        et = _utc_to_et(now_utc)
        # Build end-of-maintenance datetime in ET
        end_et = et.replace(
            hour=self._maint_end.hour,
            minute=self._maint_end.minute,
            second=0,
            microsecond=0,
        )
        if end_et <= et:
            end_et += timedelta(days=1)
        return end_et - et

    def _in_maintenance(self, now_utc: datetime) -> bool:
        """Check if now falls within the weekly maintenance window."""
        et = _utc_to_et(now_utc)
        # Check day of week (Monday=0)
        if et.weekday() != self._maint_day:
            return False
        current_time = et.time()
        return self._maint_start <= current_time < self._maint_end

    def summary(self) -> dict:
        """JSON-serialisable status."""
        now = datetime.now(timezone.utc)
        et = _utc_to_et(now)
        trading_allowed = self.is_trading_allowed(now)
        maintenance_day: bool = False

        try:
            from merid.event_venues.kalshi.exchange_availability import get_kalshi_exchange_availability
            snap = get_kalshi_exchange_availability().snapshot()
            trading_allowed = snap.trading_open_now
            maintenance_day = not snap.trading_open_now
        except Exception:
            # Fall back to local maintenance-window calculation.
            # Default to safe state (no trading) when exchange status unavailable.
            maintenance_day = bool(self._in_maintenance(now))
            trading_allowed = not maintenance_day

        return {
            "trading_allowed": trading_allowed,
            "block_reason": self.block_reason(now),
            "current_utc": now.isoformat(),
            "current_et": et.strftime("%Y-%m-%d %H:%M:%S ET"),
            "maintenance_day": maintenance_day,
            "maintenance_window": f"{self._config.maintenance_start_et}–{self._config.maintenance_end_et} ET",
        }


# ── Singleton ──────────────────────────────────────────────────────────

_guard: Optional[SessionGuard] = None
_guard_lock = threading.Lock()


def get_session_guard(config: Optional[SessionConfig] = None) -> SessionGuard:
    """Return the module-level SessionGuard singleton."""
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = SessionGuard(config)
    return _guard
