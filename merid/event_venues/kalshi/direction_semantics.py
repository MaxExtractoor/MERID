"""Kalshi Direction Semantics — Single source of truth for up/down contract logic.

This module provides the canonical implementation of Kalshi's crypto up/down
contract settlement rules as documented at:
https://help.kalshi.com/en/articles/13823838-crypto-markets

Key principles:
- "UP" markets: YES wins when CF Benchmarks RTI ≥ strike
- "DOWN" markets: YES wins when CF Benchmarks RTI < strike
- Direction is parsed from market ticker, title, and description
- Never guess direction or strike — must come from Kalshi API response

Usage::

    from merid.event_venues.kalshi.direction_semantics import (
        kalshi_is_yes_winner,
        determine_kalshi_side,
        parse_kalshi_crypto_direction,
    )

    # Settlement logic
    winner = kalshi_is_yes_winner(
        settlement_rti=50050.0,
        strike=50000.0,
        direction="up"
    )  # True (YES wins)

    # Forecast-to-side conversion
    side = determine_kalshi_side(
        forecast_direction="bullish",
        market_direction="up"
    )  # "yes"
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.direction_semantics")


def kalshi_is_yes_winner(
    settlement_rti: float,
    strike: float,
    direction: str,
) -> bool:
    """Determine if YES side wins for a Kalshi crypto up/down market.

    Per Kalshi's official specification (help.kalshi.com/en/articles/13823838):
    - "UP" markets: YES wins when CF Benchmarks RTI average ≥ strike
    - "DOWN" markets: YES wins when CF Benchmarks RTI average < strike

    Args:
        settlement_rti: CF Benchmarks RTI average over the settlement window.
        strike: Target level from the contract definition.
        direction: Market direction, either "up" or "down".

    Returns:
        True if YES side wins, False if NO side wins.

    Raises:
        ValueError: If direction is not "up" or "down".

    Examples:
        >>> kalshi_is_yes_winner(50050.0, 50000.0, "up")
        True  # RTI ≥ strike on UP market

        >>> kalshi_is_yes_winner(49950.0, 50000.0, "up")
        False  # RTI < strike on UP market

        >>> kalshi_is_yes_winner(49950.0, 50000.0, "down")
        True  # RTI < strike on DOWN market

        >>> kalshi_is_yes_winner(50050.0, 50000.0, "down")
        False  # RTI ≥ strike on DOWN market
    """
    direction_lower = direction.lower().strip()

    if direction_lower not in ("up", "down"):
        raise ValueError(
            f"Invalid direction '{direction}'. Must be 'up' or 'down'."
        )

    if direction_lower == "up":
        # UP market: YES wins when settlement ≥ strike
        return settlement_rti >= strike
    else:
        # DOWN market: YES wins when settlement < strike
        return settlement_rti < strike


def parse_kalshi_crypto_direction(
    ticker: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[str]:
    """Extract direction ("up" or "down") from Kalshi market metadata.

    Parsing priority:
    1. Explicit "up" or "down" in title (e.g., "Bitcoin price up/down")
    2. "above"/"at or above" language → "up"
    3. "below" language → "down"
    4. Ticker suffix patterns (if established)

    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-25DEC262200").
        title: Market title/question text.
        description: Market description text.

    Returns:
        "up" or "down" if direction can be determined, None otherwise.

    Examples:
        >>> parse_kalshi_crypto_direction(
        ...     "KXBTC15M-25DEC262200",
        ...     "Bitcoin price at or above $50,000?"
        ... )
        'up'

        >>> parse_kalshi_crypto_direction(
        ...     "KXBTC15M-25DEC262200",
        ...     "Bitcoin price below $50,000?"
        ... )
        'down'
    """
    # Combine all text for pattern matching
    combined_text = " ".join(filter(None, [ticker, title or "", description or ""]))

    if not combined_text.strip():
        return None

    # Pattern 1: Explicit "up" or "down" mention
    up_down_match = re.search(r'\b(up|down)\b', combined_text, re.IGNORECASE)
    if up_down_match:
        return up_down_match.group(1).lower()

    # Pattern 2: "above", "at or above", "over" → up
    if re.search(r'\b(above|at\s+or\s+above|over|higher\s+than)\b', combined_text, re.IGNORECASE):
        return "up"

    # Pattern 3: "below", "under" → down
    if re.search(r'\b(below|under|less\s+than)\b', combined_text, re.IGNORECASE):
        return "down"

    # No clear direction found
    logger.debug(
        "Could not parse direction from market: ticker=%s, title=%s",
        ticker, title
    )
    return None


def determine_kalshi_side(
    forecast_direction: str,
    market_direction: str,
) -> str:
    """Map forecast direction to Kalshi YES/NO side.

    Logic table:
    - Bullish + "up" market   → "yes" (bet price goes up)
    - Bullish + "down" market → "no"  (bet price doesn't go down)
    - Bearish + "up" market   → "no"  (bet price doesn't go up)
    - Bearish + "down" market → "yes" (bet price goes down)

    Args:
        forecast_direction: Model forecast, either "bullish" or "bearish".
        market_direction: Market direction from Kalshi, either "up" or "down".

    Returns:
        "yes" or "no"

    Raises:
        ValueError: If either direction parameter is invalid.

    Examples:
        >>> determine_kalshi_side("bullish", "up")
        'yes'

        >>> determine_kalshi_side("bullish", "down")
        'no'

        >>> determine_kalshi_side("bearish", "up")
        'no'

        >>> determine_kalshi_side("bearish", "down")
        'yes'
    """
    forecast_lower = forecast_direction.lower().strip()
    market_lower = market_direction.lower().strip()

    if forecast_lower not in ("bullish", "bearish"):
        raise ValueError(
            f"Invalid forecast_direction '{forecast_direction}'. "
            "Must be 'bullish' or 'bearish'."
        )

    if market_lower not in ("up", "down"):
        raise ValueError(
            f"Invalid market_direction '{market_direction}'. "
            "Must be 'up' or 'down'."
        )

    # Bullish forecast
    if forecast_lower == "bullish":
        return "yes" if market_lower == "up" else "no"

    # Bearish forecast
    else:
        return "no" if market_lower == "up" else "yes"


def get_strike_from_market(market: Any) -> Optional[float]:
    """Extract strike/reference price from Kalshi market object.

    Never guesses the strike — must come directly from the market metadata.
    Returns None if strike cannot be reliably determined.

    Args:
        market: Kalshi EventMarket object or dict with market data.

    Returns:
        Strike price as float, or None if not available.
    """
    # Handle both dict and object access patterns
    strike = None

    # Try dict-style access first
    if isinstance(market, dict):
        strike = market.get("strike_price") or market.get("strike")

    # Try object attribute access
    elif hasattr(market, "strike_price"):
        strike = market.strike_price
    elif hasattr(market, "strike"):
        strike = market.strike

    # Validate strike
    if strike is not None:
        try:
            strike_float = float(strike)
            if strike_float > 0:
                return strike_float
        except (TypeError, ValueError):
            logger.warning(
                "Invalid strike value: %s (type: %s)",
                strike, type(strike)
            )

    return None
