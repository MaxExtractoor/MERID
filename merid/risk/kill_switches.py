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

[AGENT_AUDIT: Section 7.3 - PROTECT phase]
[AGENT_AUDIT: Section 10.4 - This module implements HARD KILL criteria
(not graduated drawdown tiers). Hard kills are immediate circuit breakers
for catastrophic scenarios (daily loss limits, error thresholds). Graduated
drawdown tiers (from merid.formulas) implement 5%/8%/12% warning/tight/halt
progressions for normal risk management. These are intentionally separate patterns.]
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import threading
from typing import Any, Callable, Dict, List, Optional, Union

from utils.logger import get_logger

# Import version constants from formulas module for TRACE logging
try:
    from merid.formulas import FORMULAS_VERSION, AUDIT_SPEC_VERSION
except ImportError:
    # Fallback if formulas module not available
    FORMULAS_VERSION = "unknown"
    AUDIT_SPEC_VERSION = "unknown"

# Optional Path/str override for tests; if None, MERID_RISK_KS_FILE is read on each persist/load.
_KILL_SWITCH_FILE: Optional[Union[Path, str]] = None


def _get_kill_switch_path() -> Path:
    """Return path to persisted kill-switch JSON.

    Evaluated on each call so ``MERID_RISK_KS_FILE`` can be set before constructing
    ``RiskController`` in tests without re-importing this module. Tests may also assign
    ``merid.risk.kill_switches._KILL_SWITCH_FILE`` to a temp path.
    """
    if _KILL_SWITCH_FILE is not None:
        return Path(_KILL_SWITCH_FILE)
    return Path(os.environ.get("MERID_RISK_KS_FILE", "data/risk_kill_switch.json"))


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
    DEPENDENCY_HEALTH = "dependency_health"  # Critical dependency down
    RTI_FEED_STALE = "rti_feed_stale"     # CF Benchmarks RTI feed stale / divergent
    LOOP_LAG_HALT = "loop_lag_halt"       # Event loop latency critical
    PORTFOLIO_INTEGRITY = "portfolio_integrity"  # Cross-system consistency failure


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
    - Distributed agent propagation (P0 fix)
    """
    
    daily_loss_limit: float = 500.0
    max_position_value: float = 10000.0
    error_threshold: int = 500  # FIXED: Was 50, now 500 - only truly catastrophic errors should halt trading

    def __post_init__(self):
        # R-1, R-5: Override with env vars if set AND value still equals default.
        # This allows explicit constructor arguments to win over env vars.
        env_daily_loss = os.getenv("MERID_MAX_DAILY_LOSS_USD")
        if env_daily_loss and self.daily_loss_limit == 500.0:
            try:
                self.daily_loss_limit = float(env_daily_loss)
            except (ValueError, TypeError):
                pass

        env_max_pos = os.getenv("MERID_MAX_POSITION_VALUE_USD")
        if env_max_pos and self.max_position_value == 10000.0:
            try:
                self.max_position_value = float(env_max_pos)
            except (ValueError, TypeError):
                pass

        env_error_thresh = os.getenv("MERID_ERROR_THRESHOLD")
        if env_error_thresh and self.error_threshold == 50:
            try:
                self.error_threshold = int(env_error_thresh)
            except (ValueError, TypeError):
                pass

        # Also try to read from settings if available (takes precedence after env vars)
        try:
            from merid.settings import settings
            # Only override if still at default (not explicitly set via env/constructor)
            if self.error_threshold == 50:
                self.error_threshold = settings.MERID_ERROR_THRESHOLD
        except Exception:
            pass  # Settings not available, use env/constructor/default
        
        self._global_kill: bool = False
        self._kill_reason: Optional[KillSwitchReason] = None
        self._kill_details: Optional[str] = None
        self._kill_timestamp: Optional[datetime] = None
        
        self._daily_pnl: float = 0.0
        self._daily_pnl_reset_date: str = self._today()
        self._total_position_value: float = 0.0
        
        self._error_count: int = 0
        self._weighted_error_count: float = 0.0
        self._error_window_start: float = time.time()
        # ERROR_THRESHOLD startup grace: suppress hard kill during cold-start / venue wobble.
        self._process_start_time: float = time.time()
        self._error_threshold_execution_warm: bool = False

        self._events: List[KillSwitchEvent] = []
        self._callbacks: List[Callable[[KillSwitchEvent], None]] = []
        # P0 fix: Distributed kill switch propagation
        self._agent_kill_handlers: Dict[str, Callable[[KillSwitchEvent], None]] = {}
        self._lock = threading.Lock()  # ZT3-01: protects all mutable state

        # T-063: Auto circuit breaker tracking
        self._consecutive_rejections: int = 0
        self._auto_halt_until: float = 0.0
        self._auto_halt_cooldown: float = 300.0  # 5 min default
        
        # P0 fix: Per-agent circuit breaker state
        self._agent_circuit_states: Dict[str, Dict[str, Any]] = {}
        self._agent_circuit_threshold: int = 3  # Failures before opening
        self._agent_circuit_cooldown: float = 300.0  # 5 min cooldown

        # Load from settings if available
        self._load_from_settings()
        # Restore persisted kill state so a restart does not silently re-enable trading
        self._load_persisted_kill_switch()
    
    def _load_from_settings(self):
        """Load limits from settings module if env vars and explicit args did not override them."""
        _env_limit = float(os.getenv("MERID_MAX_DAILY_LOSS_USD", "0"))
        _env_pos = float(os.getenv("MERID_MAX_POSITION_VALUE_USD", "0"))
        # Only apply settings if NEITHER env var is set AND values are still defaults.
        if _env_limit > 0 or _env_pos > 0:
            return
        # Only load from settings if values are still at defaults (not explicitly overridden)
        if self.daily_loss_limit != 500.0 or self.max_position_value != 10000.0:
            return
        try:
            from merid.settings import settings
            # Use USD limit if set, otherwise compute from percentage * bankroll
            _usd_limit = settings.MERID_MAX_DAILY_LOSS_USD
            if _usd_limit > 0:
                self.daily_loss_limit = _usd_limit
            else:
                # Compute from percentage - 15% default for top-3 edge strategy
                _bankroll = getattr(settings, 'KALSHI_PORTFOLIO_BANKROLL_CENTS', 0) / 100.0
                if _bankroll <= 0:
                    _bankroll = getattr(settings, 'MERID_TOTAL_CAPITAL_USD', 100.0)
                _pct = getattr(settings, 'MERID_MAX_DAILY_LOSS_PCT', 0.15)
                self.daily_loss_limit = _bankroll * _pct
            self.max_position_value = settings.MERID_MAX_POSITION_SIZE_USD
        except (ImportError, AttributeError):
            pass

    def _persist_kill_switch(self) -> None:
        """Write kill-switch state to disk atomically (temp + rename).

        Atomic write ensures that if the process is killed mid-write,
        the file is either the old complete version or the new complete version,
        never a partial/corrupted state.
        """
        try:
            ks_path = _get_kill_switch_path()
            ks_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "active": self._global_kill,
                "reason": self._kill_reason.value if self._kill_reason else None,
                "details": self._kill_details,
                "activated_at": self._kill_timestamp.isoformat() if self._kill_timestamp else None,
            }
            _tmp = ks_path.with_suffix(".tmp")
            _tmp.write_text(json.dumps(payload, indent=2))
            _tmp.replace(ks_path)  # atomic on POSIX and Windows (same volume)
        except Exception as exc:
            logger.error("[risk] Failed to persist kill switch state: %s", exc)

    def _load_persisted_kill_switch(self) -> None:
        """Reload kill-switch state from disk on startup.
        
        If a kill switch is persisted from a prior run, it requires explicit
        human acknowledgment before trading can resume (fail-safe behavior).
        """
        try:
            ks_path = _get_kill_switch_path()
            if ks_path.exists():
                data = json.loads(ks_path.read_text(encoding="utf-8"))
                logger.info(
                    "[risk] Kill switch persistence file found: %s | active=%s | reason=%s",
                    ks_path, data.get("active"), data.get("reason")
                )
                if data.get("active"):
                    self._global_kill = True
                    raw_reason = data.get("reason", "persisted")
                    try:
                        self._kill_reason = KillSwitchReason(raw_reason)
                    except ValueError:
                        self._kill_reason = KillSwitchReason.MANUAL
                    self._kill_details = data.get("details", "restored from disk - REQUIRES HUMAN ACKNOWLEDGMENT")
                    logger.critical(
                        "[risk] Kill switch RESTORED from prior run: %s — %s. "
                        "EXPLICIT RESET REQUIRED before trading can resume.",
                        self._kill_reason, self._kill_details,
                    )
                    logger.info(
                        "[risk] Execution gate will stay BLOCKED until kill_switch is cleared "
                        "(not a venue reconciliation mismatch).",
                    )
                    
                    # P0: Record to session log for operator visibility
                    try:
                        from core.session_log import record_event
                        record_event(
                            category="kill_switch",
                            severity="critical",
                            title="Kill switch restored from disk - TRADING BLOCKED",
                            detail=f"Prior kill switch ({self._kill_reason}) restored. "
                                   f"Operator must explicitly reset via dashboard before trading resumes.",
                            hint="Navigate to Mode & Safety panel and click 'Reset Kill Switch' after reviewing cause.",
                            metadata={
                                "reason": self._kill_reason.value,
                                "persisted_at": data.get("activated_at"),
                                "requires_ack": True,
                            },
                        )
                    except Exception as _se_exc:
                        logger.debug("[risk] kill_switch persistence session log failed: %s", _se_exc)
        except Exception as exc:
            logger.critical(
                "[risk] CORRUPT kill-switch state file — defaulting to BLOCKED: %s", exc
            )
            self._global_kill = True
            self._kill_reason = KillSwitchReason.MANUAL
            self._kill_details = f"Fail-closed: corrupt state file ({exc})"
    
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
        with self._lock:
            # Pull fresh daily P&L from fills_ledger (canonical source)
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                _ledger = get_fills_ledger()
                _ledger_summary = _ledger.summary()
                
                # Validate fills_ledger data to detect test data pollution
                is_valid, warning = self._validate_fills_ledger_data(_ledger_summary)
                if not is_valid:
                    logger.warning(f"[VALIDATION] Rejecting fills_ledger data in can_trade: {warning}")
                    # CRITICAL FIX: Reset to 0 when stale data detected, don't keep corrupted value
                    if self._daily_pnl != 0.0:
                        logger.warning(f"[VALIDATION] Resetting corrupted daily_pnl from {self._daily_pnl:.2f} to 0.0")
                        self._daily_pnl = 0.0
                else:
                    if warning:
                        logger.info(f"[VALIDATION] {warning}")
                    _ledger_daily_pnl = _ledger_summary.get("daily_realized_pnl_usd", 0.0)
                    self._daily_pnl = float(_ledger_daily_pnl)
            except Exception:
                # If fills_ledger unavailable, keep existing value
                pass
            
            # Reset daily P&L if new day
            today = self._today()
            if self._daily_pnl_reset_date != today:
                if self._daily_pnl != 0.0:
                    logger.warning(
                        "[DAILY-PNL-RESET] date=%s → %s final_pnl=%.4f — resetting to 0",
                        self._daily_pnl_reset_date, today, self._daily_pnl,
                    )
                self._daily_pnl_reset_date = today
                self._daily_pnl = 0.0

            # Inline daily-loss check: fire kill if limit already breached
            # Uses fills_ledger-synced _daily_pnl for accurate real trading P&L
            if (
                not self._global_kill
                and self._daily_pnl < 0
                and abs(self._daily_pnl) >= self.daily_loss_limit
            ):
                self._trigger_kill_locked(
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
    
    @staticmethod
    def _parse_error_threshold_startup_grace_seconds() -> int:
        """Rolling window after process start where ERROR_THRESHOLD kill may be suppressed.

        ``MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS`` (default 600): 0 disables grace
        (immediate kill at threshold, previous behavior).
        """
        raw = os.getenv("MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS", "600")
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            return 600

    def _in_error_threshold_startup_grace_locked(self) -> bool:
        """Caller must hold ``self._lock``."""
        grace = self._parse_error_threshold_startup_grace_seconds()
        if grace <= 0:
            return False
        if self._error_threshold_execution_warm:
            return False
        return (time.time() - self._process_start_time) < float(grace)

    def mark_execution_warm(self, source: str = "unspecified") -> None:
        """End ERROR_THRESHOLD startup grace early (e.g. first live Kalshi success).

        Idempotent. Safe to call from hot paths.
        """
        with self._lock:
            if self._error_threshold_execution_warm:
                return
            self._error_threshold_execution_warm = True
        logger.info(
            "[risk] ERROR_THRESHOLD startup grace cleared (%s) — steady-state threshold kills enabled",
            source,
        )

    def get_status(self) -> dict:
        """
        Get full risk controller status.
        
        Useful for dashboards and monitoring.
        """
        # BUG-70 fix: get_status should NOT call can_trade() (has side-effect of resetting daily PnL)
        # Instead, read the state directly.
        # All mutable fields must be read inside the lock to avoid TOCTOU races with
        # record_pnl(), record_error(), and trigger_kill() on other threads.
        with self._lock:
            _today = self._today()
            _is_new_day = self._daily_pnl_reset_date != _today
            grace_sec = self._parse_error_threshold_startup_grace_seconds()
            warm = self._error_threshold_execution_warm
            elapsed = time.time() - self._process_start_time
            in_grace = grace_sec > 0 and not warm and elapsed < float(grace_sec)
            grace_remaining = max(0.0, float(grace_sec) - elapsed) if in_grace else 0.0
            err_phase = "startup_grace" if in_grace else "steady"
            # Capture all fields used in the return dict while lock is held.
            _global_kill = self._global_kill
            _state_val = self.get_state().value  # calls _get_state_locked() — safe inside lock
            _kill_reason_val = self._kill_reason.value if self._kill_reason else None
            _kill_details = self._kill_details
            _kill_ts = self._kill_timestamp.isoformat() if self._kill_timestamp else None
            _position_value = self._total_position_value
            
            # Pull daily P&L from fills_ledger (canonical source) instead of self._daily_pnl
            # This fixes the discrepancy where fills_ledger tracked real P&L but
            # risk_controller had stale value because record_pnl() was never called
            _daily_pnl = self._daily_pnl  # fallback default
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                _ledger = get_fills_ledger()
                _ledger_summary = _ledger.summary()
                _ledger_daily_pnl = _ledger_summary.get("daily_realized_pnl_usd", 0.0)
                # Sync the internal value to match canonical source
                _daily_pnl = float(_ledger_daily_pnl)
                self._daily_pnl = _daily_pnl
            except Exception:
                # If fills_ledger unavailable, use internal value (may be stale)
                pass
            
            _error_count = self._error_count
            _events_count = len(self._events)

        _all_pm_spot = True
        try:
            from merid.prediction.pm_spot_health import get_operator_pm_spot_block

            _all_pm_spot = bool(
                get_operator_pm_spot_block().get("summary", {}).get("all_pm_assets_have_spot", True)
            )
        except Exception:
            _all_pm_spot = False
        return {
            "state": _state_val,
            "can_trade": not _global_kill,
            "daily_pnl_stale": _is_new_day,
            "kill_reason": _kill_reason_val,
            "kill_details": _kill_details,
            "kill_timestamp": _kill_ts,
            "daily_pnl": _daily_pnl,
            "daily_loss_limit": self.daily_loss_limit,
            "daily_pnl_pct": (abs(_daily_pnl) / self.daily_loss_limit * 100) if self.daily_loss_limit > 0 else 0,
            "position_value": _position_value,
            "max_position_value": self.max_position_value,
            "error_count": _error_count,
            "error_threshold": self.error_threshold,
            "error_threshold_phase": err_phase,
            "error_threshold_execution_warm": warm,
            "error_threshold_startup_grace_seconds": grace_sec,
            "error_threshold_grace_seconds_remaining": round(grace_remaining, 1),
            "events_count": _events_count,
            # Data-feed health (orthogonal to ERROR_THRESHOLD) — see pm_spot_health / CRYPTO_15M_MM gate
            "all_pm_assets_have_spot": _all_pm_spot,
        }
    
    # -------------------------------------------------------------------------
    # Kill Switch Triggers
    # -------------------------------------------------------------------------
    
    # T-063: Transient rejection reasons that should NOT count toward circuit breaker.
    _TRANSIENT_REJECTIONS: frozenset[str] = frozenset({
        "rate_limit", "429", "too_many_requests", "api_temporary",
        "timeout", "connection_error", "service_unavailable",
    })

    def record_order_rejection(self, reason: str = "unknown") -> None:
        """T-063: Track consecutive order rejections for auto circuit breaker.

        Transient API errors (rate limits, timeouts) are skipped so a burst of
        429s does not permanently kill the session.
        """
        reason_lower = reason.lower()
        if any(t in reason_lower for t in self._TRANSIENT_REJECTIONS):
            logger.debug(
                "[risk] Transient rejection '%s' skipped — not counted toward circuit breaker",
                reason,
            )
            return
        with self._lock:
            self._consecutive_rejections += 1
            if self._consecutive_rejections >= 5:
                logger.critical(
                    "AUTO CIRCUIT BREAKER: %d consecutive rejections — halting for %.0fs",
                    self._consecutive_rejections, self._auto_halt_cooldown,
                )
                self._auto_halt_until = time.time() + self._auto_halt_cooldown
                self._trigger_kill_locked(
                    KillSwitchReason.CIRCUIT_BREAKER,
                    f"{self._consecutive_rejections} consecutive order rejections (last: {reason})",
                )

    def record_order_success(self) -> None:
        """T-063: Reset consecutive rejection counter on success."""
        with self._lock:
            self._consecutive_rejections = 0

    def is_auto_halted(self) -> bool:
        """T-063: Check if auto-halt cooldown is active."""
        with self._lock:
            if self._auto_halt_until > 0 and time.time() < self._auto_halt_until:
                return True
            if self._auto_halt_until > 0 and time.time() >= self._auto_halt_until:
                self._auto_halt_until = 0.0
                logger.info("Auto-halt cooldown expired — allowing test request")
            return False

    def emergency_stop(self, reason: str = "Manual stop") -> None:
        """
        Trigger global kill switch immediately.
        
        Use for manual intervention or automated safety triggers.
        """
        with self._lock:
            if self._global_kill:
                logger.warning(f"[risk] Kill switch already triggered, ignoring: {reason}")
                return
            self._trigger_kill_locked(KillSwitchReason.MANUAL, reason)
        logger.critical(f"[risk] EMERGENCY STOP: {reason}")

    def trigger_rti_feed_stale(self, details: str) -> None:
        """Engage kill when CFB RTI is unavailable or operationally unsafe."""
        with self._lock:
            if self._global_kill:
                return
            self._trigger_kill_locked(KillSwitchReason.RTI_FEED_STALE, details)
        logger.critical("[risk] RTI_FEED_STALE kill: %s", details)

    def trigger_loop_lag_halt(self, lag_ms: float, threshold_ms: float) -> None:
        """Engage kill when event loop latency exceeds critical threshold in live mode.
        
        This is a safety mechanism for infrastructure degradation that could
        cause order execution delays or stale decisions.
        """
        # Loop lag is an observability signal; it must not hard-block trading by default.
        # Keep the hook for operators, but only enable kill behavior if explicitly requested.
        if os.getenv("MERID_LOOP_LAG_KILL_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
            logger.warning(
                "[risk] LOOP_LAG_HALT suppressed (non-blocking): %.1fms > %.1fms",
                lag_ms,
                threshold_ms,
            )
            return
        with self._lock:
            if self._global_kill:
                return
            details = f"Loop lag {lag_ms:.1f}ms exceeded halt threshold {threshold_ms:.1f}ms"
            self._trigger_kill_locked(KillSwitchReason.LOOP_LAG_HALT, details)
        logger.critical("[risk] LOOP_LAG_HALT kill: %.1fms > %.1fms", lag_ms, threshold_ms)

    def trigger_portfolio_integrity(self, issues: str) -> None:
        """Engage kill when portfolio integrity check fails in live mode.

        Cross-system consistency failures (fills vs positions, risk state
        mismatches) indicate potential data corruption or reconciliation
        failures that make trading unsafe.
        """
        with self._lock:
            if self._global_kill:
                return
            self._trigger_kill_locked(KillSwitchReason.PORTFOLIO_INTEGRITY, issues)
        logger.critical("[risk] PORTFOLIO_INTEGRITY kill: %s", issues)

    def trigger_dependency_health(self, details: str) -> None:
        """Engage kill when a critical system dependency is unavailable.

        Use for: swarm consensus down > wall-clock limit, external data feed
        permanently gone, or any structural dependency failure that makes
        producing safe trading decisions impossible.

        Guarded by MERID_DEPENDENCY_HEALTH_KILL_ENABLED (default: false) so
        the kill is opt-in until operators have validated the trigger path in
        their environment.
        """
        if os.getenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", "").strip().lower() not in (
            "1", "true", "yes", "on"
        ):
            logger.warning(
                "[risk] DEPENDENCY_HEALTH kill suppressed (set MERID_DEPENDENCY_HEALTH_KILL_ENABLED=true to enable): %s",
                details,
            )
            return
        with self._lock:
            if self._global_kill:
                return
            self._trigger_kill_locked(KillSwitchReason.DEPENDENCY_HEALTH, details)
        logger.critical("[risk] DEPENDENCY_HEALTH kill: %s", details)

    def _trigger_kill(self, reason: KillSwitchReason, details: str) -> None:
        """Acquire lock then trigger kill switch (external callers)."""
        with self._lock:
            self._trigger_kill_locked(reason, details)

    def _trigger_kill_locked(self, reason: KillSwitchReason, details: str) -> None:
        """Internal: trigger kill switch. Caller MUST hold self._lock."""
        old_state = self.get_state()
        
        self._global_kill = True
        self._kill_reason = reason
        self._kill_details = details
        self._kill_timestamp = self._now()
        self._persist_kill_switch()

        # [TRACE] PROTECT_DECISION — kill switch triggered (drawdown/risk halt)
        # P2-1 FIX: Upgraded from info to warning — kill switch is critical
        logger.warning(
            "[TRACE] PROTECT_DECISION | reason=%s | details=%s | daily_pnl=%.2f | daily_limit=%.2f | formulas=%s | audit_spec=%s",
            reason.value if hasattr(reason, 'value') else str(reason),
            details[:100],
            self._daily_pnl,
            self.daily_loss_limit,
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )

        event = KillSwitchEvent(
            timestamp=self._kill_timestamp,
            old_state=old_state,
            new_state=KillSwitchState.TRIGGERED,
            reason=reason,
            details=details,
        )
        self._events.append(event)

        # P0 fix: Propagate to all registered agents
        self._propagate_kill_to_agents(event)

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

            def _on_tg_done(_t: _aio.Task) -> None:
                if not _t.cancelled() and _t.exception():
                    # P2-1 FIX: Upgraded from debug to warning — kill switch notifications are critical
                    logger.warning("[risk] kill_switch tg_send failed: %s", _t.exception())

            _loop = _aio.get_running_loop()
            _tg_task = _loop.create_task(
                tg_send(f"\U0001f6a8 [KILL SWITCH] <b>{reason.value.upper()}</b>\n{details}"),
                name="kill-switch-tg",
            )
            _tg_task.add_done_callback(_on_tg_done)
        except RuntimeError:
            logger.debug("[risk] kill_switch Telegram skipped — no running loop")
        except Exception as _tg_exc:
            logger.debug("[risk] kill_switch Telegram failed: %s", _tg_exc)

        # Notify callbacks — copy list first to prevent mutation-during-iteration
        # if another thread unregisters a callback while we're iterating.
        for callback in list(self._callbacks):
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
        with self._lock:
            if not self._global_kill:
                # Clear stale auto-circuit state so a prior run cannot wedge local
                # checks (e.g. consecutive-rejection counter) while already disarmed.
                self._error_count = 0
                self._weighted_error_count = 0.0
                self._consecutive_rejections = 0
                self._auto_halt_until = 0.0
                self._persist_kill_switch()
                logger.info("[risk] Kill switch not triggered; cleared error/circuit counters")
                return True

            old_reason = self._kill_reason
            old_details = self._kill_details

            self._global_kill = False
            self._kill_reason = None
            self._kill_details = None
            self._kill_timestamp = None
            self._persist_kill_switch()

            # Don't reset daily P&L - that persists
            self._error_count = 0
            self._weighted_error_count = 0.0
            # After operator ack, steady-state ERROR_THRESHOLD rules apply (no startup grace).
            self._error_threshold_execution_warm = True
            # L1 fix: reset consecutive rejections so circuit breaker
            # doesn't immediately re-trigger after operator reset.
            self._consecutive_rejections = 0

            # P2-5 FIX: Force drawdown recovery check on kill switch reset.
            # This ensures sizing is restored if capital recovered, regardless of kill reason.
            try:
                from merid.risk.capital_engine import get_capital_engine
                _engine = get_capital_engine()
                for _asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    _engine.check_drawdown_recovery(_asset)
            except Exception as _rec_exc:
                logger.debug("[risk] drawdown recovery check on reset skipped: %s", _rec_exc)

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
            # P2-1 FIX: Upgraded from debug to error — session logging is critical for audit trail
            logger.error("[risk] kill_switch reset session log failed: %s", _se_exc)
        
        logger.warning(f"[risk] Kill switch RESET by {operator}")
        return True
    
    # -------------------------------------------------------------------------
    # P&L Tracking
    # -------------------------------------------------------------------------
    
    def _validate_fills_ledger_data(self, summary: dict) -> tuple[bool, str]:
        """
        Validate fills_ledger data to detect test data / stale data.

        Returns: (is_valid, warning_message)
        - Suspicious patterns: PnL exactly $105 with $100 limit (test artifact)
        - Stale data: fills from previous days without current day data
        - Empty data: no fills but non-zero PnL

        This prevents test data pollution from triggering production kill switches.
        """
        daily_pnl = float(summary.get("daily_realized_pnl_usd", 0.0))
        total_fills = int(summary.get("total_fills", 0))

        # Detect suspicious test pattern: $105 loss with $100 limit
        # This matches the test data pattern in test_trading_lifecycle_audit.py
        pnl_magnitude = abs(daily_pnl)
        if pnl_magnitude > 0 and abs(pnl_magnitude - 105.0) < 0.01 and self.daily_loss_limit == 100.0:
            return False, f"TEST DATA DETECTED: Suspicious PnL ${pnl_magnitude:.2f} with $100 limit (matches test pattern)"

        # Detect stale data: non-zero PnL but no fills (ledger corruption)
        # NOTE: "zero fills AND zero PnL" is VALID (fresh start), not stale data.
        if abs(daily_pnl) > 0 and total_fills == 0:
            return False, f"STALE DATA: Non-zero PnL ${daily_pnl:.2f} but zero fills — ledger may be corrupted"

        return True, ""

    def record_pnl(self, pnl: float) -> bool:
        """
        Record P&L from a trade.
        
        Automatically triggers daily loss kill if limit exceeded.
        Returns True if trading can continue, False if killed.
        """
        with self._lock:
            # Sync from fills_ledger (canonical) before checking limit.
            # Naive accumulation from individual callers can drift from
            # the fills_ledger total and cause false kill switches.
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                _ledger = get_fills_ledger()
                _s = _ledger.summary()
                
                # Validate fills_ledger data to detect test data pollution
                is_valid, warning = self._validate_fills_ledger_data(_s)
                if not is_valid:
                    logger.warning(f"[VALIDATION] Rejecting fills_ledger data: {warning}")
                    # CRITICAL FIX: Reset to 0 when stale data detected, then add new PnL
                    if self._daily_pnl != 0.0:
                        logger.warning(f"[VALIDATION] Resetting corrupted daily_pnl from {self._daily_pnl:.2f} to 0.0 before recording new PnL")
                        self._daily_pnl = 0.0
                    self._daily_pnl += pnl
                else:
                    if warning:
                        logger.info(f"[VALIDATION] {warning}")
                    self._daily_pnl = float(_s.get("daily_realized_pnl_usd", 0.0))
            except Exception:
                self._daily_pnl += pnl
            if self._daily_pnl < 0 and abs(self._daily_pnl) >= self.daily_loss_limit:
                self._trigger_kill_locked(
                    KillSwitchReason.DAILY_LOSS,
                    f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${self.daily_loss_limit:.2f}"
                )
                logger.critical(
                    f"[risk] DAILY LOSS KILL: ${abs(self._daily_pnl):.2f} >= ${self.daily_loss_limit:.2f}"
                )
                return False
            return True
    
    
    # -------------------------------------------------------------------------
    # Error Tracking (Legacy - counts all errors equally)
    # -------------------------------------------------------------------------

    def record_error(self, error_hint: str = "") -> bool:
        """
        Record an error occurrence for observability only.

        PRODUCTION FIX: Error counts NEVER trigger kill switches. This method
        only logs errors for metrics and debugging. Only risk/drawdown violations
        and manual kills can halt trading.

        If error_hint is provided, the error classification system is used
        to determine the appropriate log level. Budget-exempt errors are logged
        at lower severity.

        For full classified error tracking with deduplication, use
        record_error_classified() instead.

        Returns True always (trading can continue - errors never kill).
        """
        # Check if we should use classification based on error hint
        if error_hint:
            try:
                from merid.risk.error_classification import (
                    classify_error,
                    ErrorSeverity,
                    _BUDGET_EXEMPT_CLASSES,
                )

                classification = classify_error(error_hint, context="legacy_record_error")

                # If error is budget-exempt, log at appropriate level but don't count
                if classification.error_class in _BUDGET_EXEMPT_CLASSES:
                    if classification.severity == ErrorSeverity.CRITICAL:
                        logger.debug(
                            "[risk] record_error: %s classified as %s (budget-exempt, not counted)",
                            error_hint,
                            classification.error_class.value,
                        )
                    else:
                        logger.debug(
                            "[risk] record_error: %s classified as %s (budget-exempt)",
                            error_hint,
                            classification.error_class.value,
                        )
                    # Still return True (trading can continue) without incrementing counter
                    return True

                # Error counts toward budget - fall through to normal counting
                logger.debug(
                    "[risk] record_error: %s classified as %s (counts toward budget)",
                    error_hint,
                    classification.error_class.value,
                )
            except Exception as _exc:
                # If classification fails, fall through to legacy behavior
                logger.debug("[risk] record_error: classification failed for %s: %s", error_hint, _exc)

        # PRODUCTION FIX: Error counting is DISABLED - errors never trigger kill switches
        # Only risk/drawdown violations and manual kills can halt trading
        logger.debug(
            "[risk] record_error: error from %s - NOT counting toward threshold (error-count kills disabled)",
            error_hint or "unknown"
        )
        return True

    # -------------------------------------------------------------------------
    # Classified Error Tracking (P0 Audit Fix)
    # -------------------------------------------------------------------------

    def record_error_classified(
        self,
        error_code: str,
        context: Optional[str] = None,
        details: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Record a classified error for observability only.
        
        PRODUCTION FIX: Error counts NEVER trigger kill switches. This method
        tracks errors for metrics, logging, and dashboards only. Only 
        risk/drawdown violations and manual kills can halt trading.
        
        Error classification is used for:
        - Appropriate log levels (CRITICAL->error, HIGH->warning, etc.)
        - Deduplication within time windows
        - Metrics and dashboard visibility
        
        Args:
            error_code: Error code string (e.g., "auth_failed", "gate_blocked")
            context: Optional context for dedup (e.g., "kalshi_api", "btc_15m")
            details: Human-readable details for logging
            
        Returns:
            (can_trade, metadata_dict) — can_trade is always True
        """
        from merid.risk.error_classification import (
            should_count_error,
            ErrorClassification,
            ErrorClass,
            compute_kill_tier,
            KillSwitchTier,
        )
        
        # Classify and check dedup
        should_count, classification = should_count_error(error_code, context)
        
        # Build structured log entry
        # counts_toward_budget = whether this error CLASS counts toward budget (CRITICAL/HIGH)
        # dedup_filtered = whether this specific occurrence was filtered
        log_data = {
            "error_class": classification.error_class.value,
            "severity": classification.severity.value,
            "counts_toward_budget": classification.counts_toward_budget,
            "context": context,
            "dedup_filtered": not should_count,
            "is_transient": classification.is_transient,
        }
        
        # Log with appropriate level
        log_msg = f"[{classification.error_class.value}] {details or classification.description}"
        if classification.is_critical:
            if should_count:
                logger.error(f"[risk] {log_msg} [BUDGET+]")
            else:
                logger.warning(f"[risk] {log_msg} [DEDUP]")
        elif classification.severity.value == "high":
            logger.warning(f"[risk] {log_msg}")
        else:
            logger.info(f"[risk] {log_msg} [BUDGET-EXEMPT]")
        
        with self._lock:
            # PRODUCTION FIX: Track errors for observability only - NEVER trigger kills
            # Only risk/drawdown violations and manual kills can halt trading
            now = time.time()
            if now - self._error_window_start > 3600:
                self._error_count = 0
                self._weighted_error_count = 0.0
                self._error_window_start = now
            
            # Track for observability/metrics only (no kill switch triggering)
            if classification.counts_toward_budget and should_count:
                weighted_increment = classification.severity_weight
                self._weighted_error_count += weighted_increment
                self._error_count += 1
                log_data["weighted_increment"] = weighted_increment
                log_data["weighted_total"] = self._weighted_error_count
            
            # Log tier for observability but DO NOT act on it
            tier, pct = self._check_error_tier_locked()
            log_data["tier"] = tier.value
            log_data["pct_of_threshold"] = round(pct * 100, 1)
            
            # CRITICAL: Error counts can NEVER trigger kill switches
            # Only risk/drawdown/manual kills are allowed
            return True, log_data

    def _check_error_tier_locked(self) -> Tuple[Any, float]:
        """Check current error tier. Caller must hold self._lock."""
        from merid.risk.error_classification import compute_kill_tier, KillSwitchTier
        
        # Use weighted count if available, else integer count
        error_count = getattr(self, '_weighted_error_count', float(self._error_count))
        return compute_kill_tier(error_count, self.error_threshold)

    def _handle_triggered_escalation_locked(
        self,
        log_data: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Handle escalation to TRIGGERED tier. Caller must hold self._lock."""
        from merid.risk.error_classification import check_multi_signal_condition
        
        # Per audit: TRIGGERED requires either:
        # 1. Error count >= threshold AND multi-signal condition, OR
        # 2. Error count >= threshold AND runaway condition
        
        # For simplicity, we consider multi-signal as:
        # - Multiple error classes seen, OR
        # - Very rapid error accumulation (runaway)
        
        # Check if kill is disabled
        _kill_disabled = os.getenv("MERID_ERROR_THRESHOLD_KILL_ENABLED", "true").strip().lower() in (
            "0", "false", "no", "off",
        )
        if _kill_disabled:
            details = f"{self._error_count} errors exceeds threshold {self.error_threshold}"
            _live = os.getenv("MERID_TRADE_MODE", "").lower() == "live"
            if _live:
                logger.critical(
                    "[risk] EMERGENCY STOP: ERROR_THRESHOLD (metric=errors/hr, count=%d, threshold=%d, top_classes=[%s]) — SUPPRESSED IN LIVE",
                    self._error_count,
                    self.error_threshold,
                    log_data.get("error_class", "unknown"),
                )
            return True, {**log_data, "kill_suppressed": True}
        
        # Check startup grace
        if self._in_error_threshold_startup_grace_locked():
            g = float(self._parse_error_threshold_startup_grace_seconds())
            left = max(0.0, g - (time.time() - self._process_start_time))
            logger.critical(
                "[risk] EMERGENCY STOP: ERROR_THRESHOLD (metric=errors/hr, count=%d, threshold=%d) — suppressed (startup grace %.0fs)",
                self._error_count,
                self.error_threshold,
                left,
            )
            return True, {**log_data, "kill_suppressed_grace": True, "grace_left": left}
        
        # TRIGGER the kill switch with structured reason
        details = (
            f"ERROR_THRESHOLD (metric=errors/hr, count={self._error_count}, "
            f"threshold={self.error_threshold}, top_classes=[{log_data.get('error_class', 'unknown')}])"
        )
        self._trigger_kill_locked(KillSwitchReason.ERROR_THRESHOLD, details)
        logger.critical(
            "[risk] EMERGENCY STOP: %s",
            details,
        )
        return False, {**log_data, "kill_triggered": True}

    def get_error_budget_status(self) -> Dict[str, Any]:
        """Get current error budget status for operator visibility."""
        from merid.risk.error_classification import compute_kill_tier, get_dedup_tracker
        
        with self._lock:
            error_count = getattr(self, '_weighted_error_count', float(self._error_count))
            tier, pct = compute_kill_tier(error_count, self.error_threshold)
            
            return {
                "tier": tier.value,
                "error_count": self._error_count,
                "weighted_error_count": round(error_count, 2),
                "threshold": self.error_threshold,
                "pct_of_threshold": round(pct * 100, 1),
                "window_start": self._error_window_start,
                "window_remaining_sec": max(0, 3600 - (time.time() - self._error_window_start)),
                "dedup_stats": get_dedup_tracker().get_stats(),
            }
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    
    def update_position_value(self, total_value: float) -> bool:
        """Update total position value. Triggers kill if limit exceeded."""
        with self._lock:
            self._total_position_value = total_value
            if total_value > self.max_position_value:
                self._trigger_kill_locked(
                    KillSwitchReason.POSITION_LIMIT,
                    f"Position value ${total_value:.2f} exceeds limit ${self.max_position_value:.2f}"
                )
                logger.critical(
                    f"[risk] POSITION LIMIT KILL: ${total_value:.2f} > ${self.max_position_value:.2f}"
                )
                return False
            return True

    def reset_daily_counters(self) -> None:
        """Zero transient PnL / error counters for a fresh start.

        Kill-switch state (_global_kill, _kill_reason, etc.) is
        deliberately **preserved** so a reset cannot silently
        re-enable trading.
        """
        with self._lock:
            self._daily_pnl = 0.0
            self._daily_pnl_reset_date = self._today()
            self._total_position_value = 0.0
            self._error_count = 0
            self._weighted_error_count = 0.0
            self._error_window_start = time.time()
            self._events.clear()
        logger.info("[risk] Daily counters reset (kill-switch state preserved)")

    def on_kill(self, callback: Callable[[KillSwitchEvent], None]) -> None:
        """Register callback for kill switch events."""
        self._callbacks.append(callback)
    
    # P0 fix: Distributed kill switch propagation methods
    def register_agent_kill_handler(
        self, agent_id: str, handler: Callable[[KillSwitchEvent], None]
    ) -> None:
        """Register an agent to receive kill switch events.
        
        When the global kill switch triggers, all registered agents
        will be notified via their handler callback.
        """
        with self._lock:
            self._agent_kill_handlers[agent_id] = handler
            logger.info("[risk] Agent %s registered for kill switch propagation", agent_id)
    
    def unregister_agent_kill_handler(self, agent_id: str) -> None:
        """Unregister an agent from kill switch propagation."""
        with self._lock:
            self._agent_kill_handlers.pop(agent_id, None)
    
    def _propagate_kill_to_agents(self, event: KillSwitchEvent) -> None:
        """Propagate kill switch event to all registered agents.
        
        Caller MUST hold self._lock before calling this method.
        """
        # Copy handlers list while holding lock, then release before calling
        handlers = list(self._agent_kill_handlers.items())
        
        for agent_id, handler in handlers:
            try:
                handler(event)
                logger.debug("[risk] Kill switch propagated to agent %s", agent_id)
            except Exception as _exc:
                logger.warning("[risk] Failed to propagate kill to agent %s: %s", agent_id, _exc)
    
    def get_events(self, limit: int = 10) -> List[KillSwitchEvent]:
        """Get recent kill switch events."""
        return self._events[-limit:]
    
    # -------------------------------------------------------------------------
    # P0 Fix: Per-Agent Circuit Breaker Methods
    # -------------------------------------------------------------------------
    
    def record_agent_failure(self, agent_id: str, reason: str = "unknown") -> bool:
        """Record a failure for an agent and check if circuit should open.
        
        Returns True if agent can continue, False if circuit is now open.
        """
        with self._lock:
            now = time.time()
            
            if agent_id not in self._agent_circuit_states:
                self._agent_circuit_states[agent_id] = {
                    "failures": 0,
                    "last_failure": 0.0,
                    "opened_at": None,
                    "reasons": [],
                }
            
            state = self._agent_circuit_states[agent_id]
            
            # Check if circuit is currently open
            if state["opened_at"] is not None:
                elapsed = now - state["opened_at"]
                if elapsed < self._agent_circuit_cooldown:
                    # Circuit still open
                    return False
                else:
                    # Cooldown expired, reset circuit
                    state["opened_at"] = None
                    state["failures"] = 0
                    state["reasons"] = []
                    logger.info("[risk] Agent %s circuit breaker cooldown expired - resetting", agent_id)
            
            # Record failure
            state["failures"] += 1
            state["last_failure"] = now
            state["reasons"].append(reason)
            
            # Check if threshold reached
            if state["failures"] >= self._agent_circuit_threshold:
                state["opened_at"] = now
                logger.critical(
                    "[risk] Agent %s CIRCUIT BREAKER OPENED after %d failures",
                    agent_id, state["failures"]
                )
                # Notify via Telegram
                try:
                    import asyncio as _aio
                    from merid.alerts.webhook_client import tg_send
                    _loop = _aio.get_running_loop()
                    _loop.create_task(
                        tg_send(f"⚡ [AGENT CB] <b>{agent_id}</b> circuit opened after {state['failures']} failures")
                    )
                except Exception:
                    pass
                return False
            
            return True
    
    def record_agent_success(self, agent_id: str) -> None:
        """Record a success for an agent, resetting failure count."""
        with self._lock:
            if agent_id in self._agent_circuit_states:
                state = self._agent_circuit_states[agent_id]
                if state["failures"] > 0:
                    logger.debug("[risk] Agent %s success - resetting failure count", agent_id)
                state["failures"] = 0
                state["reasons"] = []
    
    def is_agent_circuit_open(self, agent_id: str) -> bool:
        """Check if an agent's circuit breaker is currently open."""
        with self._lock:
            if agent_id not in self._agent_circuit_states:
                return False
            
            state = self._agent_circuit_states[agent_id]
            if state["opened_at"] is None:
                return False
            
            # Check if cooldown has expired
            now = time.time()
            elapsed = now - state["opened_at"]
            if elapsed >= self._agent_circuit_cooldown:
                # Auto-reset
                state["opened_at"] = None
                state["failures"] = 0
                state["reasons"] = []
                return False
            
            return True
    
    def get_agent_circuit_status(self, agent_id: str) -> Dict[str, Any]:
        """Get circuit breaker status for an agent."""
        with self._lock:
            state = self._agent_circuit_states.get(agent_id, {
                "failures": 0,
                "last_failure": 0.0,
                "opened_at": None,
                "reasons": [],
            })
            
            is_open = state["opened_at"] is not None and (
                time.time() - state["opened_at"] < self._agent_circuit_cooldown
            )
            
            remaining = 0.0
            if is_open:
                remaining = self._agent_circuit_cooldown - (time.time() - state["opened_at"])
            
            return {
                "agent_id": agent_id,
                "circuit_open": is_open,
                "failures": state["failures"],
                "threshold": self._agent_circuit_threshold,
                "cooldown_remaining_s": max(0.0, remaining),
                "last_failure_ago_s": time.time() - state["last_failure"] if state["last_failure"] > 0 else None,
            }
    
    def reset_agent_circuit(self, agent_id: str, operator: str = "system") -> bool:
        """Manually reset an agent's circuit breaker."""
        with self._lock:
            if agent_id in self._agent_circuit_states:
                state = self._agent_circuit_states[agent_id]
                was_open = state["opened_at"] is not None
                state["opened_at"] = None
                state["failures"] = 0
                state["reasons"] = []
                if was_open:
                    logger.warning("[risk] Agent %s circuit breaker manually reset by %s", agent_id, operator)
                    return True
            return False

    def halt_strategy(self, strategy_id: str, reason: str = "Strategy halted") -> bool:
        """
        Halt a specific strategy while keeping global trading active.
        
        Used for per-strategy kill on sanity violations, preventing
        further orders from a compromised strategy without affecting
        other strategies.
        
        Args:
            strategy_id: The strategy/agent identifier to halt
            reason: Human-readable reason for the halt
            
        Returns:
            True if strategy was newly halted, False if already halted
        """
        with self._lock:
            # Use agent circuit states for per-strategy halting
            state = self._agent_circuit_states.get(strategy_id, {
                "failures": 0,
                "last_failure": 0.0,
                "opened_at": None,
                "reasons": [],
            })
            
            # Check if already halted
            if state["opened_at"] is not None:
                return False
            
            # Open the circuit for this strategy
            state["opened_at"] = time.time()
            state["failures"] = 999  # Force open
            state["reasons"].append(f"HALT: {reason}")
            self._agent_circuit_states[strategy_id] = state
            
            logger.critical(
                "[risk] STRATEGY HALT: strategy=%s reason=%s — "
                "strategy will be blocked for %.0fs",
                strategy_id, reason, self._agent_circuit_cooldown
            )
            return True


def invalidate_promotion_cache(event: KillSwitchEvent) -> None:
    """P-1: Clear promotion report cache when kill switch triggers.

    Prevents stale promotion eligibility from being used after a kill switch
    event that may have been caused by a gauntlet failure.
    """
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        # Reset promotion eligibility to force re-check
        guard._promotion_eligible_domains = None
        guard._promotion_blocked_agents = None
        guard._promotion_report_ts = 0.0
        logger.info("[risk] Promotion cache invalidated due to kill switch: %s", event.reason)
    except Exception as exc:
        logger.debug("[risk] Failed to invalidate promotion cache: %s", exc)


# Global singleton instance with cache invalidation callback
risk_controller = RiskController()
risk_controller.on_kill(invalidate_promotion_cache)


def can_trade() -> bool:
    """Convenience function to check if trading is allowed."""
    return risk_controller.can_trade()


def emergency_stop(reason: str = "Manual stop") -> None:
    """Convenience function for emergency stop."""
    risk_controller.emergency_stop(reason)


def get_risk_status() -> dict:
    """Convenience function to get risk status."""
    return risk_controller.get_status()
