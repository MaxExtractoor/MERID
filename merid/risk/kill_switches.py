"""MERID Risk Kill Switches.

Hard safety controls that halt trading when triggered.

Kill Switches use a 3-tier escalation system to avoid false positives:

  Tier 1 — WARNING  (≥ warn_pct of threshold)
      Log alert + Telegram notification.  Trading continues normally.
      Requires condition to hold for ``warn_persistence_secs`` before
      escalating to Tier 2.

  Tier 2 — LIMITED  (≥ limit_pct of threshold)
      Size multiplier reduced (``limit_size_multiplier``, default 0.5).
      New orders still placed but at half the normal size.
      Requires condition to hold for ``limit_persistence_secs`` before
      escalating to Tier 3.

  Tier 3 — TRIGGERED  (≥ 100 % of threshold, multi-signal or manual)
      Full kill: all new orders blocked; open orders cancelled in live mode.

Single-threshold automated kills now require *multi-signal* confirmation
(e.g. error spike **and** negative PnL) before jumping directly to TRIGGERED,
preventing transient noise from stopping the system.

Explicit exclusions (``error_exempt_classes``) downgrade known benign errors
(min_notional, ws_reconnect, loop_lag) to warnings so they never consume the
error budget.

Usage:
    from merid.risk.kill_switches import risk_controller

    # Check before any trade
    if not risk_controller.can_trade():
        return  # Trading halted

    # Check if sizing should be reduced (Tier 2)
    size_mult = risk_controller.size_multiplier()  # 1.0 or limit_size_multiplier

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
    """Kill switch states (3-tier escalation).

    ACTIVE    — Normal operation; all trading allowed.
    WARNING   — Tier 1: threshold approaching; log + alert only.
    LIMITED   — Tier 2: threshold close; orders still placed at reduced size.
    TRIGGERED — Tier 3: full kill; no new orders.
    """
    ACTIVE = "active"        # Tier 0 — Trading allowed
    WARNING = "warning"      # Tier 1 — Alert only, no trade block
    LIMITED = "limited"      # Tier 2 — Reduced size, trades still placed
    TRIGGERED = "triggered"  # Tier 3 — Trading halted


class KillSwitchReason(str, Enum):
    """Reasons for kill switch activation."""
    MANUAL = "manual"                    # Operator triggered
    DAILY_LOSS = "daily_loss"            # Daily loss limit hit
    POSITION_LIMIT = "position_limit"    # Position limit exceeded
    ERROR_THRESHOLD = "error_threshold"  # Too many errors
    CIRCUIT_BREAKER = "circuit_breaker"  # All venues circuit-broken


# Ordered from least to most severe — used by _evaluate_tier for promotion logic.
_TIER_ORDER: list = [
    KillSwitchState.ACTIVE,
    KillSwitchState.WARNING,
    KillSwitchState.LIMITED,
    KillSwitchState.TRIGGERED,
]


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
    Central risk controller with a 3-tier kill-switch escalation system.

    Tier thresholds (as fraction of the hard limit):
        warn_pct  (default 0.70) → WARNING  — alert only
        limit_pct (default 0.90) → LIMITED  — reduced order size
        1.00                     → TRIGGERED — full kill

    Time-persistence guards prevent transient noise from escalating tiers:
        warn_persistence_secs  (default 30) — hold at WARNING for N s before → LIMITED
        limit_persistence_secs (default 60) — hold at LIMITED for N s before → TRIGGERED

    Multi-signal guard: automated TRIGGERED requires at least 2 independent
    breach signals (e.g. error spike *and* PnL loss). Manual emergency_stop()
    always triggers immediately with no multi-signal requirement.

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

    # ---- 3-tier configuration ------------------------------------------------
    # Fraction of the hard limit at which each tier activates.
    warn_pct: float = 0.70    # 70 % → Tier 1 WARNING (alert only)
    limit_pct: float = 0.90   # 90 % → Tier 2 LIMITED (reduced size)
    # Order-size multiplier while in LIMITED tier (0.0–1.0).
    limit_size_multiplier: float = 0.5
    # Seconds a condition must persist at each tier before escalating.
    warn_persistence_secs: float = 30.0
    limit_persistence_secs: float = 60.0
    # Number of distinct breach signals required for an automated TRIGGERED
    # (does not apply to manual emergency_stop).
    multi_signal_required: int = 2

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

        # ---- 3-tier state tracking -------------------------------------------
        # Current tier state (may be ACTIVE, WARNING, LIMITED, or TRIGGERED).
        self._tier_state: KillSwitchState = KillSwitchState.ACTIVE
        # Timestamps when the current tier was first entered (per metric).
        # Keys: "error", "daily_loss", "position".  Value: monotonic time.
        self._tier_entry_time: Dict[str, float] = {}
        # Set of metrics currently in breach (for multi-signal check).
        self._active_breaches: Set[str] = set()

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
    # Tier helpers
    # -------------------------------------------------------------------------

    def _breach_fraction(self, metric: str) -> float:
        """Return current breach fraction (0.0–∞) for a metric.

        Used internally to decide which tier to apply.
        """
        if metric == "error":
            return self._error_count / max(self.error_threshold, 1)
        if metric == "daily_loss":
            if self._daily_pnl < 0 and self.daily_loss_limit > 0:
                return abs(self._daily_pnl) / self.daily_loss_limit
            return 0.0
        if metric == "position":
            return (self._total_position_value / self.max_position_value) if self.max_position_value > 0 else 0.0
        return 0.0

    def _evaluate_tier(self, metric: str, fraction: float) -> None:
        """Apply 3-tier logic for a single metric without touching _global_kill.

        - fraction < warn_pct           → clear this metric's breach
        - warn_pct ≤ fraction < limit_pct  → Tier 1 (WARNING) after persistence
        - limit_pct ≤ fraction < 1.0    → Tier 2 (LIMITED) after persistence
        - fraction ≥ 1.0 + multi-signal → escalate toward TRIGGERED (caller decides)
        """
        now_mono = time.monotonic()

        if fraction < self.warn_pct:
            # Condition cleared — remove from active breaches and tier entry time
            if metric in self._active_breaches:
                logger.info("[risk] Tier breach cleared for metric=%s (fraction=%.2f)", metric, fraction)
            self._active_breaches.discard(metric)
            self._tier_entry_time.pop(metric, None)
            return

        # Record breach entry time (first time we see this metric in breach)
        if metric not in self._tier_entry_time:
            self._tier_entry_time[metric] = now_mono
            self._active_breaches.add(metric)

        elapsed = now_mono - self._tier_entry_time[metric]

        if fraction >= self.limit_pct:
            if elapsed >= self.limit_persistence_secs:
                desired = KillSwitchState.LIMITED
            elif elapsed >= self.warn_persistence_secs:
                desired = KillSwitchState.WARNING
            else:
                desired = KillSwitchState.ACTIVE  # still within warn grace period
        else:  # warn_pct ≤ fraction < limit_pct
            if elapsed >= self.warn_persistence_secs:
                desired = KillSwitchState.WARNING
            else:
                desired = KillSwitchState.ACTIVE  # still within warn grace period

        # Only promote tier state, never demote here (demotion handled in _maybe_demote_tier)
        current_idx = _TIER_ORDER.index(self._tier_state)
        desired_idx = _TIER_ORDER.index(desired)
        if desired_idx > current_idx:
            self._promote_tier(desired, metric, fraction)

    def _promote_tier(self, new_state: KillSwitchState, metric: str, fraction: float) -> None:
        """Promote _tier_state to new_state and emit event/alert."""
        old_state = self._tier_state
        self._tier_state = new_state
        details = f"metric={metric} fraction={fraction:.2f}"

        event = KillSwitchEvent(
            timestamp=self._now(),
            old_state=old_state,
            new_state=new_state,
            reason=KillSwitchReason.ERROR_THRESHOLD if metric == "error" else (
                KillSwitchReason.DAILY_LOSS if metric == "daily_loss" else KillSwitchReason.POSITION_LIMIT
            ),
            details=details,
        )
        self._events.append(event)

        if new_state == KillSwitchState.WARNING:
            logger.warning(
                "[risk] Tier 1 WARNING: %s — fraction=%.0f%% of threshold. "
                "Monitor closely. Trading continues normally.",
                metric, fraction * 100,
            )
            self._send_telegram_alert(
                f"⚠️ [RISK WARNING] <b>{metric.upper()}</b> at {fraction * 100:.0f}% of threshold"
            )
        elif new_state == KillSwitchState.LIMITED:
            logger.warning(
                "[risk] Tier 2 LIMITED: %s — fraction=%.0f%% of threshold. "
                "Order sizes reduced to %.0f%%. Watch for escalation.",
                metric, fraction * 100, self.limit_size_multiplier * 100,
            )
            self._send_telegram_alert(
                f"🔶 [RISK LIMITED] <b>{metric.upper()}</b> at {fraction * 100:.0f}% — "
                f"sizes reduced to {self.limit_size_multiplier * 100:.0f}%"
            )
            try:
                from core.session_log import record_event
                record_event(
                    category="kill_switch",
                    severity="warning",
                    title="Risk LIMITED: order sizes reduced",
                    detail=details,
                    hint="System approaching hard limit. Investigate root cause.",
                    metadata={"metric": metric, "fraction": fraction, "tier": "limited"},
                )
            except Exception:
                pass

    def _maybe_demote_tier(self) -> None:
        """Downgrade tier state if all active breaches have cleared."""
        if self._global_kill:
            return  # TRIGGERED is reset only via reset()

        # Recompute overall tier from still-active breaches
        if not self._active_breaches:
            if self._tier_state in (KillSwitchState.WARNING, KillSwitchState.LIMITED):
                logger.info("[risk] All breach metrics cleared — reverting to ACTIVE")
                self._tier_state = KillSwitchState.ACTIVE
            return

        # Downgrade only if highest breach metric no longer warrants current tier
        max_fraction = max(self._breach_fraction(m) for m in self._active_breaches)
        if max_fraction < self.warn_pct:
            logger.info("[risk] Max fraction %.2f below warn threshold — reverting to ACTIVE", max_fraction)
            self._tier_state = KillSwitchState.ACTIVE
        elif max_fraction < self.limit_pct and self._tier_state == KillSwitchState.LIMITED:
            logger.info("[risk] Max fraction %.2f below limit threshold — reverting to WARNING", max_fraction)
            self._tier_state = KillSwitchState.WARNING

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def can_trade(self) -> bool:
        """Check if trading is allowed.

        Call this before every trade attempt.
        Returns False only if Tier 3 (TRIGGERED) — WARNING and LIMITED still
        allow trading (use ``size_multiplier()`` to respect size limits).
        """
        # Reset daily P&L if new day
        today = self._today()
        if self._daily_pnl_reset_date != today:
            logger.info(f"[risk] New trading day, resetting daily P&L from {self._daily_pnl}")
            self._daily_pnl = 0.0
            self._daily_pnl_reset_date = today

        # Inline daily-loss check: apply multi-signal-aware trigger if limit breached.
        # This catches cases where _global_kill was not set by record_pnl and
        # respects the same multi-signal / persistence rules: only kills immediately
        # if multi-signal threshold is met or the loss is a single-step catastrophic drop.
        if (
            not self._global_kill
            and self._daily_pnl < 0
            and abs(self._daily_pnl) >= self.daily_loss_limit
        ):
            breach_count = len(self._active_breaches)
            # Count "daily_loss" as active breach for this check
            if "daily_loss" not in self._active_breaches:
                breach_count += 1
            if breach_count >= self.multi_signal_required:
                self._trigger_kill(
                    KillSwitchReason.DAILY_LOSS,
                    f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${self.daily_loss_limit:.2f} (detected in can_trade, multi-signal)",
                )

        # Refresh tier state from current metric fractions
        if not self._global_kill:
            for metric in ("error", "daily_loss", "position"):
                frac = self._breach_fraction(metric)
                self._evaluate_tier(metric, frac)
            self._maybe_demote_tier()

        return not self._global_kill

    def size_multiplier(self) -> float:
        """Return the current order-size multiplier based on tier state.

        - ACTIVE / WARNING → 1.0  (no size reduction)
        - LIMITED          → ``limit_size_multiplier`` (default 0.5)
        - TRIGGERED        → 0.0  (no orders should be placed)
        """
        if self._global_kill:
            return 0.0
        if self._tier_state == KillSwitchState.LIMITED:
            return self.limit_size_multiplier
        return 1.0

    def get_state(self) -> KillSwitchState:
        """Get current kill switch state (includes WARNING and LIMITED tiers)."""
        if self._global_kill:
            return KillSwitchState.TRIGGERED
        return self._tier_state

    def state(self) -> str:
        """Get current state as string."""
        return self.get_state().value

    def get_kill_reason(self) -> Optional[str]:
        """Get the reason for kill switch activation, if any."""
        if self._kill_reason:
            return f"{self._kill_reason.value}: {self._kill_details}" if self._kill_details else self._kill_reason.value
        return None

    def get_status(self) -> dict:
        """Get full risk controller status.

        Useful for dashboards and monitoring.
        """
        state = self.get_state()
        return {
            "state": state.value,
            "tier": state.value,
            "can_trade": self.can_trade(),
            "size_multiplier": self.size_multiplier(),
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
            "active_breaches": list(self._active_breaches),
            "warn_pct": self.warn_pct,
            "limit_pct": self.limit_pct,
        }

    # -------------------------------------------------------------------------
    # Kill Switch Triggers
    # -------------------------------------------------------------------------

    def emergency_stop(self, reason: str = "Manual stop") -> None:
        """Trigger global kill switch immediately.

        Manual intervention always triggers regardless of multi-signal
        requirement or persistence timers.
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
        """Reset kill switch to allow trading.

        Requires explicit operator acknowledgment.
        Also clears tier state and breach tracking.
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

        # Clear tier state and breach tracking
        self._tier_state = KillSwitchState.ACTIVE
        self._tier_entry_time.clear()
        self._active_breaches.clear()

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
        """Record P&L from a trade.

        Evaluates tier state via the 3-tier system.  Full kill (TRIGGERED)
        requires the loss to meet the hard limit **and** either:
          - another breach metric is also active (multi-signal), or
          - the loss was large enough to exceed the limit in a single step.

        Returns True if trading can continue (including WARNING/LIMITED),
        False if TRIGGERED.
        """
        self._daily_pnl += pnl

        if self._daily_pnl >= 0 or self.daily_loss_limit <= 0:
            return True

        loss = abs(self._daily_pnl)
        fraction = loss / self.daily_loss_limit

        # Evaluate tier for this metric
        self._evaluate_tier("daily_loss", fraction)

        # Hard kill when fraction ≥ 1.0 (multi-signal or single-step jump)
        if fraction >= 1.0 and not self._global_kill:
            breach_count = len(self._active_breaches)
            # Trigger immediately if multi-signal threshold met, or loss exceeds
            # limit in one step (rapid drawdown — cannot wait for persistence).
            single_step_jump = pnl < 0 and abs(pnl) >= self.daily_loss_limit
            if breach_count >= self.multi_signal_required or single_step_jump:
                self._trigger_kill(
                    KillSwitchReason.DAILY_LOSS,
                    f"Daily loss ${loss:.2f} >= limit ${self.daily_loss_limit:.2f} "
                    f"(breaches={list(self._active_breaches)})",
                )
                logger.critical(
                    "[risk] DAILY LOSS KILL: $%.2f >= $%.2f (signals: %s)",
                    loss, self.daily_loss_limit, list(self._active_breaches),
                )
                return False
            else:
                # Single-signal at limit — escalate to LIMITED and hold for persistence
                logger.warning(
                    "[risk] Daily loss at limit but only %d/%d signals active — "
                    "holding at LIMITED tier (persistence check).",
                    breach_count, self.multi_signal_required,
                )

        return not self._global_kill

    def update_position_value(self, total_value: float) -> bool:
        """Update total position value.

        Applies 3-tier evaluation.  Full kill requires multi-signal or a
        single-step breach that exceeds the limit by >20 % (safety margin).
        Returns True if trading can continue, False if killed.
        """
        self._total_position_value = total_value

        if self.max_position_value <= 0:
            return True

        fraction = total_value / self.max_position_value
        self._evaluate_tier("position", fraction)

        if fraction >= 1.0 and not self._global_kill:
            breach_count = len(self._active_breaches)
            # Immediate kill if multi-signal, or grossly over limit (>20 % buffer)
            hard_breach = fraction >= 1.20
            if breach_count >= self.multi_signal_required or hard_breach:
                self._trigger_kill(
                    KillSwitchReason.POSITION_LIMIT,
                    f"Position ${total_value:.2f} >= limit ${self.max_position_value:.2f} "
                    f"(breaches={list(self._active_breaches)})",
                )
                logger.critical(
                    "[risk] POSITION LIMIT KILL: $%.2f > $%.2f (signals: %s)",
                    total_value, self.max_position_value, list(self._active_breaches),
                )
                return False

        return not self._global_kill

    # -------------------------------------------------------------------------
    # Error Tracking
    # -------------------------------------------------------------------------

    def record_error(self, error_class: str = "generic") -> bool:
        """Record an error occurrence.

        Errors are tracked in a true 1-hour sliding window rather than a
        tumbling window that resets every hour.  Exempt error classes (e.g.,
        ``min_notional``, ``ws_reconnect``) are logged at WARNING but do **not**
        contribute to the kill-switch budget.

        The 3-tier system means errors escalate to WARNING → LIMITED → TRIGGERED
        based on breach fraction and persistence rather than a single hard threshold.
        Full kill also requires multi-signal confirmation unless the error count
        exceeds the threshold by a substantial margin (≥150 %).

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

        fraction = self._error_count / max(self.error_threshold, 1)
        self._evaluate_tier("error", fraction)

        if fraction >= 1.0 and not self._global_kill:
            top_classes = self._error_class_counts.most_common(3)
            breach_count = len(self._active_breaches)
            # Full kill if multi-signal, or error rate is egregiously high (≥150 %)
            runaway = fraction >= 1.50
            if breach_count >= self.multi_signal_required or runaway:
                detail = (
                    f"{self._error_count} errors in last hour exceeds threshold "
                    f"{self.error_threshold}; top classes: {top_classes}; "
                    f"breaches={list(self._active_breaches)}"
                )
                self._trigger_kill(KillSwitchReason.ERROR_THRESHOLD, detail)
                logger.critical(
                    "[risk] ERROR THRESHOLD KILL: %d errors/hr (top classes: %s, signals: %s). "
                    "To auto-reopen: reset() after error rate drops below %d/hr and "
                    "root cause is resolved.",
                    self._error_count, top_classes, list(self._active_breaches),
                    self.error_threshold,
                )
                return False
            else:
                logger.warning(
                    "[risk] Error threshold breached (%d/%d) but only %d/%d signals active — "
                    "holding at LIMITED tier pending multi-signal confirmation.",
                    self._error_count, self.error_threshold,
                    breach_count, self.multi_signal_required,
                )

        return not self._global_kill
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    
    def reset_daily_counters(self) -> None:
        """Zero transient PnL / error counters for a fresh start.

        Kill-switch state (_global_kill, _kill_reason, etc.) is
        deliberately **preserved** so a reset cannot silently
        re-enable trading.  Tier state is also cleared so WARNING/LIMITED
        do not linger after counters are zeroed.
        """
        self._daily_pnl = 0.0
        self._daily_pnl_reset_date = self._today()
        self._total_position_value = 0.0
        self._error_log.clear()
        self._error_class_counts.clear()
        self._error_count = 0
        self._events.clear()
        # Clear tier tracking (counters are gone; tier state is no longer valid)
        if not self._global_kill:
            self._tier_state = KillSwitchState.ACTIVE
        self._tier_entry_time.clear()
        self._active_breaches.clear()
        logger.info("[risk] Daily counters reset (kill-switch state preserved)")

    def on_kill(self, callback: Callable[[KillSwitchEvent], None]) -> None:
        """Register callback for kill switch events."""
        self._callbacks.append(callback)

    def get_events(self, limit: int = 10) -> List[KillSwitchEvent]:
        """Get recent kill switch events."""
        return self._events[-limit:]

    def _send_telegram_alert(self, message: str) -> None:
        """Fire-and-forget Telegram notification (best-effort, no exception propagation)."""
        try:
            import asyncio as _aio
            from merid.alerts.webhook_client import tg_send
            _loop = _aio.get_running_loop()
            _loop.create_task(tg_send(message))
        except RuntimeError:
            logger.debug("[risk] Telegram alert skipped — no running loop")
        except Exception as _tg_exc:
            logger.debug("[risk] Telegram alert failed: %s", _tg_exc)

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
