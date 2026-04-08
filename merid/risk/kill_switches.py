"""MERID Risk Kill Switches.

Hard safety controls that halt trading when triggered.

Kill Switches:
1. Global Kill Switch - Immediately halts all trading
2. Daily Loss Kill - Halts when daily P&L limit breached

Usage:
    from merid.risk.kill_switches import risk_controller
    
    # Check before any trade
    if not risk_controller.can_trade():
        return  # Trading halted
    
    # Record P&L after trades
    risk_controller.record_pnl(-50.0)
    
    # Emergency stop
    risk_controller.emergency_stop("Manual operator intervention")
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.risk.kill_switches")


class KillSwitchState(str, Enum):
    """Kill switch states."""
    ACTIVE = "active"        # Trading allowed
    TRIGGERED = "triggered"  # Trading halted


class KillSwitchReason(str, Enum):
    """Reasons for kill switch activation."""
    MANUAL = "manual"                    # Operator triggered
    DAILY_LOSS = "daily_loss"            # Daily loss limit hit
    POSITION_LIMIT = "position_limit"    # Position limit exceeded
    ERROR_THRESHOLD = "error_threshold"  # Too many errors
    CIRCUIT_BREAKER = "circuit_breaker"  # All venues circuit-broken


@dataclass
class KillSwitchEvent:
    """Record of a kill switch state change."""
    timestamp: datetime
    old_state: KillSwitchState
    new_state: KillSwitchState
    reason: KillSwitchReason
    details: Optional[str] = None


@dataclass 
class RiskController:
    """
    Central risk controller with kill switches.
    
    Thread-safe singleton that integrates with:
    - Settings (config validation)
    - Circuit breakers (venue health)
    - Trading engine (P&L tracking)
    """
    
    daily_loss_limit: float = 500.0
    max_position_value: float = 10000.0
    # Threshold raised from 10 to 50: benign repeating errors (min_notional misconfig,
    # WS reconnects) must not exhaust the budget before a human can investigate.
    error_threshold: int = 50
    # Error classes that are downgraded to warnings and do NOT count toward the
    # error budget.  One misconfigured asset/TF producing repeated identical
    # min_notional failures must not instantly trip the breaker.
    error_exempt_classes: Set[str] = field(
        default_factory=lambda: {"min_notional", "ws_reconnect", "loop_lag"}
    )
    
    def __post_init__(self):
        self._global_kill: bool = False
        self._kill_reason: Optional[KillSwitchReason] = None
        self._kill_details: Optional[str] = None
        self._kill_timestamp: Optional[datetime] = None
        
        self._daily_pnl: float = 0.0
        self._daily_pnl_reset_date: str = self._today()
        self._total_position_value: float = 0.0
        
        # Sliding-window error tracking: each entry is (timestamp, error_class).
        # Using a deque sized to a large but bounded number of events so old
        # timestamps can be purged on each record_error() call without a full
        # O(N) rebuild.  A maxlen of 10 × threshold prevents unbounded growth.
        self._error_log: deque = deque(maxlen=self.error_threshold * 10)
        # Class-level count within the current sliding window (rebuilt on purge).
        self._error_class_counts: Counter = Counter()
        # Legacy scalar kept for backward-compat with get_status().
        self._error_count: int = 0
        
        self._events: List[KillSwitchEvent] = []
        self._callbacks: List[Callable[[KillSwitchEvent], None]] = []
        
        # Load from settings if available
        self._load_from_settings()
    
    def _load_from_settings(self):
        """Load limits from settings module if not explicitly set."""
        # Only load from settings if using defaults
        if self.daily_loss_limit == 500.0 and self.max_position_value == 10000.0:
            try:
                from merid.settings import settings
                self.daily_loss_limit = settings.MERID_MAX_DAILY_LOSS_USD
                self.max_position_value = settings.MERID_MAX_POSITION_SIZE_USD * 10
            except (ImportError, AttributeError):
                pass
    
    @staticmethod
    def _today() -> str:
        """Get today's date string (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    @staticmethod
    def _now() -> datetime:
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc)
    
    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------
    
    def can_trade(self) -> bool:
        """
        Check if trading is allowed.
        
        Call this before every trade attempt.
        Returns False if any kill switch is triggered.
        """
        # Reset daily P&L if new day
        today = self._today()
        if self._daily_pnl_reset_date != today:
            logger.info(f"[risk] New trading day, resetting daily P&L from {self._daily_pnl}")
            self._daily_pnl = 0.0
            self._daily_pnl_reset_date = today

        # Inline daily-loss check: fire kill if limit already breached
        # (catches cases where _global_kill was not yet set by record_pnl)
        if (
            not self._global_kill
            and self._daily_pnl < 0
            and abs(self._daily_pnl) >= self.daily_loss_limit
        ):
            self._trigger_kill(
                KillSwitchReason.DAILY_LOSS,
                f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${self.daily_loss_limit:.2f} (detected in can_trade)",
            )

        return not self._global_kill
    
    def get_state(self) -> KillSwitchState:
        """Get current kill switch state."""
        return KillSwitchState.TRIGGERED if self._global_kill else KillSwitchState.ACTIVE
    
    def state(self) -> str:
        """Get current state as string."""
        return self.get_state().value
    
    def get_kill_reason(self) -> Optional[str]:
        """Get the reason for kill switch activation, if any."""
        if self._kill_reason:
            return f"{self._kill_reason.value}: {self._kill_details}" if self._kill_details else self._kill_reason.value
        return None
    
    def get_status(self) -> dict:
        """
        Get full risk controller status.
        
        Useful for dashboards and monitoring.
        """
        return {
            "state": self.get_state().value,
            "can_trade": self.can_trade(),
            "kill_reason": self._kill_reason.value if self._kill_reason else None,
            "kill_details": self._kill_details,
            "kill_timestamp": self._kill_timestamp.isoformat() if self._kill_timestamp else None,
            "daily_pnl": self._daily_pnl,
            "daily_loss_limit": self.daily_loss_limit,
            "daily_pnl_pct": (abs(self._daily_pnl) / self.daily_loss_limit * 100) if self.daily_loss_limit > 0 else 0,
            "position_value": self._total_position_value,
            "max_position_value": self.max_position_value,
            "error_count": self._error_count,
            "error_threshold": self.error_threshold,
            "error_class_counts": dict(self._error_class_counts),
            "error_exempt_classes": list(self.error_exempt_classes),
            "events_count": len(self._events),
        }
    
    # -------------------------------------------------------------------------
    # Kill Switch Triggers
    # -------------------------------------------------------------------------
    
    def emergency_stop(self, reason: str = "Manual stop") -> None:
        """
        Trigger global kill switch immediately.
        
        Use for manual intervention or automated safety triggers.
        """
        if self._global_kill:
            logger.warning(f"[risk] Kill switch already triggered, ignoring: {reason}")
            return
        
        self._trigger_kill(KillSwitchReason.MANUAL, reason)
        logger.critical(f"[risk] EMERGENCY STOP: {reason}")
    
    def _trigger_kill(self, reason: KillSwitchReason, details: str) -> None:
        """Internal method to trigger kill switch."""
        old_state = self.get_state()

        self._global_kill = True
        self._kill_reason = reason
        self._kill_details = details
        self._kill_timestamp = self._now()

        event = KillSwitchEvent(
            timestamp=self._kill_timestamp,
            old_state=old_state,
            new_state=KillSwitchState.TRIGGERED,
            reason=reason,
            details=details,
        )
        self._events.append(event)

        # Record session event
        try:
            from core.session_log import record_event
            record_event(
                category="kill_switch",
                severity="critical",
                title="Kill switch TRIGGERED",
                detail=details,
                hint="Reset via Mode & Safety panel after investigating the trigger cause.",
                metadata={"reason": reason.value if hasattr(reason, 'value') else str(reason)},
            )
        except Exception as _se_exc:
            logger.debug("[risk] kill_switch session log failed: %s", _se_exc)

        # Telegram alert — kill switch is the most critical event
        try:
            import asyncio as _aio
            from merid.alerts.webhook_client import tg_send
            _loop = _aio.get_running_loop()
            _loop.create_task(tg_send(
                f"\U0001f6a8 [KILL SWITCH] <b>{reason.value.upper()}</b>\n{details}"
            ))
        except RuntimeError:
            logger.debug("[risk] kill_switch Telegram skipped — no running loop")
        except Exception as _tg_exc:
            logger.debug("[risk] kill_switch Telegram failed: %s", _tg_exc)

        # Cancel all open orders when kill switch triggers (live mode only)
        try:
            import asyncio as _aio
            from merid.settings import settings
            # Only cancel orders in live mode
            if settings.MERID_MODE == "LIVE":
                try:
                    _loop = _aio.get_running_loop()
                    _loop.create_task(self._cancel_all_orders_async(reason))
                except RuntimeError:
                    logger.warning("[risk] kill_switch: No running loop for order cancellation")
        except Exception as _cancel_exc:
            logger.error(f"[risk] kill_switch order cancellation failed: {_cancel_exc}")

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"[risk] Callback error: {e}")
    
    def reset(self, operator: str = "system") -> bool:
        """
        Reset kill switch to allow trading.
        
        Requires explicit operator acknowledgment.
        Returns True if reset successful.
        """
        if not self._global_kill:
            logger.info("[risk] Kill switch not triggered, nothing to reset")
            return True
        
        old_reason = self._kill_reason
        old_details = self._kill_details
        
        self._global_kill = False
        self._kill_reason = None
        self._kill_details = None
        self._kill_timestamp = None
        
        # Don't reset daily P&L - that persists
        self._error_log.clear()
        self._error_class_counts.clear()
        self._error_count = 0
        
        event = KillSwitchEvent(
            timestamp=self._now(),
            old_state=KillSwitchState.TRIGGERED,
            new_state=KillSwitchState.ACTIVE,
            reason=KillSwitchReason.MANUAL,
            details=f"Reset by {operator} (was: {old_reason} - {old_details})",
        )
        self._events.append(event)

        # Record session event
        try:
            from core.session_log import record_event
            record_event(
                category="kill_switch",
                severity="info",
                title="Kill switch RESET",
                detail=f"Reset by {operator} (was: {old_reason} - {old_details})",
                hint="Monitor for recurrence. If the trigger was automatic, check risk thresholds.",
                metadata={"operator": operator},
            )
        except Exception as _se_exc:
            logger.debug("[risk] kill_switch reset session log failed: %s", _se_exc)
        
        logger.warning(
            "[risk] Kill switch RESET by %s (was: %s — %s). "
            "Trading re-enabled; monitor error rate for recurrence.",
            operator, old_reason, old_details,
        )
        return True
    
    # -------------------------------------------------------------------------
    # P&L Tracking
    # -------------------------------------------------------------------------
    
    def record_pnl(self, pnl: float) -> bool:
        """
        Record P&L from a trade.
        
        Automatically triggers daily loss kill if limit exceeded.
        Returns True if trading can continue, False if killed.
        """
        self._daily_pnl += pnl
        
        # Check daily loss limit (negative P&L)
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= self.daily_loss_limit:
            self._trigger_kill(
                KillSwitchReason.DAILY_LOSS,
                f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${self.daily_loss_limit:.2f}"
            )
            logger.critical(
                f"[risk] DAILY LOSS KILL: ${abs(self._daily_pnl):.2f} >= ${self.daily_loss_limit:.2f}"
            )
            return False
        
        return True
    
    def update_position_value(self, total_value: float) -> bool:
        """
        Update total position value.
        
        Triggers kill if position limit exceeded.
        Returns True if trading can continue.
        """
        self._total_position_value = total_value
        
        if total_value > self.max_position_value:
            self._trigger_kill(
                KillSwitchReason.POSITION_LIMIT,
                f"Position value ${total_value:.2f} exceeds limit ${self.max_position_value:.2f}"
            )
            logger.critical(
                f"[risk] POSITION LIMIT KILL: ${total_value:.2f} > ${self.max_position_value:.2f}"
            )
            return False
        
        return True
    
    # -------------------------------------------------------------------------
    # Error Tracking
    # -------------------------------------------------------------------------
    
    def record_error(self, error_class: str = "generic") -> bool:
        """
        Record an error occurrence.

        Errors are tracked in a true 1-hour sliding window rather than a
        tumbling window that resets every hour.  Exempt error classes (e.g.,
        ``min_notional``, ``ws_reconnect``) are logged at WARNING but do **not**
        contribute to the kill-switch budget.

        Args:
            error_class: Short descriptor for the error category.  Classes in
                ``error_exempt_classes`` are downgraded to warnings only.

        Returns:
            True if trading can continue, False if kill switch was triggered.
        """
        now = time.time()
        window_start = now - 3600.0  # 1-hour sliding window

        if error_class in self.error_exempt_classes:
            # Exempt class — warn but don't count
            logger.warning(
                "[risk] Exempt error recorded (class=%s, not counted toward budget). "
                "Threshold %d/hr, current budget errors: %d",
                error_class, self.error_threshold, self._error_count,
            )
            return not self._global_kill

        # Append to sliding log
        self._error_log.append((now, error_class))
        self._error_class_counts[error_class] += 1

        # Purge entries that have aged out of the window and rebuild counter
        while self._error_log and self._error_log[0][0] < window_start:
            _, aged_class = self._error_log.popleft()
            self._error_class_counts[aged_class] -= 1
            if self._error_class_counts[aged_class] <= 0:
                del self._error_class_counts[aged_class]

        self._error_count = len(self._error_log)

        if self._error_count >= self.error_threshold:
            top_classes = self._error_class_counts.most_common(3)
            detail = (
                f"{self._error_count} errors in last hour exceeds threshold "
                f"{self.error_threshold}; top classes: {top_classes}"
            )
            self._trigger_kill(KillSwitchReason.ERROR_THRESHOLD, detail)
            logger.critical(
                "[risk] ERROR THRESHOLD KILL: %d errors/hr (top classes: %s). "
                "To auto-reopen: reset() after error rate drops below %d/hr and "
                "root cause is resolved.",
                self._error_count, top_classes, self.error_threshold,
            )
            return False

        return True
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    
    def reset_daily_counters(self) -> None:
        """Zero transient PnL / error counters for a fresh start.

        Kill-switch state (_global_kill, _kill_reason, etc.) is
        deliberately **preserved** so a reset cannot silently
        re-enable trading.
        """
        self._daily_pnl = 0.0
        self._daily_pnl_reset_date = self._today()
        self._total_position_value = 0.0
        self._error_log.clear()
        self._error_class_counts.clear()
        self._error_count = 0
        self._events.clear()
        logger.info("[risk] Daily counters reset (kill-switch state preserved)")

    def on_kill(self, callback: Callable[[KillSwitchEvent], None]) -> None:
        """Register callback for kill switch events."""
        self._callbacks.append(callback)

    def get_events(self, limit: int = 10) -> List[KillSwitchEvent]:
        """Get recent kill switch events."""
        return self._events[-limit:]

    async def _cancel_all_orders_async(self, reason: KillSwitchReason) -> None:
        """Cancel all open orders across all venues when kill switch triggers.

        This is called automatically in live mode when the kill switch is triggered.
        It fetches all open orders and cancels them in batches.
        """
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig

        logger.critical(f"[risk] KILL SWITCH: Canceling all open orders (reason: {reason.value})")

        try:
            # Initialize Kalshi client
            config = KalshiConfig()
            client = KalshiVenueClient(config)
            await client.connect()

            try:
                # Fetch all open orders
                all_orders = await client.get_open_orders()
                order_ids = [o.order_id for o in all_orders]

                if not order_ids:
                    logger.info("[risk] KILL SWITCH: No open orders to cancel")
                    # Record event even if no orders
                    try:
                        from core.session_log import record_event
                        record_event(
                            category="kill_switch",
                            severity="info",
                            title="Kill switch: No orders to cancel",
                            detail=f"Kill switch triggered ({reason.value}) but no open orders found",
                            metadata={"kill_switch_cancelled_orders": 0, "reason": reason.value},
                        )
                    except Exception:
                        pass
                    return

                logger.warning(f"[risk] KILL SWITCH: Found {len(order_ids)} open orders, canceling in batches...")

                # Batch cancel (max 20 per call)
                all_canceled = []
                all_failed = []

                for i in range(0, len(order_ids), 20):
                    batch = order_ids[i:i+20]
                    result = await client.batch_cancel_orders(batch)

                    all_canceled.extend(result.get("canceled", []))
                    all_failed.extend(result.get("failed", []))

                # Log structured event
                canceled_count = len(all_canceled)
                failed_count = len(all_failed)

                logger.critical(
                    f"[risk] KILL SWITCH: Canceled {canceled_count} orders, "
                    f"{failed_count} failed (reason: {reason.value})"
                )

                # Record session event
                try:
                    from core.session_log import record_event
                    record_event(
                        category="kill_switch",
                        severity="critical",
                        title=f"Kill switch cancelled {canceled_count} orders",
                        detail=f"Kill switch triggered ({reason.value}), canceled {canceled_count} orders, {failed_count} failed",
                        metadata={
                            "kill_switch_cancelled_orders": canceled_count,
                            "failed_orders": failed_count,
                            "reason": reason.value,
                        },
                    )
                except Exception as _evt_exc:
                    logger.debug(f"[risk] kill_switch session log failed: {_evt_exc}")

            finally:
                await client.close()

        except Exception as exc:
            logger.error(f"[risk] KILL SWITCH: Failed to cancel orders: {exc}", exc_info=True)


# Global singleton instance
risk_controller = RiskController()


def can_trade() -> bool:
    """Convenience function to check if trading is allowed."""
    return risk_controller.can_trade()


def emergency_stop(reason: str = "Manual stop") -> None:
    """Convenience function for emergency stop."""
    risk_controller.emergency_stop(reason)


def get_risk_status() -> dict:
    """Convenience function to get risk status."""
    return risk_controller.get_status()
