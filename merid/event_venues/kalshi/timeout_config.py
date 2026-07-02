"""Centralized timeout and retry configuration for Kalshi venue.

This module provides single source of truth for all timeout and retry policies
across the Kalshi venue stack (WebSocket, REST API, database, etc.).

Usage:
    from merid.event_venues.kalshi.timeout_config import (
        WS_CONNECT_TIMEOUT_S,
        WS_PING_TIMEOUT_S,
        REST_API_TIMEOUT_S,
        get_retry_delay,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# =============================================================================
# WebSocket Configuration
# =============================================================================

# Connection timeout for WebSocket connect() calls
WS_CONNECT_TIMEOUT_S: float = 10.0

# Ping/pong timeout for WebSocket keepalive
WS_PING_TIMEOUT_S: float = 60.0

# Ping interval for WebSocket keepalive
WS_PING_INTERVAL_S: float = 30.0

# Close timeout for WebSocket shutdown
WS_CLOSE_TIMEOUT_S: float = 5.0

# Maximum time per batch before yielding in event processing
WS_BATCH_TIMEOUT_MS: int = 100

# Minimum time between sync attempts
WS_SYNC_RETRY_INTERVAL_S: float = 5.0

# Message queue timeout for event processing
WS_MESSAGE_QUEUE_TIMEOUT_S: float = 0.1

# Event publish timeout for forward loop
WS_EVENT_PUBLISH_TIMEOUT_S: float = 1.0


# =============================================================================
# REST API Configuration
# =============================================================================

# Default timeout for REST API calls
REST_API_TIMEOUT_S: float = 15.0

# Timeout for orderbook snapshot requests
ORDERBOOK_SNAPSHOT_TIMEOUT_S: float = 5.0

# Timeout for batch orderbook snapshot operations
ORDERBOOK_BATCH_TIMEOUT_S: float = 30.0

# Catalog sync timeout
CATALOG_SYNC_TIMEOUT_S: float = 10.0


# =============================================================================
# Database Configuration
# =============================================================================

# Database connection timeout
DB_TIMEOUT_S: float = 5.0

# Database busy timeout (for retry logic)
DB_BUSY_TIMEOUT_MS: int = 30000

# Database retry attempts
DB_RETRY_ATTEMPTS: int = 3

# Database retry delay (initial)
DB_RETRY_DELAY_INITIAL_S: float = 0.05

# Database retry delay (max)
DB_RETRY_DELAY_MAX_S: float = 0.5


# =============================================================================
# Retry Configuration
# =============================================================================

# Base retry delay for exponential backoff
RETRY_DELAY_BASE_S: float = 5.0

# Maximum retry delay (capped)
RETRY_DELAY_MAX_S: float = 300.0

# Maximum retry attempts
RETRY_MAX_ATTEMPTS: int = 3

# WebSocket connection retry attempts
WS_CONNECT_RETRY_ATTEMPTS: int = 3


# =============================================================================
# Order Management Configuration
# =============================================================================

# Default timeout for waiting for order fill
ORDER_FILL_TIMEOUT_S: float = 10.0

# Thread join timeout for shutdown
THREAD_JOIN_TIMEOUT_S: float = 5.0


# =============================================================================
# Helper Functions
# =============================================================================

@dataclass
class RetryPolicy:
    """Retry policy configuration."""
    max_attempts: int = RETRY_MAX_ATTEMPTS
    base_delay_s: float = RETRY_DELAY_BASE_S
    max_delay_s: float = RETRY_DELAY_MAX_S
    exponential_backoff: bool = True


def get_retry_delay(attempt: int, policy: Optional[RetryPolicy] = None) -> float:
    """Calculate retry delay with exponential backoff.
    
    Args:
        attempt: Current attempt number (0-indexed)
        policy: Retry policy (uses default if None)
    
    Returns:
        Delay in seconds before next retry
    """
    if policy is None:
        policy = RetryPolicy()
    
    if not policy.exponential_backoff:
        return policy.base_delay_s
    
    # Exponential backoff: base_delay * 2^attempt
    delay = policy.base_delay_s * (2 ** attempt)
    
    # Cap at max delay
    return min(delay, policy.max_delay_s)


def get_ws_retry_delay(attempt: int) -> float:
    """Get WebSocket connection retry delay.
    
    Uses shorter base delay (5s) for WS connections.
    
    Args:
        attempt: Current attempt number (0-indexed)
    
    Returns:
        Delay in seconds before next retry
    """
    return get_retry_delay(attempt, RetryPolicy(base_delay_s=5.0, max_delay_s=60.0))


def get_api_retry_delay(attempt: int) -> float:
    """Get REST API retry delay.
    
    Uses standard base delay (5s) for API calls.
    
    Args:
        attempt: Current attempt number (0-indexed)
    
    Returns:
        Delay in seconds before next retry
    """
    return get_retry_delay(attempt, RetryPolicy(base_delay_s=5.0, max_delay_s=300.0))


def get_db_retry_delay(attempt: int) -> float:
    """Get database retry delay.
    
    Uses shorter base delay (0.05s) for DB operations.
    
    Args:
        attempt: Current attempt number (0-indexed)
    
    Returns:
        Delay in seconds before next retry
    """
    return get_retry_delay(
        attempt,
        RetryPolicy(
            base_delay_s=DB_RETRY_DELAY_INITIAL_S,
            max_delay_s=DB_RETRY_DELAY_MAX_S
        )
    )
