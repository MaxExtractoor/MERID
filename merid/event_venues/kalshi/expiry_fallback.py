"""Best-effort expiry repair for Kalshi crypto interval contracts.

The REST catalog sometimes yields ``close_time`` / ``end_date`` that are missing,
stale, or already in the past while the contract is still open. For compact
15-minute tickers (``KXBTC15M-26APR071830-30``) we can infer the window from
the ticker and use **America/New_York** (Kalshi's typical crypto event timezone)
then convert to UTC for comparisons with ``now``.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional
from utils.logger import get_logger

logger = get_logger("expiry_fallback")

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from merid.event_venues.base import EventMarket

_ET = ZoneInfo("America/New_York") if ZoneInfo else None

# KXBTC15M-26MAY201245-45 → date + time in ET; trailing -45 is strike price
# Format: KX[A-Z0-9]+15M-(YY)(MON)(DD)(HHMM)-STRIKE
_RE_15M_BODY = re.compile(
    r"^KX[A-Z0-9]+15M-(\d{2})([A-Z]{3})(\d{2})(\d{4})-\d+$",
    re.IGNORECASE,
)

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _infer_15m_window_end_utc(ticker: str) -> Optional[datetime]:
    m = _RE_15M_BODY.match(ticker.strip())
    if not m:
        return None
    yy_s, mon_s, dd_s, hhmm_s = m.groups()
    try:
        year = 2000 + int(yy_s)
        month = _MONTHS.get(mon_s.upper())
        if not month:
            return None
        day = int(dd_s)
        hh = int(hhmm_s) // 100
        mm = int(hhmm_s) % 100
        
        # CRITICAL FIX: The ticker format is KXBTC15M-26JUL111200-00 where the time is the END time in Eastern Time
        # The ticker represents the window END time (expiry), not the start time
        # For example: KXBTC15M-26JUL111200-00 means the market closes at 12:00 ET on July 11, 2026
        # The market runs for 15 minutes BEFORE this time (11:45-12:00 ET)
        # This is confirmed by API data: KXDOGE15M-26JUL111200-00 has close_time=2026-07-11T16:00:00Z
        # Ticker time 1200 ET = 16:00 UTC, which matches API close_time exactly
        
        if _ET:
            end_et = datetime(year, month, day, hh, mm, tzinfo=_ET)
            end_utc = end_et.astimezone(timezone.utc)
        else:
            # Fallback if ZoneInfo not available (treat as UTC, but this is incorrect)
            end_utc = datetime(year, month, day, hh, mm, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    
    # CRITICAL FIX: The ticker time IS the expiry time (window end)
    # No need to add 15 minutes - the ticker already represents the window end
    # end_utc = end_utc  # (already set above)
    
    # DEBUG: Log inferred expiry for debugging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "[EXPIRY-FALLBACK] ticker=%s parsed: %s-%02d-%02d %02d:%02d ET → end_utc=%s (ticker time IS expiry)",
        ticker, year, month, day, hh, mm, end_utc
    )
    return end_utc


def expiry_fallback_enabled() -> bool:
    return os.getenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_crypto_interval_expiry_fallback(m: EventMarket, now: datetime) -> EventMarket:
    """Use ticker-based repair ONLY when API fields are missing or invalid.
    
    CRITICAL REFACTOR: This is now a fallback, not the primary source of truth.
    Kalshi's close_ts/close_time should be used when available.
    Ticker-based inference is only used when API fields are completely missing.
    """
    
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
