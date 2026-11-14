"""Parse the contractual reference windows out of Kalshi ``rules_primary``.

The 15m crypto rules state e.g.::

    "If the simple average of the sixty seconds of CF Benchmarks' ETHUSDRTI
     before 12:00 AM EST on Nov 14, 2026 is at least the simple average of
     the sixty seconds ... before 11:45 PM EST on Nov 13, 2026 ..."

First stated time = CLOSING reference window end; second = OPENING window
end.  The stated wall time is ET; the sixty-second observation window
precedes it (``[T-60, T)`` per ``boundary_verify`` semantics).

Dependency-free (stdlib only) so boundary resolution stays import-light.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

_RULES_TIME_RE = re.compile(
    r"before\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s+(E[DS]T)\s+on\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)

# "the sixty seconds of CF Benchmarks' ..." — observation-window duration.
_RULES_WINDOW_RE = re.compile(
    r"(?:the\s+)?([a-zA-Z]+)\s+seconds?\s+of\s+CF\s+Benchmarks", re.IGNORECASE)

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,
           "AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}


def rules_window_seconds(rules_primary: str) -> Optional[int]:
    """Observation-window duration in seconds stated by the rules text."""
    m = _RULES_WINDOW_RE.search(rules_primary or "")
    if not m:
        return None
    word = m.group(1).lower()
    if word.isdigit():
        return int(word)
    return _NUM_WORDS.get(word)


def parse_rules_windows(rules_primary: str) -> Dict[str, Any]:
    """Extract opening/closing reference-window boundaries from rules text.

    Returns window end timestamps (UTC epoch) parsed from the rules' own
    stated ET times, the stated observation-window duration, plus the exact
    supporting passages.  Never infers the window from API timestamp names —
    the rules text is the authority.
    """
    out: Dict[str, Any] = {"passages": [], "close_window_end_ts": None,
                           "open_window_end_ts": None,
                           "window_seconds": rules_window_seconds(rules_primary)}
    if not rules_primary:
        return out
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:
        return out
    from datetime import timezone
    matches = list(_RULES_TIME_RE.finditer(rules_primary))
    for i, m in enumerate(matches):
        hh, mm, ampm, _tz, mon_s, dd, yy = m.groups()
        mon = _MONTHS.get(mon_s[:3].upper())
        if mon is None:
            continue
        hour = int(hh) % 12 + (12 if ampm.upper() == "PM" else 0)
        try:
            dt = datetime(int(yy), mon, int(dd), hour, int(mm), tzinfo=et)
        except ValueError:
            continue
        span = rules_primary[max(0, m.start() - 120):m.end() + 10]
        out["passages"].append(span.strip())
        key = "close_window_end_ts" if i == 0 else "open_window_end_ts"
        if out.get(key) is None:
            out[key] = dt.astimezone(timezone.utc).timestamp()
    return out
