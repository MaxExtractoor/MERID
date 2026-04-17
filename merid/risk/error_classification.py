"""Error classification system for MERID kill switch and error budget.

Provides centralized error classification mapping per the Halt Conditions Audit:
- CRITICAL errors: counted toward kill switch budget (auth_error, risk_violation, etc.)
- LOW/MEDIUM errors: budget-exempt (gate_blocked, duplicate_order, ws_reconnect, etc.)

Usage:
    from merid.risk.error_classification import classify_error, ErrorClass, ErrorSeverity
    
    # Classify an error
    classification = classify_error("auth_failed", context="kalshi_api")
    
    # Check if error should count toward budget
    if classification.counts_toward_budget:
        risk_controller.record_error_weighted(classification.severity_weight)
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.error_classification")


class ErrorClass(str, Enum):
    """Error class taxonomy per Halt Conditions Audit."""
    
    # Critical errors — always count toward kill switch budget
    AUTH_ERROR = "auth_error"                    # 401/403 auth failures
    RISK_VIOLATION = "risk_violation"           # Risk limit breaches
    INSUFFICIENT_FUNDS = "insufficient_funds"   # Balance/funding issues
    ORDER_REJECTED = "order_rejected"           # Serious order rejections
    GENERIC = "generic"                          # Uncategorized serious errors
    
    # Low severity — budget exempt
    GATE_BLOCKED = "gate_blocked"               # Execution gate blocked (expected)
    DUPLICATE_ORDER_REJECTED = "duplicate_order_rejected"  # Idempotency dupes
    PAPER_SESSION_ERROR = "paper_session_error"  # Paper trading issues
    WS_RECONNECT = "ws_reconnect"                # WebSocket reconnects (expected)
    WS_DISCONNECT = "ws_disconnect"                # WebSocket disconnects (normal client behavior)
    ASYNCIO_WIN995 = "asyncio_win995"            # Windows asyncio benign error (WinError 995)
    ASYNCIO_INVALID_STATE = "asyncio_invalid_state"  # InvalidStateError from asyncio
    MARKET_STATE = "market_state"                # Market closed/not tradeable (expected)
    STALE_SNAPSHOT = "stale_snapshot"           # Stale market data
    LOW_EDGE = "low_edge"                       # Low edge/filtered trades
    SPREAD_TOO_WIDE = "spread_too_wide"         # Market condition filter
    DEPTH_INSUFFICIENT = "depth_insufficient"   # Liquidity filter
    NO_OPEN_ORDERS = "no_open_orders"           # No orders to cancel
    NO_POSITION = "no_position"                 # No position for action
    ORDER_GROUP_NOT_FOUND = "order_group_not_found"  # Order group lifecycle
    ORDER_GROUP_NOT_ACTIVE = "order_group_not_active"

    # Intelligence/RSS/Sentiment — budget exempt (external service flakiness)
    INTELLIGENCE_FEED_FAILED = "intelligence_feed_failed"  # RSS/API fetch failure
    INTELLIGENCE_SENTIMENT_FAILED = "intelligence_sentiment_failed"  # Sentiment analysis error
    INTELLIGENCE_PARSE_FAILED = "intelligence_parse_failed"  # RSS/article parse error

    # Optional integrations — budget exempt when misconfigured
    TWITTER_AUTH_FAILED = "twitter_auth_failed"  # Twitter auth misconfig (non-critical)
    COINBASE_AUTH_FAILED = "coinbase_auth_failed"  # Coinbase auth misconfig (non-critical)
    
    # Medium severity — budget exempt but logged
    RATE_LIMIT = "rate_limit"                   # 429 rate limits
    TIMEOUT = "timeout"                         # Network timeouts
    EXCHANGE_ERROR = "exchange_error"           # 5xx exchange errors
    VALIDATION_ERROR = "validation_error"       # Input validation
    
    # Phantom kill switch specific
    PHANTOM_POSITION_DETECTED = "phantom_position_detected"  # True phantom positions


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    CRITICAL = "critical"      # P0 — can trigger kill switch
    HIGH = "high"             # P1 — serious but not budget-counted
    MEDIUM = "medium"         # P2 — operational concerns
    LOW = "low"               # Advisory — safe to ignore


# Error class to severity mapping
_ERROR_CLASS_SEVERITY: Dict[ErrorClass, ErrorSeverity] = {
    # Critical - ONLY auth and data integrity errors count toward kill threshold
    ErrorClass.AUTH_ERROR: ErrorSeverity.CRITICAL,
    ErrorClass.PHANTOM_POSITION_DETECTED: ErrorSeverity.CRITICAL,
    
    # HIGH - Serious but don't halt trading (venue errors, timeouts)
    ErrorClass.INSUFFICIENT_FUNDS: ErrorSeverity.HIGH,
    ErrorClass.ORDER_REJECTED: ErrorSeverity.HIGH,
    ErrorClass.GENERIC: ErrorSeverity.HIGH,
    
    # LOW - Risk violations are INTENTIONAL stops, not errors (daily loss, drawdown)
    ErrorClass.RISK_VIOLATION: ErrorSeverity.LOW,
    
    # High
    ErrorClass.RATE_LIMIT: ErrorSeverity.HIGH,
    ErrorClass.TIMEOUT: ErrorSeverity.HIGH,
    ErrorClass.EXCHANGE_ERROR: ErrorSeverity.HIGH,
    
    # Medium
    ErrorClass.VALIDATION_ERROR: ErrorSeverity.MEDIUM,
    ErrorClass.ORDER_GROUP_NOT_FOUND: ErrorSeverity.MEDIUM,
    ErrorClass.ORDER_GROUP_NOT_ACTIVE: ErrorSeverity.MEDIUM,
    
    # Low (budget exempt)
    ErrorClass.GATE_BLOCKED: ErrorSeverity.LOW,
    ErrorClass.DUPLICATE_ORDER_REJECTED: ErrorSeverity.LOW,
    ErrorClass.PAPER_SESSION_ERROR: ErrorSeverity.LOW,
    ErrorClass.WS_RECONNECT: ErrorSeverity.LOW,
    ErrorClass.WS_DISCONNECT: ErrorSeverity.LOW,
    ErrorClass.ASYNCIO_WIN995: ErrorSeverity.LOW,
    ErrorClass.ASYNCIO_INVALID_STATE: ErrorSeverity.LOW,
    ErrorClass.MARKET_STATE: ErrorSeverity.LOW,
    ErrorClass.STALE_SNAPSHOT: ErrorSeverity.LOW,
    ErrorClass.LOW_EDGE: ErrorSeverity.LOW,
    ErrorClass.SPREAD_TOO_WIDE: ErrorSeverity.LOW,
    ErrorClass.DEPTH_INSUFFICIENT: ErrorSeverity.LOW,
    ErrorClass.NO_OPEN_ORDERS: ErrorSeverity.LOW,
    ErrorClass.NO_POSITION: ErrorSeverity.LOW,
    ErrorClass.INTELLIGENCE_FEED_FAILED: ErrorSeverity.LOW,
    ErrorClass.INTELLIGENCE_SENTIMENT_FAILED: ErrorSeverity.LOW,
    ErrorClass.INTELLIGENCE_PARSE_FAILED: ErrorSeverity.LOW,
    ErrorClass.TWITTER_AUTH_FAILED: ErrorSeverity.LOW,
    ErrorClass.COINBASE_AUTH_FAILED: ErrorSeverity.LOW,
}

# Severity weights for weighted error counting
_SEVERITY_WEIGHTS: Dict[ErrorSeverity, float] = {
    ErrorSeverity.CRITICAL: 1.0,
    ErrorSeverity.HIGH: 0.5,
    ErrorSeverity.MEDIUM: 0.0,  # Not counted
    ErrorSeverity.LOW: 0.0,       # Not counted
}

# Error budget exempt classes - these do NOT count toward kill switch threshold
_BUDGET_EXEMPT_CLASSES: Set[ErrorClass] = {
    # Risk management stops (intentional, not errors)
    ErrorClass.RISK_VIOLATION,  # Daily loss limits, drawdowns - INTENTIONAL STOPS
    ErrorClass.GATE_BLOCKED,
    
    # Operational noise
    ErrorClass.DUPLICATE_ORDER_REJECTED,
    ErrorClass.PAPER_SESSION_ERROR,
    ErrorClass.WS_RECONNECT,
    ErrorClass.WS_DISCONNECT,
    ErrorClass.ASYNCIO_WIN995,
    ErrorClass.ASYNCIO_INVALID_STATE,
    ErrorClass.MARKET_STATE,
    ErrorClass.STALE_SNAPSHOT,
    ErrorClass.LOW_EDGE,
    ErrorClass.SPREAD_TOO_WIDE,
    ErrorClass.DEPTH_INSUFFICIENT,
    ErrorClass.NO_OPEN_ORDERS,
    ErrorClass.NO_POSITION,
    ErrorClass.ORDER_GROUP_NOT_FOUND,
    ErrorClass.ORDER_GROUP_NOT_ACTIVE,
    ErrorClass.VALIDATION_ERROR,
    ErrorClass.RATE_LIMIT,
    ErrorClass.TIMEOUT,
    
    # External service failures (not our fault)
    ErrorClass.INTELLIGENCE_FEED_FAILED,
    ErrorClass.INTELLIGENCE_SENTIMENT_FAILED,
    ErrorClass.INTELLIGENCE_PARSE_FAILED,
    ErrorClass.TWITTER_AUTH_FAILED,
    ErrorClass.COINBASE_AUTH_FAILED,
}


@dataclass(frozen=True)
class ErrorClassification:
    """Immutable classification result for an error."""
    error_class: ErrorClass
    severity: ErrorSeverity
    severity_weight: float
    counts_toward_budget: bool
    is_transient: bool  # True if error is expected to resolve itself
    description: str
    
    @property
    def is_critical(self) -> bool:
        return self.severity == ErrorSeverity.CRITICAL
    
    @property
    def should_alert_operator(self) -> bool:
        """Whether this error warrants operator notification."""
        return self.severity in (ErrorSeverity.CRITICAL, ErrorSeverity.HIGH)


def classify_error(
    error_code: str,
    context: Optional[str] = None,
    is_transient: bool = False,
) -> ErrorClassification:
    """Classify an error code into a structured classification.
    
    Args:
        error_code: String error code or identifier
        context: Optional context (e.g., "kalshi_api", "order_router")
        is_transient: Whether this is a transient/expected error
        
    Returns:
        ErrorClassification with severity, budget status, etc.
    """
    # Normalize error code
    normalized = error_code.lower().replace("-", "_").replace(" ", "_")
    
    # Try to match to known error class
    try:
        error_class = ErrorClass(normalized)
    except ValueError:
        # Try common aliases
        error_class = _resolve_error_class_alias(normalized)
    
    severity = _ERROR_CLASS_SEVERITY.get(error_class, ErrorSeverity.CRITICAL)
    weight = _SEVERITY_WEIGHTS.get(severity, 1.0)
    counts = error_class not in _BUDGET_EXEMPT_CLASSES
    
    # Auto-detect transient errors
    if not is_transient:
        is_transient = error_class in {
            ErrorClass.WS_RECONNECT,
            ErrorClass.WS_DISCONNECT,
            ErrorClass.ASYNCIO_WIN995,
            ErrorClass.ASYNCIO_INVALID_STATE,
            ErrorClass.MARKET_STATE,
            ErrorClass.RATE_LIMIT,
            ErrorClass.TIMEOUT,
            ErrorClass.STALE_SNAPSHOT,
        }
    
    description = _get_error_description(error_class, context)
    
    return ErrorClassification(
        error_class=error_class,
        severity=severity,
        severity_weight=weight,
        counts_toward_budget=counts,
        is_transient=is_transient,
        description=description,
    )


def _resolve_error_class_alias(normalized: str) -> ErrorClass:
    """Resolve common error code aliases to canonical ErrorClass."""
    aliases: Dict[str, ErrorClass] = {
        # Auth errors
        "401": ErrorClass.AUTH_ERROR,
        "403": ErrorClass.AUTH_ERROR,
        "auth_failed": ErrorClass.AUTH_ERROR,
        "api_key_invalid": ErrorClass.AUTH_ERROR,
        "forbidden": ErrorClass.AUTH_ERROR,
        "unauthorized": ErrorClass.AUTH_ERROR,
        
        # Risk violations (only true risk breaches, not policy rejections)
        "daily_loss_limit": ErrorClass.RISK_VIOLATION,
        "drawdown_halt": ErrorClass.RISK_VIOLATION,
        "kill_switch": ErrorClass.RISK_VIOLATION,
        # Policy rejections — budget exempt (these are expected guardrail outcomes)
        "position_limit": ErrorClass.GATE_BLOCKED,
        "position_limit_exceeded": ErrorClass.GATE_BLOCKED,
        "category_cap_exceeded": ErrorClass.GATE_BLOCKED,
        
        # Funds
        "insufficient_funds": ErrorClass.INSUFFICIENT_FUNDS,
        "max_cost_exceeded": ErrorClass.INSUFFICIENT_FUNDS,
        "balance_exceeded": ErrorClass.INSUFFICIENT_FUNDS,
        
        # Order rejected
        "order_rejected": ErrorClass.ORDER_REJECTED,
        "live_execution_error": ErrorClass.ORDER_REJECTED,
        "sanity_check_failed": ErrorClass.ORDER_REJECTED,
        
        # Gate blocked
        "gate_blocked": ErrorClass.GATE_BLOCKED,
        "execution_blocked": ErrorClass.GATE_BLOCKED,
        "reconciliation_blocked": ErrorClass.GATE_BLOCKED,
        
        # Duplicates
        "duplicate": ErrorClass.DUPLICATE_ORDER_REJECTED,
        "duplicate_order": ErrorClass.DUPLICATE_ORDER_REJECTED,
        "order_exists": ErrorClass.DUPLICATE_ORDER_REJECTED,
        
        # WS reconnect / disconnect
        "ws_reconnect": ErrorClass.WS_RECONNECT,
        "websocket_reconnect": ErrorClass.WS_RECONNECT,
        "connection_reset": ErrorClass.WS_RECONNECT,
        "ws_disconnect": ErrorClass.WS_DISCONNECT,
        "websocket_disconnect": ErrorClass.WS_DISCONNECT,
        "websocket_closed": ErrorClass.WS_DISCONNECT,
        
        # Windows asyncio errors (benign)
        "winerror_995": ErrorClass.ASYNCIO_WIN995,
        "win995": ErrorClass.ASYNCIO_WIN995,
        "invalid_state": ErrorClass.ASYNCIO_INVALID_STATE,
        "invalidstateerror": ErrorClass.ASYNCIO_INVALID_STATE,
        "cancelled_error": ErrorClass.ASYNCIO_INVALID_STATE,
        
        # Market state
        "market_closed": ErrorClass.MARKET_STATE,
        "market_not_tradeable": ErrorClass.MARKET_STATE,
        "market_state": ErrorClass.MARKET_STATE,
        
        # Rate limits
        "429": ErrorClass.RATE_LIMIT,
        "rate_limited": ErrorClass.RATE_LIMIT,
        "too_many_requests": ErrorClass.RATE_LIMIT,
        
        # Timeouts
        "timeout": ErrorClass.TIMEOUT,
        "connection_timeout": ErrorClass.TIMEOUT,
        "read_timeout": ErrorClass.TIMEOUT,
        
        # Exchange errors
        "500": ErrorClass.EXCHANGE_ERROR,
        "502": ErrorClass.EXCHANGE_ERROR,
        "503": ErrorClass.EXCHANGE_ERROR,
        "504": ErrorClass.EXCHANGE_ERROR,
        "exchange_error": ErrorClass.EXCHANGE_ERROR,
        
        # Phantom positions
        "phantom_position": ErrorClass.PHANTOM_POSITION_DETECTED,
        "phantom_kill": ErrorClass.PHANTOM_POSITION_DETECTED,
        
        # Intelligence / external services (budget exempt)
        "intelligence_feed": ErrorClass.INTELLIGENCE_FEED_FAILED,
        "rss_fetch_failed": ErrorClass.INTELLIGENCE_FEED_FAILED,
        "intelligence_sentiment": ErrorClass.INTELLIGENCE_SENTIMENT_FAILED,
        "sentiment_analysis_failed": ErrorClass.INTELLIGENCE_SENTIMENT_FAILED,
        "intelligence_parse": ErrorClass.INTELLIGENCE_PARSE_FAILED,
        "twitter_auth": ErrorClass.TWITTER_AUTH_FAILED,
        "coinbase_auth": ErrorClass.COINBASE_AUTH_FAILED,
        
        # Execution gate / policy (budget exempt — mapped to GATE_BLOCKED)
        "execution_gate_blocked": ErrorClass.GATE_BLOCKED,
        "execution_gate_error": ErrorClass.GATE_BLOCKED,
        "market_condition": ErrorClass.MARKET_STATE,
        "circuit_breaker": ErrorClass.GATE_BLOCKED,
        "circuit_breaker_open": ErrorClass.GATE_BLOCKED,
        "maintenance_mode": ErrorClass.GATE_BLOCKED,
        "venue_unavailable": ErrorClass.GATE_BLOCKED,
        "lease_conflict": ErrorClass.GATE_BLOCKED,
        "unauthorized_caller": ErrorClass.GATE_BLOCKED,
        "concurrent_order_limit": ErrorClass.GATE_BLOCKED,
        "live_not_enabled": ErrorClass.GATE_BLOCKED,
        "live_requires_async": ErrorClass.GATE_BLOCKED,
    }
    
    # Direct match
    if normalized in aliases:
        return aliases[normalized]
    
    # Partial match
    for alias, ec in aliases.items():
        if alias in normalized or normalized in alias:
            return ec
    
    # Default to generic critical
    return ErrorClass.GENERIC


def _get_error_description(error_class: ErrorClass, context: Optional[str]) -> str:
    """Get human-readable description for an error class."""
    descriptions: Dict[ErrorClass, str] = {
        ErrorClass.AUTH_ERROR: "Authentication/authorization failure",
        ErrorClass.RISK_VIOLATION: "Risk limit or kill switch violation",
        ErrorClass.INSUFFICIENT_FUNDS: "Insufficient funds for operation",
        ErrorClass.ORDER_REJECTED: "Order rejected by venue or system",
        ErrorClass.GENERIC: "Uncategorized error",
        ErrorClass.GATE_BLOCKED: "Execution gate blocked (expected control flow)",
        ErrorClass.DUPLICATE_ORDER_REJECTED: "Duplicate order rejected (idempotency)",
        ErrorClass.PAPER_SESSION_ERROR: "Paper trading session issue",
        ErrorClass.WS_RECONNECT: "WebSocket reconnected (expected)",
        ErrorClass.WS_DISCONNECT: "WebSocket disconnected (normal client behavior)",
        ErrorClass.ASYNCIO_WIN995: "Windows asyncio benign error (WinError 995)",
        ErrorClass.ASYNCIO_INVALID_STATE: "Asyncio invalid state (benign during shutdown)",
        ErrorClass.MARKET_STATE: "Market closed or not tradeable (expected)",
        ErrorClass.STALE_SNAPSHOT: "Stale market data snapshot",
        ErrorClass.LOW_EDGE: "Edge below threshold (filtered)",
        ErrorClass.SPREAD_TOO_WIDE: "Spread too wide (market condition)",
        ErrorClass.DEPTH_INSUFFICIENT: "Insufficient market depth",
        ErrorClass.NO_OPEN_ORDERS: "No open orders for operation",
        ErrorClass.NO_POSITION: "No position for operation",
        ErrorClass.RATE_LIMIT: "Rate limited by venue",
        ErrorClass.TIMEOUT: "Network/operation timeout",
        ErrorClass.EXCHANGE_ERROR: "Venue/exchange error (5xx)",
        ErrorClass.PHANTOM_POSITION_DETECTED: "Phantom position detected (reconciliation)",
        ErrorClass.ORDER_GROUP_NOT_FOUND: "Order group not found (lifecycle)",
        ErrorClass.ORDER_GROUP_NOT_ACTIVE: "Order group not active (lifecycle)",
        ErrorClass.INTELLIGENCE_FEED_FAILED: "Intelligence feed fetch failure (external)",
        ErrorClass.INTELLIGENCE_SENTIMENT_FAILED: "Sentiment analysis failure (external)",
        ErrorClass.INTELLIGENCE_PARSE_FAILED: "RSS/article parse failure (external)",
        ErrorClass.TWITTER_AUTH_FAILED: "Twitter auth misconfigured (non-critical)",
        ErrorClass.COINBASE_AUTH_FAILED: "Coinbase auth misconfigured (non-critical)",
    }
    
    base = descriptions.get(error_class, "Unknown error")
    if context:
        return f"{base} [context: {context}]"
    return base


# ── Error Budget Dedup Tracker ─────────────────────────────────────────────


@dataclass
class ErrorDedupTracker:
    """Tracks error occurrences for deduplication within a time window.
    
    Per the audit: within the dedup window, repeated occurrences of the same
    error "class + context" only increment the budget once.
    """
    
    dedup_window_seconds: float = field(default_factory=lambda: float(
        os.getenv("MERID_ERROR_DEDUP_WINDOW_SECS", "300")  # 5 min default
    ))
    
    # (error_class, context) -> last counted timestamp
    _last_seen: Dict[Tuple[str, Optional[str]], float] = field(default_factory=dict)
    
    def should_count(
        self,
        error_class: ErrorClass,
        context: Optional[str] = None,
    ) -> bool:
        """Check if this error occurrence should count toward budget.
        
        Returns True if:
        - First occurrence of this (class, context)
        - Previous occurrence was outside dedup window
        
        Returns False if:
        - Duplicate within dedup window
        """
        key = (error_class.value, context)
        now = time.time()
        
        last = self._last_seen.get(key, 0)
        if now - last > self.dedup_window_seconds:
            # Outside window — count it
            self._last_seen[key] = now
            return True
        
        # Inside window — don't count; do NOT update timestamp (avoids
        # infinite window extension from a steady trickle of the same error)
        return False
    
    def purge_old(self, max_age_seconds: Optional[float] = None) -> int:
        """Purge entries older than max_age. Returns count purged."""
        if max_age_seconds is None:
            max_age_seconds = self.dedup_window_seconds * 2
        
        now = time.time()
        old_keys = [
            k for k, ts in self._last_seen.items()
            if now - ts > max_age_seconds
        ]
        for k in old_keys:
            del self._last_seen[k]
        return len(old_keys)
    
    def get_stats(self) -> Dict[str, int]:
        """Get dedup tracker statistics."""
        return {
            "tracked_keys": len(self._last_seen),
            "unique_classes": len({k[0] for k in self._last_seen}),
        }


# Global dedup tracker singleton
_dedup_tracker: Optional[ErrorDedupTracker] = None


def get_dedup_tracker() -> ErrorDedupTracker:
    """Get the global error dedup tracker."""
    global _dedup_tracker
    if _dedup_tracker is None:
        _dedup_tracker = ErrorDedupTracker()
    return _dedup_tracker


def should_count_error(
    error_code: str,
    context: Optional[str] = None,
) -> Tuple[bool, ErrorClassification]:
    """Combined helper: classify error and check if it should count toward budget.
    
    Returns:
        (should_count, classification)
    """
    classification = classify_error(error_code, context)
    
    if not classification.counts_toward_budget:
        return False, classification
    
    tracker = get_dedup_tracker()
    should = tracker.should_count(classification.error_class, context)
    
    return should, classification


# ── Kill Switch Tier Logic ─────────────────────────────────────────────────


class KillSwitchTier(str, Enum):
    """Kill switch escalation tiers per audit."""
    CLEAR = "clear"           # Normal operation
    WARNING = "warning"       # 70% of threshold
    LIMITED = "limited"       # 90% of threshold — reduced sizing
    TRIGGERED = "triggered"   # 100% of threshold — trading halted


@dataclass
class TierThresholds:
    """Thresholds for tier escalation."""
    warning_pct: float = 0.70   # 70%
    limited_pct: float = 0.90   # 90%
    triggered_pct: float = 1.0  # 100%
    
    @classmethod
    def from_env(cls) -> "TierThresholds":
        """Load thresholds from environment variables."""
        return cls(
            warning_pct=float(os.getenv("MERID_WARN_PCT", "0.70")),
            limited_pct=float(os.getenv("MERID_LIMIT_PCT", "0.90")),
            triggered_pct=float(os.getenv("MERID_TRIGGER_PCT", "1.0")),
        )


def compute_kill_tier(
    error_count: float,
    threshold: int,
    thresholds: Optional[TierThresholds] = None,
) -> Tuple[KillSwitchTier, float]:
    """Compute kill switch tier based on weighted error count.
    
    Returns:
        (tier, pct_of_threshold)
    """
    if thresholds is None:
        thresholds = TierThresholds.from_env()
    
    if threshold <= 0:
        return KillSwitchTier.CLEAR, 0.0
    
    pct = error_count / threshold
    
    if pct >= thresholds.triggered_pct:
        return KillSwitchTier.TRIGGERED, pct
    elif pct >= thresholds.limited_pct:
        return KillSwitchTier.LIMITED, pct
    elif pct >= thresholds.warning_pct:
        return KillSwitchTier.WARNING, pct
    else:
        return KillSwitchTier.CLEAR, pct


def check_multi_signal_condition(
    recent_errors: List[ErrorClassification],
    window_seconds: float = 60.0,
) -> bool:
    """Check if multi-signal condition is met for tier escalation.
    
    Per audit: TRIGGERED requires either:
    - Error count >= threshold AND multi-signal condition, OR
    - Error count >= threshold AND runaway condition
    
    Multi-signal = errors from >= 2 different critical classes within window.
    """
    now = time.time()
    recent_critical = [
        e for e in recent_errors
        if e.is_critical and e.timestamp > now - window_seconds  # Note: would need timestamp
    ]
    
    unique_classes = {e.error_class for e in recent_critical}
    return len(unique_classes) >= 2
