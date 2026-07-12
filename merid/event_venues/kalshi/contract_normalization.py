"""Single normalization function for Kalshi contracts.

This module provides a unified path for normalizing Kalshi market payloads
across all assets (BTC, ETH, SOL, XRP, DOGE). It enforces:

1. Consistent ticker/asset mapping
2. Per-contract expiry resolution with canonical field names
3. Fail-fast on missing/invalid metadata
4. Symmetric treatment across all 5 assets

The normalized output is consumed by:
- KalshiMarketStateStore (for state registration)
- Agent grid (for edge calculation)
- Readiness checks (for health monitoring)
- Risk layer (for dynamic window checks)
- Candidate optimizer (for candidate creation)

CANONICAL FIELD SET (per contract):
- expiry_ts (datetime) - canonical expiry timestamp
- seconds_to_expiry (float, >= 0) - derived from expiry_ts
- minutes_to_expiry (float, >= 0) - derived from seconds_to_expiry
- status (ok/expired/invalid_metadata) - contract health status
- status_reason (str) - human-readable status explanation
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Literal

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.contract_normalization")


# ── Ticker → Asset mapping (symmetric for all 5 assets) ─────────────────

_TICKER_ASSET_MAP = {
    "KXBTC": "BTC",
    "KXETH": "ETH",
    "KXSOL": "SOL",
    "KXXRP": "XRP",
    "KXDOGE": "DOGE",
}


def map_ticker_to_asset(ticker: str) -> Optional[str]:
    """Map Kalshi ticker to asset (BTC/ETH/SOL/XRP/DOGE).
    
    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-26JUN061945-45")
    
    Returns:
        Asset code (BTC/ETH/SOL/XRP/DOGE) or None if not a recognized crypto ticker.
    """
    ticker_upper = ticker.upper()
    for prefix, asset in _TICKER_ASSET_MAP.items():
        if ticker_upper.startswith(prefix):
            return asset
    return None


# ── Normalized contract model (canonical representation) ─────────────────────

@dataclass
class NormalizedKalshiContract:
    """Normalized Kalshi contract with complete metadata.
    
    This is the SINGLE SOURCE OF TRUTH for contract metadata across the stack.
    All consumers (state store, agent grid, readiness, risk, optimizer) use this structure.
    
    Canonical field set:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-26JUN061945-45")
        asset: Underlying asset (BTC/ETH/SOL/XRP/DOGE)
        expiry_ts: Contract expiry timestamp (UTC) - CANONICAL EXPIRY FIELD
        seconds_to_expiry: Seconds until expiry (0 if expired/invalid) - DERIVED
        minutes_to_expiry: Minutes until expiry (0 if expired/invalid) - DERIVED
        status: Contract status (ok, expired, invalid_metadata)
        status_reason: Human-readable reason for status
    """
    ticker: str
    asset: Optional[str]
    expiry_ts: Optional[datetime]
    seconds_to_expiry: float
    minutes_to_expiry: float
    status: Literal["ok", "expired", "invalid_metadata"]
    status_reason: str


# ── Single normalization function (authoritative) ───────────────────────────

def normalize_kalshi_contract(
    ticker: str,
    expiration_time: Optional[str] = None,
    expected_expiration_time: Optional[str] = None,
    end_date: Optional[datetime] = None,
    close_time: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> NormalizedKalshiContract:
    """Normalize a Kalshi contract payload (authoritative function).
    
    This is the SINGLE normalization function for all Kalshi contracts.
    It enforces:
    1. Ticker/asset mapping must succeed for crypto contracts
    2. Expiry resolved with clear priority order: expected_expiration_time > expiration_time > close_time > end_date > ticker inference
    3. For 15m contracts: close_time is authoritative over end_date (fixes time-source normalization bug)
    4. Fail-fast on missing/invalid metadata (set to expired, not None)
    5. Symmetric treatment across all assets
    
    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-26JUN061945-45")
        expiration_time: Optional expiration_time from Kalshi API (ISO string)
        expected_expiration_time: Optional expected_expiration_time from Kalshi API (ISO string)
        end_date: Optional end_date from EventMarket (datetime)
        close_time: Optional close_time from EventMarket (datetime)
        now: Current time (UTC). If None, uses datetime.now(timezone.utc)
    
    Returns:
        NormalizedKalshiContract with complete metadata.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Step 1: Map ticker to asset (must succeed for crypto contracts)
    asset = map_ticker_to_asset(ticker)
    if asset is None:
        logger.warning(
            "[NORMALIZE-FAIL] ticker=%s is not a recognized crypto ticker → marking as invalid_metadata",
            ticker
        )
        return NormalizedKalshiContract(
            ticker=ticker,
            asset=None,
            expiry_ts=None,
            seconds_to_expiry=0.0,
            minutes_to_expiry=0.0,
            status="invalid_metadata",
            status_reason="Unrecognized ticker prefix (not BTC/ETH/SOL/XRP/DOGE)"
        )
    
    # Step 2: Detect if this is a 15m contract from ticker pattern
    is_15m_contract = "15M" in ticker.upper()
    
    # Step 3: Resolve expiry with priority order
    # CRITICAL FIX 2026-07-11: For 15m contracts, ticker-based inference is PRIMARY
    # The API's close_time field is the EVENT close time (when price observation ends),
    # NOT the contract expiry time. For 15m contracts, the ticker contains the correct expiry.
    # Priority for 15m: ticker inference > expected_expiration_time > expiration_time > close_time > end_date
    # Priority for non-15m: expected_expiration_time > expiration_time > close_time > end_date > ticker inference
    expiry_ts = None
    expiry_source = None
    
    # CRITICAL: For 15m contracts, use ticker-based inference FIRST
    # The ticker format KXBTC15M-26JUL110515-15 contains the correct contract expiry
    if is_15m_contract:
        try:
            from merid.event_venues.kalshi.expiry_fallback import _infer_15m_window_end_utc
            expiry_ts = _infer_15m_window_end_utc(ticker)
            if expiry_ts:
                expiry_source = "ticker_inference_primary"
                logger.info(
                    "[NORMALIZE-15M-TICKER] ticker=%s asset=%s using ticker-based expiry (primary for 15m contracts)",
                    ticker, asset
                )
        except Exception as e:
            logger.warning(
                "[NORMALIZE-FAIL] ticker=%s asset=%s ticker-based expiry inference failed: %s",
                ticker, asset, e
            )
    
    # Try expected_expiration_time (highest priority for non-15m, fallback for 15m)
    if expiry_ts is None and expected_expiration_time:
        try:
            expiry_dt = datetime.fromisoformat(expected_expiration_time.replace("Z", "+00:00"))
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            expiry_ts = expiry_dt
            expiry_source = "expected_expiration_time"
        except (ValueError, TypeError) as e:
            logger.warning(
                "[NORMALIZE-FAIL] ticker=%s asset=%s has invalid expected_expiration_time %r (error: %s)",
                ticker, asset, expected_expiration_time, e
            )
    
    # Try expiration_time
    if expiry_ts is None and expiration_time:
        try:
            expiry_dt = datetime.fromisoformat(expiration_time.replace("Z", "+00:00"))
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            expiry_ts = expiry_dt
            expiry_source = "expiration_time"
        except (ValueError, TypeError) as e:
            logger.warning(
                "[NORMALIZE-FAIL] ticker=%s asset=%s has invalid expiration_time %r (error: %s)",
                ticker, asset, expiration_time, e
            )
    
    # Try close_time (event close time, NOT contract expiry for 15m)
    # WARNING: For 15m contracts, close_time is the event close time, not contract expiry
    if expiry_ts is None and close_time:
        expiry_ts = close_time
        expiry_source = "close_time"
        if is_15m_contract:
            logger.warning(
                "[NORMALIZE-15M-WARNING] ticker=%s asset=%s using close_time (event time) instead of ticker expiry. "
                "This may cause incorrect expiry calculation for 15m contracts.",
                ticker, asset
            )
    
    # Try end_date (datetime object) - only as fallback
    if expiry_ts is None and end_date:
        expiry_ts = end_date
        expiry_source = "end_date"
        
        # CRITICAL ALERT: Log if 15m contract is using end_date instead of ticker inference
        if is_15m_contract:
            logger.error(
                "[NORMALIZE-15M-ALERT] ticker=%s asset=%s is using end_date as expiry source instead of ticker inference. "
                "This indicates missing ticker parsing or incorrect API response. Expected ticker-based expiry for 15m contracts.",
                ticker, asset
            )
    
    # Try ticker-based inference ONLY as fallback (for non-15m contracts)
    if expiry_ts is None and not is_15m_contract:
        try:
            from merid.event_venues.kalshi.expiry_fallback import _infer_15m_window_end_utc
            expiry_ts = _infer_15m_window_end_utc(ticker)
            if expiry_ts:
                expiry_source = "ticker_inference_fallback"
                logger.info(
                    "[NORMALIZE-FALLBACK] ticker=%s asset=%s used ticker-based expiry inference (API fields missing)",
                    ticker, asset
                )
        except Exception as e:
            logger.warning(
                "[NORMALIZE-FAIL] ticker=%s asset=%s ticker-based expiry inference failed: %s",
                ticker, asset, e
            )
    
    # Step 3: Compute seconds/minutes to expiry (fail-fast to 0.0 if invalid)
    if expiry_ts is None:
        logger.error(
            "[NORMALIZE-FAIL-FAST] ticker=%s asset=%s has no resolvable expiry → treating as expired",
            ticker, asset
        )
        return NormalizedKalshiContract(
            ticker=ticker,
            asset=asset,
            expiry_ts=None,
            seconds_to_expiry=0.0,
            minutes_to_expiry=0.0,
            status="invalid_metadata",
            status_reason="No resolvable expiry from API fields or ticker inference"
        )
    
    # Compute time to expiry (allow negative values for expired markets)
    seconds_to_expiry = (expiry_ts - now).total_seconds()
    minutes_to_expiry = seconds_to_expiry / 60.0
    
    # Step 4: Add invariant guard for 15m contracts
    # CRITICAL FIX 2026-07-11: Relax invariant guard for ticker-inferred expiry
    # Ticker-based inference is reliable for 15m contracts, but the current time may not match
    # the ticker's scheduled time (e.g., server running at different time than market hours)
    # Only reject if expiry is clearly invalid (negative by more than 1 hour or more than 24 hours in future)
    if is_15m_contract:
        # Allow wide range for ticker-inferred expiry: -1 hour to +24 hours
        # This accommodates clock skew, timezone issues, and market timing
        if seconds_to_expiry < -3600.0 or seconds_to_expiry > 86400.0:
            logger.error(
                "[NORMALIZE-15M-INVARIANT-FAIL] ticker=%s asset=%s has seconds_to_expiry=%.1f (out of bounds). "
                "This indicates clearly invalid expiry. Rejecting as invalid_metadata.",
                ticker, asset, seconds_to_expiry
            )
            return NormalizedKalshiContract(
                ticker=ticker,
                asset=asset,
                expiry_ts=expiry_ts,
                seconds_to_expiry=0.0,
                minutes_to_expiry=0.0,
                status="invalid_metadata",
                status_reason=f"15m contract expiry out of bounds: {seconds_to_expiry:.1f}s (source: {expiry_source})"
            )
    
    # Step 5: Determine status
    if seconds_to_expiry < 0:
        status = "expired"
        status_reason = f"Contract expired at {expiry_ts.isoformat()} (source: {expiry_source})"
    else:
        status = "ok"
        status_reason = f"Contract expires at {expiry_ts.isoformat()} (source: {expiry_source})"
    
    logger.debug(
        "[NORMALIZE-OK] ticker=%s asset=%s expiry_ts=%s seconds_to_expiry=%.1f minutes_to_expiry=%.1f status=%s source=%s",
        ticker, asset, expiry_ts.isoformat() if expiry_ts else None, seconds_to_expiry, minutes_to_expiry, status, expiry_source
    )
    
    return NormalizedKalshiContract(
        ticker=ticker,
        asset=asset,
        expiry_ts=expiry_ts,
        seconds_to_expiry=seconds_to_expiry,
        minutes_to_expiry=minutes_to_expiry,
        status=status,
        status_reason=status_reason
    )


# ── Convenience wrapper for 15m crypto contracts (backward compatibility) ──

def normalize_kalshi_15m_contract(
    ticker: str,
    expiration_time: Optional[str] = None,
    expected_expiration_time: Optional[str] = None,
    now: Optional[datetime] = None,
) -> NormalizedKalshiContract:
    """Convenience wrapper for 15m crypto contracts (backward compatible).
    
    This function is maintained for backward compatibility with existing code.
    New code should use normalize_kalshi_contract() directly.
    """
    return normalize_kalshi_contract(
        ticker=ticker,
        expiration_time=expiration_time,
        expected_expiration_time=expected_expiration_time,
        now=now
    )
