"""Classify order failure reasons for RiskController ERROR_THRESHOLD (hourly error count).

Only *incident-grade* failures should increment ``record_error()`` — not expected policy
rejections (sanity, caps, live gates). See ``should_count_toward_error_threshold``.
"""

from __future__ import annotations

from typing import Optional

# Prefixes on *normalized* router/tool reasons (after strip_order_rejected_prefix).
# These are expected policy / guardrail outcomes — do not count toward ERROR_THRESHOLD.
_POLICY_PREFIXES_DO_NOT_COUNT: tuple[str, ...] = (
    "live_not_enabled",
    "sentiment_notional_cap:",  # from sentiment_risk.sentiment_order_rejection_reason
    "risk_check:",
    "pre_validation_failed:",
    "category_cap_exceeded:",
    "corr_stack_cap_exceeded:",
    "order_group_not_found:",
    "order_group_not_active:",
    "order_group_limit_exceeded:",
    "kalshi config mismatch",  # paper/live URL mismatch — config warning only
    "client error: 404",  # market not found — expired/delisted ticker
    "gate:duplicate",  # duplicate order race conditions
    # BUG-KS2 FIX: Missing policy prefixes causing false error threshold triggers
    "market_condition:",  # A5 market filter rejections (price/spread/volume bounds)
    "category_cap_check_error:",  # Category exposure tracker rejections
    "execution_gate_error:",  # Execution gate check failures
    "execution_gate_blocked:",  # Explicit gate blocked messages
    "unauthorized_caller:",  # Caller audit rejections
    "lease_conflict:",  # Contract lease conflicts between agents
    "live_requires_async_route_order",  # Sync route_order called in live mode
    "insufficient_margin:",  # Margin checks (expected policy)
    "position_limit_exceeded:",  # Position limit bounds (expected policy)
    "concurrent_order_limit:",  # Rate limiting per agent
    "circuit_breaker_open:",  # Venue circuit breaker (expected safety)
    "venue_unavailable:",  # Venue downtime (expected external condition)
    "maintenance_mode:",  # Scheduled maintenance
)

# Substrings in *raw* (un-normalized) reasons that indicate execution-gate or
# kill-switch blocking — not infrastructure failures.  These are checked case-
# insensitively against the original reason string BEFORE normalization so that
# multi-leg messages ("bid:... ; ask:...") are covered.
_GATE_BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    "execution gate blocked",
    "execution_gate_blocked",    # router prefix form: execution_gate_blocked:{msg}
    "kill switch is engaged",
    "kill switch engaged",
    "paper/mock=true but using live url",  # config mismatch — dev safeguard only
    "mode is paper but kalshi client url is live",  # stale .pyc / RuntimeError variant
    "client url is live",  # catch-all for any paper+live URL mismatch variant
    "refusing to create client",  # legacy .pyc message variant
    "client error: 404",  # market not found — expected when markets expire
    "gate:duplicate",  # duplicate order race — expected in multi-agent setups
    # BUG-KS2 FIX: Additional substrings for market conditions and policy blocks
    "market_condition:",  # A5 market filter rejections
    "market condition:",  # Alternative formatting
    "price_too_low",  # Price bounds
    "price_too_high",
    "spread_too_wide",  # Spread bounds
    "volume_too_low",  # Volume bounds
    "lease_conflict",  # Lease rejections
    "unauthorized_caller",  # Caller audit blocks
    "circuit_breaker",  # Circuit breaker states
    "maintenance_mode",  # Maintenance blocks
    "insufficient margin",  # Margin blocks
    "position limit",  # Position limit blocks
    # NOTE: "rate limit" intentionally omitted - rate_limit is HIGH severity, counts toward threshold
    "concurrent_order_limit",  # Concurrent order blocks
)


def strip_order_rejected_prefix(reason: str) -> str:
    """Kalshi tools wrap router reasons as ``Order rejected: <reason>`` — unwrap for classification."""
    s = (reason or "").strip()
    low = "order rejected:"
    if s.lower().startswith(low):
        return s[len(low) :].strip()
    return s


def normalize_order_failure_reason(reason: Optional[str]) -> str:
    """Canonical string for prefix checks (empty if unknown)."""
    if reason is None:
        return ""
    return strip_order_rejected_prefix(str(reason))


def should_count_toward_error_threshold(reason: Optional[str]) -> bool:
    """
    Return True if this failure should increment ``RiskController.record_error()``
    (hourly ERROR_THRESHOLD kill switch).

    Policy/guardrail outcomes return False. Infrastructure exceptions, venue outages,
    and sanity-checker *internal* errors return True.

    Multi-leg messages (arb / quote) may embed several sub-reasons; substring checks
    handle ``sanity_check:`` / ``kill_switch:`` inside ``YES: ...; NO: ...`` text.
    """
    raw = (reason or "").strip()
    if not raw:
        return True

    # Execution-gate or kill-switch blocking messages — checked on raw reason before
    # normalization so multi-leg formats ("bid:...; ask:...") are covered.
    raw_lower = raw.lower()
    for gs in _GATE_BLOCKED_SUBSTRINGS:
        if gs in raw_lower:
            return False

    n = normalize_order_failure_reason(raw)

    # Checker internal exception — count (incident).
    if "sanity_check_error:" in n:
        return True
    # Violation bundle (anywhere, including wrapped tool text) — do not count.
    if "sanity_check:" in n:
        return False
    if "kill_switch:" in n:
        return False

    for p in _POLICY_PREFIXES_DO_NOT_COUNT:
        if n.startswith(p) or n == p.rstrip(":"):
            return False

    # Default: count (venue errors, execution_gate failures, routing_exception, unknown text).
    return True
