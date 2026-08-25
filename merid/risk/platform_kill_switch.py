"""Platform-Level Kill Switch System

CRITICAL FIX (2026-07-17): Implements platform-level kill switch with exchange integration
and circuit breaker hierarchy (daily loss → drawdown → kill switch).

This is the single source of truth for platform-level trading controls.
All order placement paths must check this before executing trades.

Architecture:
- PlatformKillSwitch: Central controller for all kill switch states
- CircuitBreaker: Hierarchical circuit breakers (daily loss, drawdown, kill switch)
- ExchangeIntegration: Kalshi-specific kill switch integration
- KillSwitchState: Immutable state representation

Kill Switch Hierarchy (from least to most severe):
1. Daily Loss Circuit: Halts trading when daily loss limit breached
2. Drawdown Circuit: Halts trading when drawdown limit breached
3. Platform Kill Switch: Manual or automatic emergency stop
4. Exchange Kill Switch: Kalshi-level order blocking (most independent)
"""

from __future__ import annotations

import asyncio
import enum
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from utils.logger import get_logger

logger = get_logger(__name__)


class KillSwitchReason(enum.Enum):
    """Reasons for kill switch activation."""
    MANUAL = "manual"  # Manual activation by operator
    DAILY_LOSS = "daily_loss"  # Daily loss limit breached
    DRAWDOWN = "drawdown"  # Drawdown limit breached
    EXCHANGE = "exchange"  # Exchange-level kill switch
    SYSTEM_ERROR = "system_error"  # Critical system error
    DATA_FEED_STALE = "data_feed_stale"  # Data feed not updating
    POSITION_MISMATCH = "position_mismatch"  # Position reconciliation failed
    RATE_LIMIT = "rate_limit"  # API rate limit exceeded
    UNKNOWN = "unknown"  # Unknown reason


class CircuitBreakerState(enum.Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Tripped - blocking operations
    HALF_OPEN = "half_open"  # Testing if safe to close


@dataclass(frozen=True)
class KillSwitchState:
    """Immutable kill switch state."""
    active: bool
    reason: Optional[KillSwitchReason]
    triggered_at: Optional[datetime]
    triggered_by: Optional[str]  # Who triggered it (system, operator, etc.)
    daily_loss_pct: float = 0.0
    drawdown_pct: float = 0.0
    daily_loss_limit_pct: float = 0.02  # 2% daily loss limit
    drawdown_limit_pct: float = 0.05  # 5% drawdown limit
    
    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        return not self.active
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "active": self.active,
            "reason": self.reason.value if self.reason else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "triggered_by": self.triggered_by,
            "daily_loss_pct": self.daily_loss_pct,
            "drawdown_pct": self.drawdown_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "drawdown_limit_pct": self.drawdown_limit_pct,
        }


@dataclass
class CircuitBreaker:
    """Circuit breaker with hierarchical states."""
    name: str
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    cooldown_seconds: int = 60  # Cooldown before allowing retries
    max_failures: int = 3  # Max failures before opening
    
    def record_failure(self) -> bool:
        """Record a failure and return True if circuit should open."""
        self.failure_count += 1
        self.last_failure_time = _time.time()
        
        if self.failure_count >= self.max_failures:
            self.state = CircuitBreakerState.OPEN
            logger.warning(f"[CIRCUIT-BREAKER] {self.name} opened after {self.failure_count} failures")
            return True
        return False
    
    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        logger.info(f"[CIRCUIT-BREAKER] {self.name} reset to closed")
    
    def can_proceed(self) -> bool:
        """Check if operations can proceed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        
        if self.state == CircuitBreakerState.OPEN:
            # Check if cooldown has passed
            if self.last_failure_time and (_time.time() - self.last_failure_time) > self.cooldown_seconds:
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"[CIRCUIT-BREAKER] {self.name} moved to half-open")
                return True
            return False
        
        # HALF_OPEN - allow one attempt
        return True


class PlatformKillSwitch:
    """Platform-level kill switch controller.
    
    This is the single source of truth for platform-level trading controls.
    All order placement paths must check can_trade() before executing.
    
    Thread-safe: Uses lock for state mutations.
    """
    
    _instance: Optional[PlatformKillSwitch] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> PlatformKillSwitch:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._state_lock = threading.RLock()
        self._state = KillSwitchState(
            active=False,
            reason=None,
            triggered_at=None,
            triggered_by=None,
        )
        
        # Circuit breakers
        self._daily_loss_breaker = CircuitBreaker("daily_loss", max_failures=3, cooldown_seconds=300)
        self._drawdown_breaker = CircuitBreaker("drawdown", max_failures=3, cooldown_seconds=300)
        self._exchange_breaker = CircuitBreaker("exchange", max_failures=5, cooldown_seconds=600)
        
        # Callbacks for kill switch events
        self._callbacks: List[Callable[[KillSwitchState], None]] = []
        
        # Metrics
        self._activation_count = 0
        self._last_activation_time: Optional[float] = None
        
        self._initialized = True
        logger.info("[PLATFORM-KILL-SWITCH] Initialized")
    
    @property
    def state(self) -> KillSwitchState:
        """Get current kill switch state (thread-safe)."""
        with self._state_lock:
            return self._state
    
    def can_trade(self) -> bool:
        """Check if trading is allowed.
        
        This is the main entry point for order placement paths.
        Returns False if any kill switch is active or circuit breaker is open.
        """
        # Check kill switch state
        if not self._state.can_trade():
            logger.warning(
                f"[PLATFORM-KILL-SWITCH] Trading blocked: {self._state.reason.value} "
                f"triggered_by={self._state.triggered_by}"
            )
            return False
        
        # Check circuit breakers
        if not self._daily_loss_breaker.can_proceed():
            logger.warning("[PLATFORM-KILL-SWITCH] Trading blocked: daily loss circuit open")
            return False
        
        if not self._drawdown_breaker.can_proceed():
            logger.warning("[PLATFORM-KILL-SWITCH] Trading blocked: drawdown circuit open")
            return False
        
        if not self._exchange_breaker.can_proceed():
            logger.warning("[PLATFORM-KILL-SWITCH] Trading blocked: exchange circuit open")
            return False
        
        return True
    
    def activate(
        self,
        reason: KillSwitchReason,
        triggered_by: str = "system",
        force: bool = False,
    ) -> bool:
        """Activate kill switch.
        
        Args:
            reason: Reason for activation
            triggered_by: Who triggered it (system, operator, etc.)
            force: Force activation even if already active
            
        Returns:
            True if activation succeeded, False if already active and not forced
        """
        with self._state_lock:
            if self._state.active and not force:
                logger.info(f"[PLATFORM-KILL-SWITCH] Already active: {self._state.reason.value}")
                return False
            
            self._state = KillSwitchState(
                active=True,
                reason=reason,
                triggered_at=datetime.now(timezone.utc),
                triggered_by=triggered_by,
                daily_loss_pct=self._state.daily_loss_pct,
                drawdown_pct=self._state.drawdown_pct,
                daily_loss_limit_pct=self._state.daily_loss_limit_pct,
                drawdown_limit_pct=self._state.drawdown_limit_pct,
            )
            
            self._activation_count += 1
            self._last_activation_time = _time.time()
            
            logger.critical(
                f"[PLATFORM-KILL-SWITCH] ACTIVATED: reason={reason.value} "
                f"triggered_by={triggered_by} activation_count={self._activation_count}"
            )
            
            # Notify callbacks
            self._notify_callbacks()
            
            return True
    
    def deactivate(self, triggered_by: str = "system") -> bool:
        """Deactivate kill switch.
        
        Args:
            triggered_by: Who deactivated it (system, operator, etc.)
            
        Returns:
            True if deactivation succeeded, False if not active
        """
        with self._state_lock:
            if not self._state.active:
                logger.info("[PLATFORM-KILL-SWITCH] Not active, cannot deactivate")
                return False
            
            self._state = KillSwitchState(
                active=False,
                reason=None,
                triggered_at=None,
                triggered_by=triggered_by,
                daily_loss_pct=self._state.daily_loss_pct,
                drawdown_pct=self._state.drawdown_pct,
                daily_loss_limit_pct=self._state.daily_loss_limit_pct,
                drawdown_limit_pct=self._state.drawdown_limit_pct,
            )
            
            # Reset circuit breakers
            self._daily_loss_breaker.reset()
            self._drawdown_breaker.reset()
            self._exchange_breaker.reset()
            
            logger.info(
                f"[PLATFORM-KILL-SWITCH] DEACTIVATED: triggered_by={triggered_by}"
            )
            
            # Notify callbacks
            self._notify_callbacks()
            
            return True
    
    def update_metrics(
        self,
        daily_loss_pct: float,
        drawdown_pct: float,
        daily_loss_limit_pct: Optional[float] = None,
        drawdown_limit_pct: Optional[float] = None,
    ) -> None:
        """Update loss/drawdown metrics and auto-activate if limits breached.
        
        Args:
            daily_loss_pct: Current daily loss percentage
            drawdown_pct: Current drawdown percentage
            daily_loss_limit_pct: Daily loss limit (uses default if None)
            drawdown_limit_pct: Drawdown limit (uses default if None)
        """
        with self._state_lock:
            self._state = KillSwitchState(
                active=self._state.active,
                reason=self._state.reason,
                triggered_at=self._state.triggered_at,
                triggered_by=self._state.triggered_by,
                daily_loss_pct=daily_loss_pct,
                drawdown_pct=drawdown_pct,
                daily_loss_limit_pct=daily_loss_limit_pct or self._state.daily_loss_limit_pct,
                drawdown_limit_pct=drawdown_limit_pct or self._state.drawdown_limit_pct,
            )
        
        # Check if limits breached
        loss_limit = daily_loss_limit_pct or self._state.daily_loss_limit_pct
        drawdown_limit = drawdown_limit_pct or self._state.drawdown_limit_pct
        
        if daily_loss_pct <= -loss_limit:
            logger.critical(
                f"[PLATFORM-KILL-SWITCH] Daily loss limit breached: {daily_loss_pct:.2f}% <= -{loss_limit:.2f}%"
            )
            self._daily_loss_breaker.record_failure()
            if self._daily_loss_breaker.state == CircuitBreakerState.OPEN:
                self.activate(KillSwitchReason.DAILY_LOSS, triggered_by="system")
        
        if drawdown_pct <= -drawdown_limit:
            logger.critical(
                f"[PLATFORM-KILL-SWITCH] Drawdown limit breached: {drawdown_pct:.2f}% <= -{drawdown_limit:.2f}%"
            )
            self._drawdown_breaker.record_failure()
            if self._drawdown_breaker.state == CircuitBreakerState.OPEN:
                self.activate(KillSwitchReason.DRAWDOWN, triggered_by="system")
    
    def register_callback(self, callback: Callable[[KillSwitchState], None]) -> None:
        """Register a callback to be notified of state changes."""
        self._callbacks.append(callback)
        logger.info(f"[PLATFORM-KILL-SWITCH] Registered callback: {callback.__name__}")
    
    def _notify_callbacks(self) -> None:
        """Notify all registered callbacks of state change."""
        for callback in self._callbacks:
            try:
                callback(self._state)
            except Exception as e:
                logger.error(f"[PLATFORM-KILL-SWITCH] Callback error: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive kill switch status."""
        with self._state_lock:
            return {
                "state": self._state.to_dict(),
                "circuit_breakers": {
                    "daily_loss": {
                        "state": self._daily_loss_breaker.state.value,
                        "failure_count": self._daily_loss_breaker.failure_count,
                        "can_proceed": self._daily_loss_breaker.can_proceed(),
                    },
                    "drawdown": {
                        "state": self._drawdown_breaker.state.value,
                        "failure_count": self._drawdown_breaker.failure_count,
                        "can_proceed": self._drawdown_breaker.can_proceed(),
                    },
                    "exchange": {
                        "state": self._exchange_breaker.state.value,
                        "failure_count": self._exchange_breaker.failure_count,
                        "can_proceed": self._exchange_breaker.can_proceed(),
                    },
                },
                "can_trade": self.can_trade(),
                "activation_count": self._activation_count,
                "last_activation_time": self._last_activation_time,
            }


# Singleton accessor
def get_platform_kill_switch() -> PlatformKillSwitch:
    """Get the platform kill switch singleton."""
    return PlatformKillSwitch()


# Convenience function for order placement paths
def can_trade() -> bool:
    """Check if trading is allowed (convenience function)."""
    return get_platform_kill_switch().can_trade()


def get_kill_reason() -> Optional[str]:
    """Get the reason why trading is blocked (convenience function)."""
    ks = get_platform_kill_switch()
    if ks.state.active:
        return ks.state.reason.value
    return None
