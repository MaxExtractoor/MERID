"""Canonical Kalshi 15-minute crypto ticker time parsing (dependency-free).

Single source of truth for decoding the contract window end embedded in
compact 15m tickers (``KXBTC15M-26AUG031530-30``).  Extracted from
``merid.event_venues.kalshi.expiry_fallback`` so audit/analysis tooling can
parse boundaries WITHOUT importing the venue package (whose ``__init__``
pulls the live Kalshi client/config chain).

Formats
-------
- Canonical: ``KX{ASSET}15M-{YY}{MON}{DD}{HHMM}-{STRIKE}`` — HHMM is the
  window END in **America/New_York** (Kalshi's crypto event timezone),
  DST-aware via ZoneInfo.  Verified against venue ``close_time`` (<1s on
  sampled tickers; see ``merid.analysis.forecast_audit.boundary_verify``).
- Legacy (pre-2026-08 fixtures): ``KX{ASSET}15M-{DD}{MON}{HHMM[SS]}-{STRIKE}``
  in UTC, current year.  ``parse_kalshi_15m_ticker_expiry`` disambiguates by
  preferring the canonical parse.

Only stdlib imports — safe for offline audit tooling.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

_ET = ZoneInfo("America/New_York") if ZoneInfo else None

# KXBTC15M-26MAY201245-45 → date + time in ET; trailing -45 is strike price
# Format: KX[A-Z0-9]+15M-(YY)(MON)(DD)(HHMM)-STRIKE
_RE_15M_BODY = re.compile(
    r"^KX[A-Z0-9]+15M-(\d{2})([A-Z]{3})(\d{2})(\d{4})-\d+$",
    re.IGNORECASE,
)

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
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
        # ET expiry - callers must treat the result as degraded.
        return datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


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
    ambiguity by preferring the canonical year-first ET parse; legacy is only
    a fallback for tickers the canonical parser cannot parse.
    """
    if not ticker or "15M" not in ticker.upper():
        return None, False

    canonical_dt = parse_kalshi_15m_window_end_utc(ticker)
    legacy_dt = _parse_legacy_15m_expiry(ticker)

    canonical_match = bool(_RE_15M_SEARCH.search(ticker) or _RE_15M_BODY.search(ticker))
    legacy_match = bool(_RE_15M_LEGACY.search(ticker))
    is_15m_pattern = canonical_match or legacy_match

    # A legacy-regex body that fails to parse (e.g. 30FEB) is an invalid 15m
    # ticker and must force-expire ONLY when the canonical year-first parse
    # also failed.
    if canonical_dt is None and legacy_match and legacy_dt is None:
        return None, True

    # Prefer the canonical year-first ET parse: the legacy day-first regex
    # matches the same body, so disambiguating by "closest to now" incorrectly
    # flips to legacy for live day-24/31 tickers.
    if canonical_dt is not None:
        return canonical_dt, True

    if legacy_dt is not None:
        return legacy_dt, True

    return None, is_15m_pattern
