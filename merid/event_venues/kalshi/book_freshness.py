"""Book Freshness State Machine for Kalshi Orderbook Data.

Implements a layered approach to data freshness validation with explicit
states: LIVE / DEGRADED / STALE / FALLBACK / DEAD / MARKET_CLOSED.

This prevents the current failure mode where one missing field shuts the
entire strategy down even though the data is otherwise usable.

Reference: https://eodhd.com/financial-academy/fundamental-analysis-examples/real-time-market-data-reliability-stale-price-detection-rest-fallback-and-websocket-recovery
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.book_freshness")


class BookState(Enum):
    """Explicit book freshness states for trading decisions."""
    LIVE = "LIVE"  # Fresh data from live WebSocket with confirmed stability
    DEGRADED = "DEGRADED"  # Fresh but missing exchange timestamp (received timestamp OK)
    STALE = "STALE"  # Data exceeds staleness threshold
    FALLBACK = "FALLBACK"  # REST snapshot used (WebSocket unavailable)
    DEAD = "DEAD"  # No data available or connection lost
    MARKET_CLOSED = "MARKET_CLOSED"  # Market is closed/settled


@dataclass
class BookFreshnessState:
    """Normalized book freshness state with source tracking."""
    
    # Timestamps
    exchange_timestamp: Optional[float] = None  # Exchange-provided timestamp
    received_timestamp: Optional[float] = None  # When we received the data
    computed_timestamp: Optional[float] = None  # Best available timestamp for age calculation
    
    # State
    state: BookState = BookState.DEAD
    source: str = "UNKNOWN"  # WS_LIVE, REST_BOOTSTRAP, REST_FALLBACK
    
    # Age tracking
    age_seconds: float = float('inf')
    staleness_threshold_seconds: float = 15.0  # Default for 15m crypto markets
    
    # Stability tracking (for LIVE state confirmation)
    stable_update_count: int = 0  # Number of consecutive fresh updates
    min_stable_updates: int = 3  # Minimum updates to mark as LIVE
    
    # Connection health (separate from quote freshness)
    connection_healthy: bool = False
    last_connection_check: float = 0.0
    
    def __post_init__(self):
        """Initialize computed timestamp from available sources."""
        self._update_computed_timestamp()
        self._update_age()
        self._update_state()
    
    def _update_computed_timestamp(self) -> None:
        """Use the newest trusted timestamp available."""
        now = time.time()
        # Validate timestamps are within reasonable bounds (not corrupted)
        # Reject timestamps more than 1 hour in the past or 1 hour in the future
        max_age_seconds = 3600.0  # 1 hour
        max_future_seconds = 3600.0  # 1 hour
        
        def is_valid_timestamp(ts: Optional[float]) -> bool:
            if ts is None or ts <= 0:
                return False
            age = now - ts
            # Reject if too old (corrupted) or in the future
            return -max_future_seconds <= age <= max_age_seconds
        
        # Priority: exchange_timestamp > received_timestamp
        if self.exchange_timestamp is not None and is_valid_timestamp(self.exchange_timestamp):
            self.computed_timestamp = self.exchange_timestamp
        elif self.received_timestamp is not None and is_valid_timestamp(self.received_timestamp):
            self.computed_timestamp = self.received_timestamp
        else:
            # 2026-08-11: Missing timestamps are common during REST bootstrap or when
            # a snapshot arrives without exchange/received metadata.  Only raise a
            # WARNING when at least one timestamp is present but out of bounds.
            both_missing = self.exchange_timestamp is None and self.received_timestamp is None
            if both_missing:
                logger.debug(
                    "[BOOK-FRESHNESS] No timestamps available - exchange_ts=None received_ts=None; treating as fresh (will update on next snapshot)"
                )
            else:
                logger.warning(
                    "[BOOK-FRESHNESS] Invalid/corrupted timestamps detected - "
                    "exchange_ts=%s received_ts=%s - rejecting both as corrupted",
                    self.exchange_timestamp, self.received_timestamp
                )
            self.computed_timestamp = None
    
    def _update_age(self) -> None:
        """Compute age from the newest trusted timestamp available."""
        if self.computed_timestamp is None:
            self.age_seconds = float('inf')
        else:
            now = time.time()
            self.age_seconds = now - self.computed_timestamp
    
    def _update_state(self) -> None:
        """Update state based on age, source, and stability."""
        if self.source == "MARKET_CLOSED":
            self.state = BookState.MARKET_CLOSED
            return
        
        if self.computed_timestamp is None:
            self.state = BookState.DEAD
            return
        
        # Check staleness
        if self.age_seconds > self.staleness_threshold_seconds:
            self.state = BookState.STALE
            return
        
        # Check source
        if self.source == "REST_FALLBACK":
            self.state = BookState.FALLBACK
            return
        
        # Check if exchange timestamp is missing but received timestamp is fresh
        if self.exchange_timestamp is None and self.received_timestamp is not None:
            self.state = BookState.DEGRADED
            return
        
        # Check stability for LIVE state
        if self.stable_update_count >= self.min_stable_updates:
            self.state = BookState.LIVE
        else:
            # Not yet confirmed stable, but data is fresh
            self.state = BookState.DEGRADED
    
    def update_from_ws(self, exchange_ts: Optional[float], received_ts: Optional[float]) -> None:
        """Update state from WebSocket message."""
        now = time.time()
        
        # Update timestamps
        self.exchange_timestamp = exchange_ts
        self.received_timestamp = received_ts if received_ts is not None else now
        self.source = "WS_LIVE"
        
        # Update connection health
        self.connection_healthy = True
        self.last_connection_check = now
        
        # Recompute timestamp and age FIRST (before stability check)
        self._update_computed_timestamp()
        self._update_age()
        
        # Update stability counter (depends on age being computed)
        if self.age_seconds <= self.staleness_threshold_seconds:
            self.stable_update_count += 1
        else:
            self.stable_update_count = 0  # Reset if data was stale
        
        # Recompute state (depends on stability counter)
        self._update_state()
    
    def update_from_rest(self, received_ts: Optional[float], is_fallback: bool = False) -> None:
        """Update state from REST snapshot."""
        now = time.time()
        
        # REST snapshots typically don't have exchange timestamps
        self.exchange_timestamp = None
        self.received_timestamp = received_ts if received_ts is not None else now
        self.source = "REST_FALLBACK" if is_fallback else "REST_BOOTSTRAP"
        
        # Reset stability counter (REST data doesn't confirm WS stability)
        self.stable_update_count = 0
        
        # Recompute state
        self._update_computed_timestamp()
        self._update_age()
        self._update_state()
    
    def mark_connection_lost(self) -> None:
        """Mark connection as lost (frozen WebSocket)."""
        self.connection_healthy = False
        self.last_connection_check = time.time()
        
        # If connection is lost but data is fresh, mark as DEGRADED
        if self.state == BookState.LIVE:
            self.state = BookState.DEGRADED
    
    def is_tradable(self) -> bool:
        """Check if book state allows trading."""
        # Allow trading in LIVE, DEGRADED, and FALLBACK states
        # Reject only in STALE, DEAD, or MARKET_CLOSED states
        return self.state in {
            BookState.LIVE,
            BookState.DEGRADED,
            BookState.FALLBACK,
        }
    
    def is_healthy(self) -> bool:
        """Check if book state is healthy (LIVE or DEGRADED with healthy connection)."""
        return self.state in {BookState.LIVE, BookState.DEGRADED} and self.connection_healthy
    
    def get_diagnostic_info(self) -> Dict[str, Any]:
        """Get diagnostic information for logging/debugging."""
        return {
            "state": self.state.value,
            "source": self.source,
            "age_seconds": self.age_seconds,
            "exchange_timestamp": self.exchange_timestamp,
            "received_timestamp": self.received_timestamp,
            "computed_timestamp": self.computed_timestamp,
            "connection_healthy": self.connection_healthy,
            "stable_update_count": self.stable_update_count,
            "is_tradable": self.is_tradable(),
            "is_healthy": self.is_healthy(),
        }


class BookFreshnessTracker:
    """Track book freshness state per ticker."""
    
    def __init__(self, staleness_threshold_seconds: float = 15.0):
        self.staleness_threshold_seconds = staleness_threshold_seconds
        self._states: Dict[str, BookFreshnessState] = {}
        self._lock = __import__('threading').RLock()
    
    def get_state(self, ticker: str) -> BookFreshnessState:
        """Get freshness state for a ticker."""
        with self._lock:
            if ticker not in self._states:
                self._states[ticker] = BookFreshnessState(
                    staleness_threshold_seconds=self.staleness_threshold_seconds
                )
            return self._states[ticker]
    
    def update_from_ws(self, ticker: str, exchange_ts: Optional[float], 
                       received_ts: Optional[float]) -> None:
        """Update state from WebSocket message."""
        with self._lock:
            state = self.get_state(ticker)
            state.update_from_ws(exchange_ts, received_ts)
    
    def update_from_rest(self, ticker: str, received_ts: Optional[float], 
                        is_fallback: bool = False) -> None:
        """Update state from REST snapshot."""
        with self._lock:
            state = self.get_state(ticker)
            state.update_from_rest(received_ts, is_fallback)
    
    def mark_connection_lost(self, ticker: str) -> None:
        """Mark connection as lost for a ticker."""
        with self._lock:
            state = self.get_state(ticker)
            state.mark_connection_lost()
    
    def is_tradable(self, ticker: str) -> bool:
        """Check if ticker is tradable based on freshness state."""
        state = self.get_state(ticker)
        return state.is_tradable()
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get diagnostic info for all tickers."""
        with self._lock:
            return {
                ticker: state.get_diagnostic_info()
                for ticker, state in self._states.items()
            }


# Global singleton
_global_tracker: Optional[BookFreshnessTracker] = None
_tracker_lock = __import__('threading').Lock()


def get_book_freshness_tracker(staleness_threshold_seconds: float = 15.0) -> BookFreshnessTracker:
    """Get the global book freshness tracker singleton."""
    global _global_tracker
    with _tracker_lock:
        if _global_tracker is None:
            _global_tracker = BookFreshnessTracker(staleness_threshold_seconds)
        return _global_tracker