"""
WebSocket Health Monitoring Helpers

Centralized WebSocket health monitoring with proper idle vs stalled semantics
and consistent thresholds. Used by WS bridge and health check consumers.

Used by:
- ws_bridge.py (health computation)
- loop_15m.py (execution guardrails)
- Any code needing WS health status
"""

import time
import math
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Constants - centralized threshold configuration
IDLE_WARN_AFTER = 60.0  # Warn if idle for > 60s (wiring/subscription issue)
STALL_THRESHOLD = 15.0  # Time since last event to consider DEGRADED (reduced from 30s)
UNHEALTHY_THRESHOLD = 60.0  # Time since last event to consider UNHEALTHY
HEARTBEAT_INTERVAL = 5.0  # Health diagnostic logging interval
MAX_RECONNECT_BACKOFF_SEC = 120.0  # Maximum backoff for reconnection

@dataclass
class WSHealthResult:
    """WebSocket health status with detailed diagnostics."""
    state: str  # "idle", "healthy", "degraded", "unhealthy"
    stalled: bool  # Legacy field for compatibility
    event_count_total: int
    events_per_sec: float
    queue_size: int
    time_since_last_event: Optional[float]  # None if idle
    first_event_ts: float
    last_event_ts: float
    subscription_coverage: Dict[str, Any]
    reconnect_attempt: int = 0
    consecutive_failures: int = 0
    
    def is_healthy(self) -> bool:
        """Check if WS is healthy (not stalled and either idle or processing)."""
        return self.state in ("idle", "healthy")
    
    def can_trade(self) -> bool:
        """Check if trading is allowed (healthy or degraded with fresh data)."""
        return self.state in ("idle", "healthy", "degraded")
    
    def has_events(self) -> bool:
        """Check if any events have been processed."""
        return self.event_count_total > 0
    
    def is_processing(self) -> bool:
        """Check if actively processing events (not idle)."""
        return self.state == "healthy"

def compute_ws_health(
    event_count_total: int,
    first_event_ts: float,
    last_event_ts: float,
    events_per_sec: float,
    queue_size: int,
    subscribed_assets: set,
    expected_assets: set,
    now_mono: Optional[float] = None,
    reconnect_attempt: int = 0,
    consecutive_failures: int = 0
) -> WSHealthResult:
    """
    Compute WebSocket health status with 3-state machine (HEALTHY/DEGRADED/UNHEALTHY).
    
    Args:
        event_count_total: Total events processed since start
        first_event_ts: Timestamp of first event (0 if never received)
        last_event_ts: Timestamp of most recent event
        events_per_sec: Current events per second rate
        queue_size: Current event queue size
        subscribed_assets: Set of assets currently subscribed
        expected_assets: Set of assets that should be subscribed
        now_mono: Current monotonic time (uses time.monotonic() if None)
        reconnect_attempt: Current reconnection attempt number
        consecutive_failures: Number of consecutive connection failures
        
    Returns:
        WSHealthResult with complete health status
    """
    if now_mono is None:
        now_mono = time.monotonic()
    
    # Determine state with 3-state machine
    if event_count_total == 0:
        # Never received any events - IDLE, not stalled
        state = "idle"
        stalled = False
        time_since_last = None
    else:
        # Used to receive events, check if stopped
        time_since_last = now_mono - last_event_ts
        
        if time_since_last > UNHEALTHY_THRESHOLD:
            # No messages for > UNHEALTHY_THRESHOLD - UNHEALTHY state
            state = "unhealthy"
            stalled = True
        elif time_since_last > STALL_THRESHOLD:
            # No messages for > STALL_THRESHOLD but < UNHEALTHY_THRESHOLD - DEGRADED state
            state = "degraded"
            stalled = False  # Not fully stalled, but degraded
        else:
            # Receiving messages normally - HEALTHY state
            state = "healthy"
            stalled = False
    
    # Compute subscription coverage
    missing_assets = expected_assets - subscribed_assets
    subscription_coverage = {
        "subscribed_assets": list(subscribed_assets),
        "missing_assets": list(missing_assets),
        "expected_count": len(expected_assets),
        "subscribed_count": len(subscribed_assets),
        "coverage_complete": len(missing_assets) == 0
    }
    
    return WSHealthResult(
        state=state,
        stalled=stalled,
        event_count_total=event_count_total,
        events_per_sec=events_per_sec,
        queue_size=queue_size,
        time_since_last_event=time_since_last,
        first_event_ts=first_event_ts,
        last_event_ts=last_event_ts,
        subscription_coverage=subscription_coverage,
        reconnect_attempt=reconnect_attempt,
        consecutive_failures=consecutive_failures
    )

def compute_reconnect_backoff(attempt: int) -> float:
    """
    Compute exponential backoff with jitter for WebSocket reconnection.
    
    Implements exponential backoff with jitter to avoid hammering the server
    and prevent thundering herd problems during reconnection storms.
    
    Args:
        attempt: Current reconnection attempt number (0-indexed)
        
    Returns:
        Delay in seconds before next reconnection attempt
    """
    base = 1.0  # seconds
    cap = MAX_RECONNECT_BACKOFF_SEC
    
    # Exponential backoff: base * 2^min(attempt, 6)
    delay = base * (2 ** min(attempt, 6))
    
    # Add jitter: random value between 0 and 0.5 * delay
    jitter = random.random() * 0.5 * delay
    
    # Cap at maximum backoff
    return min(delay + jitter, cap)

def validate_ws_health_consistency(result: WSHealthResult) -> bool:
    """
    Validate WS health result for internal consistency.
    
    Args:
        result: WSHealthResult to validate
        
    Returns:
        True if result appears consistent, False otherwise
    """
    # Check timestamp consistency
    if result.first_event_ts > 0 and result.last_event_ts > 0:
        if result.first_event_ts > result.last_event_ts:
            return False  # First event can't be after last event
    
    # Check state consistency
    if result.state == "idle":
        if result.event_count_total != 0:
            return False  # Idle should have zero events
        if result.time_since_last_event is not None:
            return False  # Idle should have None time_since_last
    elif result.state == "healthy":
        if result.event_count_total == 0:
            return False  # Healthy should have events
        if result.time_since_last_event is None:
            return False  # Healthy should have time_since_last
        if result.stalled:
            return False  # Healthy should not be stalled
    elif result.state == "stalled":
        if result.event_count_total == 0:
            return False  # Stalled should have events
        if result.time_since_last_event is None:
            return False  # Stalled should have time_since_last
        if not result.stalled:
            return False  # Stalled should be marked as stalled
    
    # Check numeric validity
    if not (math.isfinite(result.events_per_sec) and result.events_per_sec >= 0):
        return False
    
    if result.queue_size < 0:
        return False
    
    return True

def log_ws_health_diagnostics(result: WSHealthResult, url: Optional[str] = None, component: str = "WS_HEALTH") -> None:
    """
    Log comprehensive WS health diagnostics with structured logging.
    
    Args:
        result: WSHealthResult to log
        url: Optional WebSocket URL for context
        component: Component name for structured logging (WS_UPSTREAM, WS_FORWARDER, WS_CLIENT_15M, WS_HEALTH)
    """
    url_str = f" uri={url}" if url else ""
    
    logger.info(
        "[%s] status=%s stalled=%s stale_ms=%.0f reason=%s component=%s last_msg_ts=%.0f reconnect_attempt=%d%s",
        component,
        result.state.upper(),
        result.stalled,
        (result.time_since_last_event or 0) * 1000,
        "ok" if result.state in ("idle", "healthy") else "stale_connection" if result.state == "degraded" else "no_messages",
        component,
        result.last_event_ts,
        result.reconnect_attempt,
        url_str
    )
    
    # Additional warnings for problematic states
    if result.state == "idle":
        # Check if we've been idle for too long (potential wiring issue)
        current_time = time.monotonic()
        if result.event_count_total == 0 and current_time > IDLE_WARN_AFTER:
            logger.warning(
                "[%s] IDLE for >%.0fs - check subscription/wiring",
                component,
                IDLE_WARN_AFTER
            )
    
    elif result.state == "degraded":
        logger.warning(
            "[%s] DEGRADED for %.1fs - messages delayed but trading allowed if data fresh",
            component,
            result.time_since_last_event or 0
        )
    
    elif result.state == "unhealthy":
        logger.error(
            "[%s] UNHEALTHY for %.1fs - events stopped processing, trading blocked",
            component,
            result.time_since_last_event or 0
        )
