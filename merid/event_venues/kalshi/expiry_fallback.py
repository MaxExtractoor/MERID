"""Best-effort expiry repair for Kalshi crypto interval contracts.

The REST catalog sometimes yields ``close_time`` / ``end_date`` that are missing,
stale, or already in the past while the contract is still open. For compact
15-minute tickers (``KXBTC15M-26APR071830-30``) we can infer the window from
the ticker and use **America/New_York** (Kalshi's typical crypto event timezone)
then convert to UTC for comparisons with ``now``.

Canonical parsing lives in ``merid.ticker_time`` (dependency-free) so audit
tooling can decode boundaries without importing the venue package.  This
module re-exports the parsers and keeps the ``EventMarket`` repair path.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional, Tuple
from utils.logger import get_logger

logger = get_logger("expiry_fallback")

# Canonical parsers — single source of truth in merid.ticker_time.
from merid.ticker_time import (  # noqa: E402
    parse_kalshi_15m_window_end_utc,
    parse_kalshi_15m_ticker_expiry,
    _parse_legacy_15m_expiry,
)

__all__ = [
    "parse_kalshi_15m_window_end_utc",
    "parse_kalshi_15m_ticker_expiry",
    "expiry_fallback_enabled",
    "apply_crypto_interval_expiry_fallback",
]

_last_inferred_log = {}


def _infer_15m_window_end_utc(ticker: str) -> Optional[datetime]:
    end_utc = parse_kalshi_15m_window_end_utc(ticker)
    if end_utc is not None:
        # 2026-11-03: dedup — the same ticker→end_utc pair re-logged every
        # catalog refresh (~1022 INFO/30min) fed the LOG-QUEUE growth for
        # zero information.  Log first sight per (ticker, value) only.
        key = end_utc.isoformat()
        if _last_inferred_log.get(ticker) != key:
            _last_inferred_log[ticker] = key
            logger.info("[EXPIRY-FALLBACK] ticker=%s → end_utc=%s (ticker time IS expiry, ET)", ticker, end_utc)
    return end_utc


def expiry_fallback_enabled() -> bool:
    return os.getenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_crypto_interval_expiry_fallback(m, now: datetime):
    """Use ticker-based repair ONLY when API fields are missing or invalid.

    CRITICAL REFACTOR: This is now a fallback, not the primary source of truth.
    Kalshi's close_ts/close_time should be used when available.
    Ticker-based inference is only used when API fields are completely missing.
    """
    # Lazy import: keeps this module importable without the venue base chain.
    from merid.event_venues.base import EventMarket  # noqa: F401

    if not expiry_fallback_enabled():
        logger.debug("[EXPIRY-FALLBACK] Disabled - MERID_PM_EXPIRY_FALLBACK_CRYPTO not set")
        return m
    tid = (m.market_id or "").strip().upper()
    if "15M" not in tid or not tid.startswith("KX"):
        logger.debug("[EXPIRY-FALLBACK] Skipped - ticker does not match pattern: %s", tid)
        return m

    # CRITICAL: Only use ticker-based inference if API fields are missing or invalid
    # If end_date exists and is reasonable, trust it over ticker parsing
    cur = m.end_date
    if cur is not None and cur.tzinfo is None:
        cur = cur.replace(tzinfo=timezone.utc)

    # Check if existing end_date is reasonable (not in the distant past)
    if cur is not None:
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        time_diff = (cur - now_utc).total_seconds()
        # If end_date is in the future (positive time_diff), trust it regardless of magnitude
        # If end_date is in the past but within -1 hour (recently expired), also trust it
        # Only replace if end_date is in the distant past (more than 1 hour ago)
        if time_diff >= -3600:
            logger.debug("[EXPIRY-FALLBACK] Skipping - API end_date is reasonable: ticker=%s end_date=%s time_diff=%s",
                        m.market_id, cur, time_diff)
            return m

    # Only use ticker inference if API fields are missing or unreasonable
    inferred = _infer_15m_window_end_utc(m.market_id or "")
    if inferred is None:
        logger.warning("[EXPIRY-FALLBACK] Failed to infer expiry from ticker: %s", m.market_id)
        return m

    logger.info("[EXPIRY-FALLBACK] Applying fallback (API fields missing/invalid) - ticker=%s old_end_date=%s new_end_date=%s",
                m.market_id, cur, inferred)
    return replace(m, end_date=inferred)
