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

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from merid.event_venues.base import EventMarket

_ET = ZoneInfo("America/New_York") if ZoneInfo else None

# KXBTC15M-26APR071830-30 → date + time in ET; trailing -30 is an exchange-specific token (ignored for duration)
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
    if _ET is None:
        return None
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
        start_et = datetime(year, month, day, hh, mm, tzinfo=_ET)
    except (ValueError, TypeError):
        return None
    end_et = start_et + timedelta(minutes=15)
    return end_et.astimezone(timezone.utc)


def expiry_fallback_enabled() -> bool:
    return os.getenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_crypto_interval_expiry_fallback(m: EventMarket, now: datetime) -> EventMarket:
    """If ``end_date`` is missing or not after ``now``, try ticker-based repair for KX*15M."""
    if not expiry_fallback_enabled():
        return m
    tid = (m.market_id or "").strip().upper()
    if "15M" not in tid or not tid.startswith("KX"):
        return m
    inferred = _infer_15m_window_end_utc(m.market_id or "")
    if inferred is None:
        return m
    cur = m.end_date
    if cur is not None and cur.tzinfo is None:
        cur = cur.replace(tzinfo=timezone.utc)
    if cur is not None and cur > now:
        return m
    # Missing, stale, or already past — use inferred window end
    return replace(m, end_date=inferred)
