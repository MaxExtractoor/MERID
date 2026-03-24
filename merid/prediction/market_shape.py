"""Canonical Kalshi market shape detection and normalization.

Transforms raw Kalshi markets into a structured representation so that
downstream sizing and guardrails can reason about direction, strikes,
and expiry without relying on brittle string assumptions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

# Supported market archetypes
MarketType = Literal["UP_DOWN", "THRESHOLD_LEQ", "THRESHOLD_GEQ"]


@dataclass
class KalshiMarketShape:
    """Normalized description of a Kalshi market."""

    asset: Optional[str]
    timeframe_label: Optional[str]
    expiry_ts: Optional[datetime]
    market_type: MarketType
    strike: Optional[float]
    yes_price: float
    no_price: float
    series_ticker: Optional[str] = None
    title: str = ""


_BELOW_PATTERNS = (
    "at or below",
    "or below",
    "below",
    "under",
    "≤",
    "<=",
)
_ABOVE_PATTERNS = (
    "at or above",
    "or above",
    "above",
    "over",
    "≥",
    ">=",
)


def _extract_strike(text: str) -> Optional[float]:
    """Extract a numeric strike from market text."""
    match = re.search(r"(?:above|below|over|under|at)\s*\$?([\d,]+\.?\d*)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    # Allow bare numbers as fallback (e.g., "59099.99")
    num_match = re.search(r"\$?([\d,]+\.?\d+)", text)
    if num_match:
        try:
            return float(num_match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _detect_market_type(text: str, strike_present: bool) -> MarketType:
    """Classify market into UP/DOWN vs threshold directions."""
    lowered = text.lower()
    if "up or down" in lowered or "up/down" in lowered or "up or" in lowered and "down" in lowered:
        return "UP_DOWN"
    if any(pat in lowered for pat in _BELOW_PATTERNS):
        return "THRESHOLD_LEQ"
    if any(pat in lowered for pat in _ABOVE_PATTERNS):
        return "THRESHOLD_GEQ"
    # If we detected a strike but no explicit direction, default to GEQ
    if strike_present:
        return "THRESHOLD_GEQ"
    return "UP_DOWN"


def _fallback_timeframe(minutes_to_expiry: Optional[float]) -> Optional[str]:
    """Infer timeframe label from minutes to expiry."""
    if minutes_to_expiry is None:
        return None
    if minutes_to_expiry <= 25:
        return "15M"
    if minutes_to_expiry <= 120:
        return "1H"
    if minutes_to_expiry <= 60 * 24:
        return "1D"
    if minutes_to_expiry <= 60 * 24 * 7:
        return "1W"
    return None


def build_market_shape(
    market: "EventMarket",
    *,
    catalog_market: Optional["CatalogMarket"] = None,
    asset: Optional[str] = None,
    now: Optional[datetime] = None,
) -> KalshiMarketShape:
    """Normalize an EventMarket into KalshiMarketShape."""
    from merid.event_venues.base import EventOutcome  # Local import to avoid cycles

    now = now or datetime.now(timezone.utc)
    text = f"{market.market_id} {market.question or ''} {market.description or ''}"
    strike = catalog_market.strike_price if catalog_market else None
    if strike is None:
        strike = _extract_strike(text)

    expiry_ts = market.end_date
    minutes_to_expiry = None
    if expiry_ts and expiry_ts > now:
        minutes_to_expiry = (expiry_ts - now).total_seconds() / 60.0

    timeframe_label = None
    if catalog_market and getattr(catalog_market, "timeframe", None):
        timeframe_label = str(catalog_market.timeframe or "").upper() or None
    if timeframe_label is None:
        timeframe_label = _fallback_timeframe(minutes_to_expiry)

    market_type = _detect_market_type(text, strike_present=strike is not None)

    yes_price = 50.0
    no_price = 50.0
    for outcome in market.outcomes or []:
        if not isinstance(outcome, EventOutcome):
            continue
        if outcome.outcome_id == "yes":
            yes_price = float(outcome.price * 100)
        elif outcome.outcome_id == "no":
            no_price = float(outcome.price * 100)

    return KalshiMarketShape(
        asset=asset,
        timeframe_label=timeframe_label,
        expiry_ts=expiry_ts,
        market_type=market_type,
        strike=strike,
        yes_price=yes_price,
        no_price=no_price,
        series_ticker=getattr(catalog_market, "series_ticker", None) if catalog_market else None,
        title=market.question or "",
    )

