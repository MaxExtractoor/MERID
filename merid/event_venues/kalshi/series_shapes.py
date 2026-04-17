"""RTI/Series→bucket mapping with hard-fail semantics.

Undefined series shapes raise ValueError with [RTI-UNDEFINED] marker.
No fall-through behavior; undefined rules fail fast.
"""

from merid.event_venues.kalshi.market_selector import (
    CRYPTO_SERIES_BASE,
    TIMEFRAME_SERIES_SUFFIX,
)


def get_series_timeframe_bucket(series_ticker: str) -> str:
    """Return bucket for series. Hard-fail on undefined shapes.

    Args:
        series_ticker: Series ticker like "KXBTC-15M" or "KXETH-D1".

    Returns:
        Canonical bucket string "BASE:TF".

    Raises:
        ValueError: If series_ticker is malformed, empty, or references
                    unknown base/timeframe components. Error message includes
                    [RTI-UNDEFINED] marker for log filtering.
    """
    if not series_ticker or "-" not in series_ticker:
        raise ValueError(f"[RTI-UNDEFINED] Invalid series_ticker: {series_ticker!r}")

    parts = series_ticker.split("-")
    if len(parts) != 2:
        raise ValueError(
            f"[RTI-UNDEFINED] Series {series_ticker!r} has invalid shape (expected BASE-TF)"
        )

    base, tf = parts

    valid_bases = set(CRYPTO_SERIES_BASE.values())
    if base not in valid_bases:
        raise ValueError(f"[RTI-UNDEFINED] Unknown base: {base!r}")

    valid_timeframes = set(TIMEFRAME_SERIES_SUFFIX.values())
    if tf not in valid_timeframes:
        raise ValueError(f"[RTI-UNDEFINED] Unknown timeframe suffix: {tf!r}")

    return f"{base}:{tf}"
