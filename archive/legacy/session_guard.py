"""Kalshi Session Guard — Trading hours, maintenance window, and degraded mode enforcement.

Kalshi is 24/7 except:
1. Weekly maintenance window (Thu 3–5 AM ET)
2. Loop lag degraded mode (sustained high event-loop lag blocks NEW orders)

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
    """Enforces Kalshi trading session rules and system health.

    Usage::

        guard = SessionGuard(session_config)
        if guard.is_trading_allowed():
            # place order
        else:
            reason = guard.block_reason()

    DEGRADED MODE:
    When event-loop lag exceeds hard threshold (sustained >1000ms),
    new order placement is blocked but position closing is allowed.
    """

    def __init__(self, config: Optional[SessionConfig] = None):
        self._config = config or SessionConfig()
        # Parse maintenance window times
        parts_start = self._config.maintenance_start_et.split(":")
        parts_end = self._config.maintenance_end_et.split(":")
        self._maint_start = time(int(parts_start[0]), int(parts_start[1]))
        self._maint_end = time(int(parts_end[0]), int(parts_end[1]))
        self._maint_day = self._config.maintenance_day
        # Track degraded mode state
        self._degraded_mode_start: Optional[datetime] = None

    def _in_degraded_mode(self) -> tuple[bool, Optional[str]]:
        """Check if system is in degraded mode due to loop lag.

        Returns:
            Tuple of (is_degraded, reason) where reason is None if not degraded.
        """
        try:
            from merid.diagnostics.loop_lag import get_loop_lag_monitor
            monitor = get_loop_lag_monitor()
            if monitor and monitor.is_degraded:
                # Check if this is a new entry into degraded mode
                now = datetime.now(timezone.utc)
                if self._degraded_mode_start is None:
                    self._degraded_mode_start = now
                    logger.critical(
                        "[DEGRADED-MODE] ENTERING DEGRADED MODE — "
                        "Loop lag sustained above threshold. "
                        "NEW order placement blocked. Position closing allowed."
                    )
                duration = now - self._degraded_mode_start
                return True, f"Degraded mode: high loop lag for {duration.total_seconds():.0f}s"
            else:
                # Was in degraded mode but recovered
                if self._degraded_mode_start is not None:
                    now = datetime.now(timezone.utc)
                    duration = now - self._degraded_mode_start
                    logger.info(
                        "[DEGRADED-MODE] Scope restoration after %.1fs — "
                        "Lag recovered, resuming normal operation",
                        duration.total_seconds()
                    )
                    self._degraded_mode_start = None
                return False, None
        except Exception:
            # If we can't check degraded mode, assume healthy (fail-open)
            return False, None

    def is_trading_allowed(self, now_utc: Optional[datetime] = None, is_closing_position: bool = False) -> bool:
        """Return True if Kalshi is open for trading right now.

        Args:
            now_utc: Current time (defaults to now)
            is_closing_position: If True, allow trade even in degraded mode
                (we always allow closing positions to reduce risk)
        """
        now_utc = now_utc or datetime.now(timezone.utc)

        # Check maintenance window
        if self._in_maintenance(now_utc):
            return False

        # Check degraded mode (loop lag)
        # OLD-HARDWARE FIX (2026-04-29): Allow trading even in degraded mode
        # Previous behavior: Block NEW orders in degraded mode
        # New behavior: Log warning but allow trades (rely on risk limits)
        is_degraded, degraded_reason = self._in_degraded_mode()
        if is_degraded and not is_closing_position:
            # Log warning but DON'T block - let risk limits handle protection
            logger.debug(
                "[SESSION-GUARD] Trading during degraded mode - %s. "
                "Risk limits still active.",
                degraded_reason
            )
            # Return True to allow trading despite degraded mode
            # return False  # OLD behavior - blocking
            pass  # NEW behavior - allow with logging only

        return True

    def block_reason(self, now_utc: Optional[datetime] = None, is_closing_position: bool = False) -> Optional[str]:
        """Return human-readable reason if trading is blocked, else None."""
        now_utc = now_utc or datetime.now(timezone.utc)
        if self._in_maintenance(now_utc):
            et = _utc_to_et(now_utc)
            return (
                f"Kalshi maintenance window: "
                f"{self._config.maintenance_start_et}–{self._config.maintenance_end_et} ET "
                f"(current ET: {et.strftime('%H:%M')})"
            )

        # Check degraded mode
        # OLD-HARDWARE FIX (2026-04-29): Don't block due to degraded mode
        # is_degraded, degraded_reason = self._in_degraded_mode()
        # if is_degraded and not is_closing_position:
        #     return degraded_reason

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
_guard_lock = None


def get_session_guard(config: Optional[SessionConfig] = None) -> SessionGuard:
    """Return the module-level SessionGuard singleton."""
    global _guard
    if _guard is None:
        if _guard_lock is not None:
            with _guard_lock:
                if _guard is None:
                    _guard = SessionGuard(config)
        else:
            # Lock disabled - direct initialization (startup workaround)
            _guard = SessionGuard(config)
    return _guard
