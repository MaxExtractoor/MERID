"""Strip Order State Tracker for Anti-Spam Protection.

This module tracks open GTC/limit orders per market ticker to prevent
resting-order spamming in the 15m Kalshi crypto trading system.

Key invariants:
- No new entry orders if there is already a working order on that strip
- Per-strip order budget to prevent excessive order submission
- Exit-aware cooldown to block re-entries after problematic exits
- Spam detection logging for monitoring
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.prediction.strip_order_state")


class ExitReason(Enum):
    """Exit reasons that trigger cooldown."""
    STALEDATA = "stale_data"
    RISK_LIMIT = "risk_limit"
    LOW_LIQUIDITY = "low_liquidity"
    REGIME_HALTED = "regime_halted"
    NORMAL = "normal"


@dataclass
class WorkingOrder:
    """Record of a working (non-terminal) order on a strip."""
    order_id: str
    ticker: str
    side: str
    action: str
    price_cents: int
    created_at: float = field(default_factory=time.time)
    
    @property
    def age_seconds(self) -> float:
        """Age of this order in seconds."""
        return time.time() - self.created_at


@dataclass
class StripCooldown:
    """Cooldown state for a strip after a problematic exit."""
    ticker: str
    exit_reason: ExitReason
    cooldown_until: float
    triggered_at: float = field(default_factory=time.time)
    
    @property
    def is_active(self) -> bool:
        """Check if cooldown is still active."""
        return time.time() < self.cooldown_until
    
    @property
    def remaining_seconds(self) -> float:
        """Remaining cooldown time in seconds."""
        return max(0.0, self.cooldown_until - time.time())


class StripOrderState:
    """Tracker for open orders and cooldowns per market ticker.
    
    Thread-safe singleton that enforces:
    - Per-strip working order limits
    - Exit-aware cooldowns
    - Spam detection
    """
    
    _instance: Optional['StripOrderState'] = None
    _lock: threading.Lock = threading.Lock()
    
    # Configuration
    MAX_ORDERS_PER_STRIP = 1  # Only 1 working order per strip
    COOLDOWN_DURATION_SECONDS = 300  # 5 minutes for problematic exits
    COOLDOWN_EXIT_REASONS = {
        ExitReason.STALEDATA,
        ExitReason.RISK_LIMIT,
        ExitReason.LOW_LIQUIDITY,
        ExitReason.REGIME_HALTED,
    }
    SPAM_THRESHOLD_ORDERS_PER_MINUTE = 5  # Spam detection threshold
    
    def __new__(cls) -> 'StripOrderState':
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the strip order state tracker."""
        if self._initialized:
            return
        
        self._working_orders: Dict[str, WorkingOrder] = {}  # order_id -> WorkingOrder
        self._strip_to_order_ids: Dict[str, Set[str]] = {}  # ticker -> set of order_ids
        self._cooldowns: Dict[str, StripCooldown] = {}  # ticker -> StripCooldown
        self._order_history: Dict[str, List[float]] = {}  # ticker -> list of timestamps
        self._lock = threading.RLock()
        self._initialized = True
        
        logger.info("[STRIP-ORDER-STATE] Initialized StripOrderState singleton")
    
    def register_order(
        self,
        order_id: str,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
    ) -> bool:
        """Register a new working order.
        
        Args:
            order_id: Unique order identifier
            ticker: Market ticker
            side: Order side (yes/no)
            action: Order action (buy/sell)
            price_cents: Order price in cents
            
        Returns:
            True if order was registered, False if blocked by limits
        """
        with self._lock:
            # Check cooldown
            if self._is_cooldown_active(ticker):
                cooldown = self._cooldowns[ticker]
                logger.warning(
                    "[STRIP-COOLDOWN] ticker=%s blocked by cooldown (reason=%s, remaining=%.1fs)",
                    ticker, cooldown.exit_reason.value, cooldown.remaining_seconds
                )
                return False
            
            # Check per-strip order limit
            strip_orders = self._strip_to_order_ids.get(ticker, set())
            if len(strip_orders) >= self.MAX_ORDERS_PER_STRIP:
                logger.warning(
                    "[STRIP-ORDER-LIMIT] ticker=%s has %d working orders (max=%d) - blocking new order",
                    ticker, len(strip_orders), self.MAX_ORDERS_PER_STRIP
                )
                return False
            
            # Register the order
            working_order = WorkingOrder(
                order_id=order_id,
                ticker=ticker,
                side=side,
                action=action,
                price_cents=price_cents,
            )
            self._working_orders[order_id] = working_order
            self._strip_to_order_ids.setdefault(ticker, set()).add(order_id)
            
            # Track for spam detection
            now = time.time()
            self._order_history.setdefault(ticker, []).append(now)
            
            logger.info(
                "[STRIP-ORDER-REGISTER] order_id=%s ticker=%s side=%s action=%s price=%dc",
                order_id, ticker, side, action, price_cents
            )
            
            # Check for spam
            self._check_spam(ticker, now)
            
            return True
    
    def unregister_order(self, order_id: str) -> None:
        """Unregister an order (filled, canceled, or expired).
        
        Args:
            order_id: Order identifier to unregister
        """
        with self._lock:
            if order_id not in self._working_orders:
                return
            
            working_order = self._working_orders[order_id]
            ticker = working_order.ticker
            
            # Remove from strip mapping
            if ticker in self._strip_to_order_ids:
                self._strip_to_order_ids[ticker].discard(order_id)
                if not self._strip_to_order_ids[ticker]:
                    del self._strip_to_order_ids[ticker]
            
            # Remove from working orders
            del self._working_orders[order_id]
            
            logger.debug(
                "[STRIP-ORDER-UNREGISTER] order_id=%s ticker=%s",
                order_id, ticker
            )
    
    def set_cooldown(
        self,
        ticker: str,
        exit_reason: ExitReason,
        duration_seconds: Optional[int] = None,
    ) -> None:
        """Set a cooldown for a strip after a problematic exit.
        
        Args:
            ticker: Market ticker
            exit_reason: Reason for the exit
            duration_seconds: Custom cooldown duration (uses default if None)
        """
        if exit_reason not in self.COOLDOWN_EXIT_REASONS:
            return
        
        duration = duration_seconds or self.COOLDOWN_DURATION_SECONDS
        cooldown_until = time.time() + duration
        
        with self._lock:
            self._cooldowns[ticker] = StripCooldown(
                ticker=ticker,
                exit_reason=exit_reason,
                cooldown_until=cooldown_until,
            )
            
            logger.warning(
                "[STRIP-COOLDOWN-SET] ticker=%s reason=%s duration=%ds",
                ticker, exit_reason.value, duration
            )
    
    def clear_cooldown(self, ticker: str) -> None:
        """Clear cooldown for a strip.
        
        Args:
            ticker: Market ticker
        """
        with self._lock:
            if ticker in self._cooldowns:
                del self._cooldowns[ticker]
                logger.info("[STRIP-COOLDOWN-CLEAR] ticker=%s", ticker)
    
    def get_working_order_count(self, ticker: str) -> int:
        """Get the number of working orders for a strip.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Number of working orders
        """
        with self._lock:
            return len(self._strip_to_order_ids.get(ticker, set()))
    
    def has_working_order(self, ticker: str, side: Optional[str] = None) -> bool:
        """Check if a strip has any working orders (optionally filtered by side).
        
        Args:
            ticker: Market ticker
            side: Optional side filter
            
        Returns:
            True if working order exists
        """
        with self._lock:
            order_ids = self._strip_to_order_ids.get(ticker, set())
            if not order_ids:
                return False
            
            if side is None:
                return len(order_ids) > 0
            
            # Check if any order matches the side
            for order_id in order_ids:
                if order_id in self._working_orders:
                    if self._working_orders[order_id].side == side:
                        return True
            
            return False
    
    def _is_cooldown_active(self, ticker: str) -> bool:
        """Check if cooldown is active for a strip.
        
        Args:
            ticker: Market ticker
            
        Returns:
            True if cooldown is active
        """
        if ticker not in self._cooldowns:
            return False
        
        cooldown = self._cooldowns[ticker]
        if not cooldown.is_active:
            # Cooldown expired, clean it up
            del self._cooldowns[ticker]
            return False
        
        return True
    
    def _check_spam(self, ticker: str, now: float) -> None:
        """Check for spam patterns and log warnings.
        
        Args:
            ticker: Market ticker
            now: Current timestamp
        """
        if ticker not in self._order_history:
            return
        
        # Count orders in the last minute
        one_minute_ago = now - 60
        recent_orders = [
            ts for ts in self._order_history[ticker]
            if ts > one_minute_ago
        ]
        
        if len(recent_orders) >= self.SPAM_THRESHOLD_ORDERS_PER_MINUTE:
            logger.warning(
                "[STRIP-SPAM-WARNING] ticker=%s has %d orders in last 60s (threshold=%d) - possible spam pattern",
                ticker, len(recent_orders), self.SPAM_THRESHOLD_ORDERS_PER_MINUTE
            )
        
        # Clean old history (keep last 5 minutes)
        five_minutes_ago = now - 300
        self._order_history[ticker] = [
            ts for ts in self._order_history[ticker]
            if ts > five_minutes_ago
        ]
    
    def reset_strip(self, ticker: str) -> None:
        """Reset state for a specific strip (called on contract roll).
        
        Args:
            ticker: Market ticker
        """
        with self._lock:
            # Unregister all orders for this strip
            order_ids = list(self._strip_to_order_ids.get(ticker, set()))
            for order_id in order_ids:
                self.unregister_order(order_id)
            
            # Clear cooldown
            self.clear_cooldown(ticker)
            
            # Clear order history
            if ticker in self._order_history:
                del self._order_history[ticker]
            
            logger.info("[STRIP-RESET] ticker=%s - reset all state", ticker)
    
    def get_snapshot(self) -> Dict[str, any]:
        """Get a snapshot of current state for monitoring.
        
        Returns:
            Dictionary with current state
        """
        with self._lock:
            return {
                "working_orders_count": len(self._working_orders),
                "strips_with_orders": len(self._strip_to_order_ids),
                "active_cooldowns": len(self._cooldowns),
                "cooldowns": {
                    ticker: {
                        "reason": cd.exit_reason.value,
                        "remaining_seconds": cd.remaining_seconds,
                    }
                    for ticker, cd in self._cooldowns.items()
                },
            }


def get_strip_order_state() -> StripOrderState:
    """Get the singleton StripOrderState instance.
    
    Returns:
        StripOrderState singleton instance
    """
    return StripOrderState()
