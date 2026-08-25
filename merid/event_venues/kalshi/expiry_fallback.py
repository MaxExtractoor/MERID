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
from typing import List, Optional, Tuple
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

# Search-based variant of the ticker body: -26AUG031530- → YY MON DD HHMM
_RE_15M_SEARCH = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(\d{4,6})-", re.IGNORECASE)

# Legacy test/live format used before 2026-08 canonical switch: DDMONHHMM[SS] in UTC
# e.g. KXBTC15M-04Aug0035-50 (day=04, month=Aug, time=00:35 UTC) or KXBTC15M-04Aug003558-50 (with seconds)
_RE_15M_LEGACY = re.compile(r"-(\d{2})([A-Z]{3})(\d{4,6})-", re.IGNORECASE)


def parse_kalshi_15m_window_end_utc(ticker: str) -> Optional[datetime]:
    """Canonical Kalshi 15m ticker expiry parser (single source of truth).

    Ticker format: KXBTC15M-26AUG031530-30 where the body 26AUG031530 is
    YY=26, MON=AUG, DD=03, HHMM=1530 in **America/New_York** (Kalshi's crypto
    event timezone). The encoded time IS the window end (expiry).

    API-confirmed: KXDOGE15M-26JUL111200-00 -> close_time 2026-07-11T16:00:00Z
    (12:00 ET = 16:00 UTC).

    CRITICAL FIX (2026-08-03): position_monitor, position_cache and diagnostics
    previously parsed this as DD=26, MON, HHMMSS=031530 UTC - off by ~26 days
    AND 4-5h. That neutered _is_expired_ticker (expired markets kept), the
    T-30s forced-exit settlement guard (never fired), and
    _calculate_dynamic_max_hold (always hit the >1day sanity fallback = 300s).

    Returns UTC datetime, or None if unparseable.
    """
    if not ticker:
        return None
    ticker = ticker.strip()
    # Try the anchored canonical regex first.  It requires the exact
    # YYMONDDHHMM-STRIKE body and prevents a 2-digit strike price from being
    # swallowed as seconds (e.g. 26AUG232330-30 must parse as HHMM=2330).
    m = _RE_15M_BODY.match(ticker)
    if m is None:
        # Fallback for search contexts / non-canonical test fixtures.
        m = _RE_15M_SEARCH.search(ticker)
    if not m:
        return None
    yy_s, mon_s, dd_s, hhmm_s = m.groups()
    month = _MONTHS.get(mon_s.upper())
    if not month:
        return None
    try:
        year = 2000 + int(yy_s)
        day = int(dd_s)

        # Kalshi crypto 15m tickers encode time as either HHMM (canonical) or
        # HHMMSS (legacy / test fixtures).  Anything else is unparseable.
        if len(hhmm_s) == 4:
            hh, mm = int(hhmm_s[:2]), int(hhmm_s[2:])
            ss = 0
        elif len(hhmm_s) == 6:
            hh, mm, ss = int(hhmm_s[:2]), int(hhmm_s[2:4]), int(hhmm_s[4:])
        else:
            return None

        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return None

        if _ET:
            return datetime(year, month, day, hh, mm, ss, tzinfo=_ET).astimezone(timezone.utc)
        # ZoneInfo unavailable (no tzdata): treat as UTC. Off by 4-5h from true
        # ET expiry - log loudly since expiry math degrades.
        logger.warning("[EXPIRY-PARSE] ZoneInfo/tzdata unavailable - parsing %s as UTC (ET intended)", ticker)
        return datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _infer_15m_window_end_utc(ticker: str) -> Optional[datetime]:
    end_utc = parse_kalshi_15m_window_end_utc(ticker)
    if end_utc is not None:
        logger.info("[EXPIRY-FALLBACK] ticker=%s → end_utc=%s (ticker time IS expiry, ET)", ticker, end_utc)
    return end_utc


def _parse_legacy_15m_expiry(ticker: str) -> Optional[datetime]:
    """Parse the legacy day-first UTC format DDMONHHMM[SS] (current year)."""
    m = _RE_15M_LEGACY.search(ticker)
    if not m:
        return None

    dd_s, mon_s, hhmmss_s = m.groups()
    month = _MONTHS.get(mon_s.upper())
    if not month:
        return None

    try:
        year = datetime.now(timezone.utc).year
        day = int(dd_s)
        hh = int(hhmmss_s[:2])
        mm = int(hhmmss_s[2:4])
        ss = int(hhmmss_s[4:6]) if len(hhmmss_s) >= 6 else 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return None
        return datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_kalshi_15m_ticker_expiry(ticker: str) -> Tuple[Optional[datetime], bool]:
    """Parse any supported Kalshi 15m crypto ticker expiry format.

    Returns:
        (expiry_utc, is_15m_pattern)
        - Canonical YYMONDDHHMM[SS] ET (year-first).
        - Legacy DDMONHHMMSS UTC (day-first, current year) used by old test
          fixtures and some internal helpers.

    The two formats are ambiguous in a raw 11-character body.  We resolve the
    ambiguity by computing both candidates and choosing the one closest to the
    current wall-clock time.  A legacy parse that fails because the date is
    invalid (e.g. 30FEB) is treated as an expired/invalid 15m ticker.
    """
    if not ticker or "15M" not in ticker.upper():
        return None, False

    canonical_dt = parse_kalshi_15m_window_end_utc(ticker)
    legacy_dt = _parse_legacy_15m_expiry(ticker)

    canonical_match = bool(_RE_15M_SEARCH.search(ticker) or _RE_15M_BODY.search(ticker))
    legacy_match = bool(_RE_15M_LEGACY.search(ticker))
    is_15m_pattern = canonical_match or legacy_match

    # CRITICAL FIX (2026-08-24): A legacy-regex body that fails to parse (e.g.
    # 30FEB) is an invalid 15m ticker and must force-expire ONLY when the
    # canonical year-first parse also failed.  The legacy day-first regex
    # matches the SAME body as the canonical year-first one, and for any ticker
    # with DD >= 24 the legacy read (DDMON + HHMMSS) yields hh >= 24 and fails.
    # Before this fix, on days 24-31 every live 15m position was rejected by
    # PositionMonitor as "expired/closed market" (canonical parse succeeded but
    # was never consulted), so no exit policy ever ran and losing positions
    # settled unmonitored at 100% loss.
    if canonical_dt is None and legacy_match and legacy_dt is None:
        return None, True

    # CRITICAL FIX (2026-08-24): Prefer the canonical year-first ET parse.
    # The legacy day-first regex matches the same body, so disambiguating by
    # "closest to now" incorrectly flips to legacy for live day-24/31 tickers.
    # Legacy is only a fallback for old test fixtures that the canonical parser
    # cannot parse.
    if canonical_dt is not None:
        return canonical_dt, True

    if legacy_dt is not None:
        return legacy_dt, True

    return None, is_15m_pattern


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
