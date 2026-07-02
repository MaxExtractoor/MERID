"""
MD SLA Interface - Canonical Staleness Contract

This module provides the single source of truth for market data staleness
determination across the entire MERID stack. All layers (health API, market
state, WS bridge, strategies, routing, risk) MUST use these functions.

Canonical Contract:
-------------------
Inputs:
  - age_ms: Time since last update in milliseconds
  - minutes_to_expiry: Optional time to contract expiry in minutes

Outputs:
  - status: One of "ok", "stale", "bad"

Guarantee:
  For any given (age_ms, minutes_to_expiry), every layer in the stack returns
  the same status. No ad-hoc staleness checks are allowed in production.

Usage:
------
    from merid.event_venues.kalshi.md_sla_interface import (
        get_md_status,
        get_md_max_age_seconds,
    )
    
    status = get_md_status(age_ms=1800, minutes_to_expiry=1.0)
    max_age_s = get_md_max_age_seconds(minutes_to_expiry=1.0)

Migration Guide:
----------------
- Replace direct age_ms comparisons with get_md_status()
- Replace hardcoded thresholds with get_md_max_age_seconds()
- Do NOT use get_md_status() (static) for production 15m markets
- Use get_md_status() only for legacy code or non-production tests
"""

from __future__ import annotations

from typing import Literal, Optional

# Re-export timing-aware functions as the canonical interface
from merid.event_venues.kalshi.sla_config import (
    get_md_max_age_seconds,
    get_md_status_timing_aware,
)

# Static SLA function - DEPRECATED for production 15m markets
# Keep only for legacy code or non-production tests
from merid.event_venues.kalshi.sla_config import get_md_status as get_md_status_static


def get_md_status(age_ms: int, minutes_to_expiry: Optional[float] = None) -> Literal["ok", "stale", "bad"]:
    """
    Get MD status based on age and time to expiry (canonical function).
    
    This is the ONLY function that should be used for staleness determination
    in production 15m crypto markets. It uses timing-aware thresholds that
    become stricter as contracts approach expiry.
    
    Args:
        age_ms: Time since last update in milliseconds
        minutes_to_expiry: Optional time to contract expiry in minutes.
                          If None, uses static fallback thresholds.
    
    Returns:
        Status: "ok", "stale", or "bad"
    
    Examples:
        >>> # Contract with 1 minute to expiry - very strict threshold
        >>> get_md_status(age_ms=500, minutes_to_expiry=1.0)
        'ok'
        >>> get_md_status(age_ms=1500, minutes_to_expiry=1.0)
        'stale'
        
        >>> # Contract with 10 minutes to expiry - moderate threshold
        >>> get_md_status(age_ms=1500, minutes_to_expiry=10.0)
        'ok'
        >>> get_md_status(age_ms=6000, minutes_to_expiry=10.0)
        'stale'
    """
    return get_md_status_timing_aware(age_ms, minutes_to_expiry)


def build_md_health_record(
    ticker: str,
    age_ms: int,
    seconds_to_expiry: Optional[float] = None
) -> dict:
    """
    Build a complete MD health record for monitoring and debugging.
    
    This helper encapsulates all MD staleness logic and provides a consistent
    structure for health endpoints, logging, and metrics.
    
    Args:
        ticker: Market ticker (e.g., "KXBTC15M-26MAY121130-30")
        age_ms: Time since last update in milliseconds
        seconds_to_expiry: Optional time to expiry in seconds
    
    Returns:
        Dict with keys:
            - ticker: Market ticker
            - age_ms: Time since last update
            - minutes_to_expiry: Time to expiry in minutes
            - max_age_ms: Maximum allowed age for this contract
            - status: "ok", "stale", or "bad"
    
    Example:
        >>> record = build_md_health_record(
        ...     ticker="KXBTC15M-26MAY121130-30",
        ...     age_ms=1800,
        ...     seconds_to_expiry=60
        ... )
        >>> record["status"]
        'stale'
        >>> record["max_age_ms"]
        1000  # 1 second for <2min expiry
    """
    minutes_to_expiry = seconds_to_expiry / 60.0 if seconds_to_expiry else None
    max_age_s = get_md_max_age_seconds(minutes_to_expiry)
    status = get_md_status(age_ms=age_ms, minutes_to_expiry=minutes_to_expiry)
    
    return {
        "ticker": ticker,
        "age_ms": age_ms,
        "minutes_to_expiry": minutes_to_expiry,
        "max_age_ms": max_age_s * 1000,
        "status": status,
    }
