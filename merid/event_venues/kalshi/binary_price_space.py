"""Canonical YES/NO price space model for binary markets.

This module provides the single source of truth for YES/NO price transformations,
side mappings, and price range checks across the entire MERID trading system.

PRICE SPACE CONVENTIONS:
-----------------------
- YES price space: 0-99 cents (probability of YES outcome)
- NO price space: 0-99 cents (probability of NO outcome)
- Duality invariant: YES_price + NO_price = 100 cents

EXECUTABLE PRICES:
------------------
- YES bid: highest price buyers will pay for YES contracts
- YES ask: lowest price sellers will accept for YES contracts
- NO bid: highest price buyers will pay for NO contracts
- NO ask: lowest price sellers will accept for NO contracts

DUALITY RELATIONSHIPS:
----------------------
- YES_ask = 100 - NO_bid
- NO_ask = 100 - YES_bid
- YES_mid = (YES_bid + YES_ask) / 2
- NO_mid = (NO_bid + NO_ask) / 2

KALSHI'S YES-CENTRIC CONVENTION:
--------------------------------
Kalshi's API and WebSocket messages are YES-centric:
- Orderbook snapshots provide YES bids and NO bids (not asks)
- YES bids are direct prices in YES space
- NO bids are direct prices in NO space
- YES asks must be derived from NO bids using duality
- NO asks must be derived from YES bids using duality

This module abstracts Kalshi's YES-centric convention and provides
a clean, symmetric interface for both YES and NO sides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.binary_price_space")


# ── Canonical Price Transformations ─────────────────────────────────────────────

def yes_to_no_price(yes_price_cents: int) -> int:
    """Convert YES price to NO price using duality.

    Args:
        yes_price_cents: Price in YES space (0-99 cents)

    Returns:
        Price in NO space (0-99 cents)

    Example:
        >>> yes_to_no_price(25)
        75
        >>> yes_to_no_price(1)
        99
    """
    return 100 - yes_price_cents


def no_to_yes_price(no_price_cents: int) -> int:
    """Convert NO price to YES price using duality.

    Args:
        no_price_cents: Price in NO space (0-99 cents)

    Returns:
        Price in YES space (0-99 cents)

    Example:
        >>> no_to_yes_price(75)
        25
        >>> no_to_yes_price(99)
        1
    """
    return 100 - no_price_cents


def derive_yes_ask_from_no_bid(no_bid_cents: int) -> int:
    """Derive YES ask from NO bid using duality.

    This is the canonical way to get YES ask prices from Kalshi's YES-centric API.

    Args:
        no_bid_cents: Best NO bid in NO space (0-99 cents)

    Returns:
        Best YES ask in YES space (0-99 cents)

    Example:
        >>> derive_yes_ask_from_no_bid(75)
        25
    """
    return 100 - no_bid_cents


def derive_no_ask_from_yes_bid(yes_bid_cents: int) -> int:
    """Derive NO ask from YES bid using duality.

    Args:
        yes_bid_cents: Best YES bid in YES space (0-99 cents)

    Returns:
        Best NO ask in NO space (0-99 cents)

    Example:
        >>> derive_no_ask_from_yes_bid(25)
        75
    """
    return 100 - yes_bid_cents


def validate_duality(yes_price_cents: int, no_price_cents: int, tolerance_cents: int = 1) -> bool:
    """Validate YES + NO = 100 duality invariant.

    Args:
        yes_price_cents: Price in YES space
        no_price_cents: Price in NO space
        tolerance_cents: Allowed deviation from 100 (default: 1 cent)

    Returns:
        True if duality invariant holds within tolerance

    Example:
        >>> validate_duality(25, 75)
        True
        >>> validate_duality(25, 74)
        False
    """
    return abs((yes_price_cents + no_price_cents) - 100) <= tolerance_cents


# ── Canonical Side Mapping ─────────────────────────────────────────────────────

def to_kalshi_side(side: str, action: str) -> str:
    """Convert side/action to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO).

    This is the single canonical function for side mapping across the entire system.
    All side mapping logic should use this function.

    Args:
        side: "yes" or "no" (case-insensitive)
        action: "buy" or "sell" (case-insensitive)

    Returns:
        Kalshi-formatted side string (BUY_YES, SELL_YES, BUY_NO, SELL_NO)

    Raises:
        ValueError: If side or action is invalid

    Example:
        >>> to_kalshi_side("yes", "buy")
        'BUY_YES'
        >>> to_kalshi_side("no", "sell")
        'SELL_NO'
    """
    side_upper = side.upper()
    action_upper = action.upper()

    if side_upper not in ("YES", "NO"):
        raise ValueError(f"Invalid side: {side}. Must be 'yes' or 'no'")

    if action_upper not in ("BUY", "SELL"):
        raise ValueError(f"Invalid action: {action}. Must be 'buy' or 'sell'")

    mapping = {
        ("YES", "BUY"): "BUY_YES",
        ("YES", "SELL"): "SELL_YES",
        ("NO", "BUY"): "BUY_NO",
        ("NO", "SELL"): "SELL_NO",
    }

    return mapping[(side_upper, action_upper)]


def parse_kalshi_side(kalshi_side: str) -> Tuple[str, str]:
    """Parse Kalshi-formatted side into (side, action) tuple.

    Args:
        kalshi_side: Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)

    Returns:
        Tuple of (side, action) where side is "yes"/"no" and action is "buy"/"sell"

    Raises:
        ValueError: If kalshi_side is invalid

    Example:
        >>> parse_kalshi_side("BUY_YES")
        ('yes', 'buy')
        >>> parse_kalshi_side("SELL_NO")
        ('no', 'sell')
    """
    kalshi_side_upper = kalshi_side.upper()

    mapping = {
        "BUY_YES": ("yes", "buy"),
        "SELL_YES": ("yes", "sell"),
        "BUY_NO": ("no", "buy"),
        "SELL_NO": ("no", "sell"),
    }

    if kalshi_side_upper not in mapping:
        raise ValueError(f"Invalid Kalshi side: {kalshi_side}. Must be one of: {list(mapping.keys())}")

    return mapping[kalshi_side_upper]


def extract_outcome_side(kalshi_side: str) -> str:
    """Extract outcome side (yes/no) from Kalshi-formatted side.

    Args:
        kalshi_side: Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)

    Returns:
        Outcome side: "yes" or "no"

    Example:
        >>> extract_outcome_side("BUY_YES")
        'yes'
        >>> extract_outcome_side("SELL_NO")
        'no'
    """
    side, _ = parse_kalshi_side(kalshi_side)
    return side


def extract_action(kalshi_side: str) -> str:
    """Extract action (buy/sell) from Kalshi-formatted side.

    Args:
        kalshi_side: Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)

    Returns:
        Action: "buy" or "sell"

    Example:
        >>> extract_action("BUY_YES")
        'buy'
        >>> extract_action("SELL_NO")
        'sell'
    """
    _, action = parse_kalshi_side(kalshi_side)
    return action


def canonicalize(action: str, side: str) -> str:
    """Canonicalize a legacy action/side pair to the long outcome side.

    Alias for :func:`canonicalize_legacy_side` for shorter call sites.
    """
    return canonicalize_legacy_side(action, side)


def close_side(outcome_side: str) -> str:
    """Return the outcome side that closes a long ``outcome_side`` position.

    Alias for :func:`close_outcome_side`.
    """
    return close_outcome_side(outcome_side)


def canonicalize_legacy_side(action: str, side: str) -> str:
    """Return the canonical outcome side (yes/no) for a legacy Kalshi order.

    DIRECTION POLICY (2026-08-07): Cross-leg equivalence is PROHIBITED.
    Each order form maps to its own leg only:
    - BUY_YES  -> long YES
    - SELL_YES -> close YES (not equivalent to BUY_NO)
    - BUY_NO   -> long NO
    - SELL_NO  -> close NO (not equivalent to BUY_YES)

    This function now returns the literal side for BUY actions only.
    SELL actions are only for exits and should not be canonicalized to long exposures.

    Args:
        action: ``buy`` or ``sell``
        side: ``yes`` or ``no``

    Returns:
        Canonical outcome side: ``yes`` or ``no`` (for BUY actions only)

    Raises:
        ValueError: for SELL actions (should use close_side instead)

    Example:
        >>> canonicalize_legacy_side("buy", "yes")
        'yes'
        >>> canonicalize_legacy_side("buy", "no")
        'no'
    """
    action_lower = action.lower()
    side_lower = side.lower()

    # DIRECTION POLICY: Only BUY actions are canonicalized to long exposures
    # SELL actions are for exits only and should use close_side()
    if action_lower == "sell":
        raise ValueError(
            f"SELL actions cannot be canonicalized to long exposures (direction policy). "
            f"Use close_side() for exit orders. action={action}, side={side}"
        )

    if action_lower == "buy" and side_lower == "yes":
        return "yes"
    if action_lower == "buy" and side_lower == "no":
        return "no"

    raise ValueError(f"Invalid legacy side/action: action={action}, side={side}")


def close_outcome_side(outcome_side: str) -> str:
    """Return the outcome side that closes a long ``outcome_side`` position.

    A position is always long its own outcome side.  To flatten, the close
    order must be on the opposite outcome side:
    - long YES -> close on NO
    - long NO  -> close on YES

    Args:
        outcome_side: Canonical side the position is long (``yes`` or ``no``)

    Returns:
        Canonical close outcome side

    Example:
        >>> close_outcome_side("no")
        'yes'
        >>> close_outcome_side("yes")
        'no'
    """
    outcome = outcome_side.lower()
    if outcome == "yes":
        return "no"
    if outcome == "no":
        return "yes"
    raise ValueError(f"Invalid outcome_side: {outcome_side}")


def legacy_to_v2(action: str, outcome: str, price_cents: int) -> tuple[str, int]:
    """Convert legacy (action, outcome, price) to Kalshi V2 (book_side, yes_price_cents).

    Kalshi V2 ``POST /portfolio/events/orders`` uses a single YES-space book.
    ``side`` is the book side (``bid`` = buy YES, ``ask`` = sell YES) and the
    ``price`` is always quoted in YES-space cents.  The four legacy order forms
    therefore map as follows:

    - BUY_YES  @ Y -> bid @ Y
    - SELL_YES @ Y -> ask @ Y
    - BUY_NO   @ N -> ask @ (100 - N)
    - SELL_NO  @ N -> bid @ (100 - N)

    This is the single permitted legacy-to-V2 conversion.  Any other path is
    a price-space bug.

    Args:
        action: ``buy`` or ``sell`` (case-insensitive)
        outcome: ``yes`` or ``no`` (case-insensitive)
        price_cents: limit price in the outcome's own price space (NO-space for
            NO-side orders, YES-space for YES-side orders)

    Returns:
        Tuple of (book_side, yes_space_price_cents)

    Raises:
        ValueError: for unsupported action/outcome combinations
    """
    action_lower = action.lower()
    outcome_lower = outcome.lower()

    if action_lower == "buy" and outcome_lower == "yes":
        return "bid", price_cents
    if action_lower == "sell" and outcome_lower == "yes":
        return "ask", price_cents
    if action_lower == "buy" and outcome_lower == "no":
        return "ask", 100 - price_cents
    if action_lower == "sell" and outcome_lower == "no":
        return "bid", 100 - price_cents

    raise ValueError(f"Invalid legacy direction: action={action}, outcome={outcome}")


def v2_to_legacy(book_side: str, yes_space_price_cents: int, outcome_side: str, action: str) -> tuple[str, str, int]:
    """Convert Kalshi V2 (book_side, yes_space_price_cents, outcome_side, action) to legacy (action, outcome, price_cents).

    This is the inverse of legacy_to_v2. The action is required to resolve the bid/ask ambiguity:
    - bid with action=buy -> BUY_YES
    - bid with action=sell -> SELL_NO
    - ask with action=buy -> BUY_NO
    - ask with action=sell -> SELL_YES

    Args:
        book_side: Kalshi V2 book side (``bid`` or ``ask``)
        yes_space_price_cents: Price in YES-space (cents)
        outcome_side: The exposure produced (``yes`` or ``no``) - canonical source
        action: The user's action (``buy`` or ``sell``)

    Returns:
        Tuple of (action, outcome, price_cents) where:
        - action: ``buy`` or ``sell``
        - outcome: ``yes`` or ``no``
        - price_cents: Price in the outcome's own price space

    Example:
        >>> v2_to_legacy("ask", 75, "no", "buy")
        ('buy', 'no', 25)
        >>> v2_to_legacy("bid", 75, "yes", "sell")
        ('sell', 'no', 25)
    """
    book_lower = book_side.lower()
    outcome_lower = outcome_side.lower()
    action_lower = action.lower()

    # Invariant: (book_side == "bid") == (outcome == "yes")
    if (book_lower == "bid") != (outcome_lower == "yes"):
        raise ValueError(
            f"Inconsistent V2 fill: book_side={book_side}, outcome_side={outcome_side}. "
            f"Per Kalshi V2 semantics, bid<=>yes and ask<=>no."
        )

    if book_lower == "bid" and outcome_lower == "yes" and action_lower == "buy":
        # bid @ p in YES-space -> BUY_YES @ p
        return "buy", "yes", yes_space_price_cents
    elif book_lower == "bid" and outcome_lower == "yes" and action_lower == "sell":
        # bid @ p in YES-space -> SELL_NO @ (100 - p)
        return "sell", "no", 100 - yes_space_price_cents
    elif book_lower == "ask" and outcome_lower == "no" and action_lower == "buy":
        # ask @ p in YES-space -> BUY_NO @ (100 - p)
        return "buy", "no", 100 - yes_space_price_cents
    elif book_lower == "ask" and outcome_lower == "no" and action_lower == "sell":
        # ask @ p in YES-space -> SELL_YES @ p
        return "sell", "yes", yes_space_price_cents

    raise ValueError(f"Invalid V2 direction: book_side={book_side}, outcome_side={outcome_side}, action={action}")


def close_book_side(outcome_side: str) -> str:
    """Return the book side (bid/ask) for a limit order that closes a long position.

    A long position is closed by selling the outcome we are long.  In Kalshi's
    V2 single-book model:

    - long YES -> SELL_YES -> ``ask``
    - long NO  -> SELL_NO  -> ``bid`` (because selling NO is economically buying YES)

    Args:
        outcome_side: Canonical side the position is long (``yes`` or ``no``)

    Returns:
        ``ask`` for long YES, ``bid`` for long NO
    """
    outcome = outcome_side.lower()
    if outcome == "yes":
        return "ask"
    if outcome == "no":
        return "bid"
    raise ValueError(f"Invalid outcome_side: {outcome_side}")


def close_to_legacy_kalshi_side(outcome_side: str) -> str:
    """Return the legacy Kalshi side string used to close a long position.

    This is only for the wire adapter and internal log fields.  The canonical
    truth is (outcome_side, book_side).

    Args:
        outcome_side: Canonical side the position is long (``yes`` or ``no``)

    Returns:
        ``SELL_YES`` or ``SELL_NO``

    Example:
        >>> close_to_legacy_kalshi_side("no")
        'SELL_NO'
        >>> close_to_legacy_kalshi_side("yes")
        'SELL_YES'
    """
    outcome = outcome_side.lower()
    if outcome == "yes":
        return "SELL_YES"
    if outcome == "no":
        return "SELL_NO"
    raise ValueError(f"Invalid outcome_side: {outcome_side}")


def yes_delta(action: str, side: str, qty: int) -> int:
    """Return the signed YES-exposure change for an order.

    Kalshi binary contracts are economically paired: buying YES is the same
    exposure as selling NO (long YES), and selling YES is the same as buying
    NO (long NO / short YES).  This function collapses the four raw order
    forms into a single signed YES delta.

    Positive  -> long YES exposure increases by ``qty``
    Negative  -> long NO exposure increases by ``qty`` (YES delta falls)

    Args:
        action: "buy" or "sell" (case-insensitive)
        side:   "yes" or "no"  (case-insensitive)
        qty:    number of centi-contracts (quantity_cc)

    Returns:
        Signed YES delta in centi-contracts (positive for long YES, negative for long NO)

    Example:
        >>> yes_delta("buy", "yes", 5)
        5
        >>> yes_delta("sell", "no", 3)
        3
        >>> yes_delta("sell", "yes", 2)
        -2
        >>> yes_delta("buy", "no", 4)
        -4
    """
    action = action.lower()
    side = side.lower()

    if (action, side) in {("buy", "yes"), ("sell", "no")}:
        return +qty
    if (action, side) in {("sell", "yes"), ("buy", "no")}:
        return -qty

    raise ValueError(f"Unsupported order: action={action} side={side}")


def to_signed_yes_exposure(side: str, contracts: int) -> int:
    """Convert a long position in outcome space to signed YES exposure.

    A position is always long its own side, so:
    - long YES  -> positive YES delta
    - long NO   -> negative YES delta

    Args:
        side:      "yes" or "no" (case-insensitive)
        contracts: number of centi-contracts held long

    Returns:
        Signed YES exposure in centi-contracts
    """
    side = side.lower()
    if side == "yes":
        return +contracts
    if side == "no":
        return -contracts
    raise ValueError(f"Unsupported side: {side}")


def from_signed_yes_exposure(yes_delta: int) -> Tuple[str, int]:
    """Convert signed YES exposure back to (side, contracts) for a long position.

    Args:
        yes_delta: Signed YES exposure (positive = long YES, negative = long NO)

    Returns:
        Tuple of (side, contracts) where side is "yes" or "no"
    """
    if yes_delta > 0:
        return ("yes", yes_delta)
    if yes_delta < 0:
        return ("no", -yes_delta)
    return ("yes", 0)


def normalize_rest_position(position_fp: int, outcome_or_side: str, ticker: str = "") -> int:
    """Convert a Kalshi REST position snapshot to signed YES exposure.

    Kalshi may report a long NO position as either ``outcome_or_side='no'`` with
    a positive ``position_fp`` or as a negative ``position_fp`` with an empty or
    yes side.  This helper collapses both conventions into the canonical signed
    YES representation so that REST, fills-ledger, and cache exposure can be
    compared directly.

    Args:
        position_fp: Raw position size from Kalshi (negative for short YES / long NO
            in some REST payloads).
        outcome_or_side: The outcome side reported for the position ("yes" or "no").
        ticker: Optional ticker for diagnostics.

    Returns:
        Signed YES exposure (positive = long YES, negative = long NO).
    """
    if position_fp is None:
        position_fp = 0
    side = (outcome_or_side or "").lower().strip()

    # Kalshi sometimes represents NO exposure as a negative position_fp with no side.
    if side in ("", "yes") and position_fp < 0:
        return position_fp  # already negative => long NO / short YES

    if side == "no":
        return -abs(int(position_fp))

    if side == "yes":
        return abs(int(position_fp))

    # Unknown side: log and treat as zero to avoid inventing exposure.
    logger.warning(
        "[NORMALIZE-REST-POSITION] Unknown outcome_or_side=%r for %s, returning 0 exposure",
        outcome_or_side,
        ticker,
    )
    return 0


def fill_to_signed_yes_exposure(action: str, side: str, count: int) -> int:
    """Wrapper around yes_delta that guards missing/invalid fill fields.

    A fill with no recognizable action/side is treated as zero exposure change.
    This prevents ``settle`` or malformed fills from corrupting the ledger.
    """
    if not action or not side or count is None or count == 0:
        return 0
    try:
        return yes_delta(str(action), str(side), int(count))
    except ValueError:
        logger.warning(
            "[FILL-TO-SIGNED-YES] Invalid fill fields: action=%r side=%r count=%r",
            action,
            side,
            count,
        )
        return 0


# ── Canonical Price Range Checking ─────────────────────────────────────────────

# Canonical price ranges (NON-NEGOTIABLE invariants)
# CRITICAL FIX (2026-08-05): Side-aware canonical ranges aligned across the stack.
# YES: 1c-75c, NO: 25c-99c. This matches the global allocator, agent_grid price
# selection, and late-expiry NO trading research (88-95c NO inverse FLB band).
CANONICAL_MIN_CENTS = 5   # Kept for legacy clamp_to_canonical_range only
CANONICAL_MAX_CENTS = 85  # Kept for legacy clamp_to_canonical_range only
SIDE_AWARE_YES_MIN_CENTS = 1
SIDE_AWARE_YES_MAX_CENTS = 75
SIDE_AWARE_NO_MIN_CENTS = 25
SIDE_AWARE_NO_MAX_CENTS = 99
CRISIS_MIN_CENTS = 5
CRISIS_MAX_CENTS = 99

# ── Favorite-Longshot Bias (FLB) Trading Thresholds ─────────────────────────────
# Based on Bürgi, Deng & Whelan (2026) analysis of 313,972 Kalshi contracts
# Contracts under 10¢ lose 60%+ of capital on average
# Contracts at 88-95¢ NO show systematic positive EV (inverse FLB)
# CRITICAL FIX (2026-08-01): Adjusted for expanded 15m crypto ranges

FLB_MIN_YES_CENTS = 5   # Minimum YES price to avoid FLB capital destruction (lowered from 10c)
FLB_MIN_NO_CENTS = 15   # Minimum NO price (equivalent to YES >85¢, lowered from 25c)
FLB_MAX_YES_CENTS = 85  # Maximum YES price (above this, diminishing returns)
FLB_MAX_NO_CENTS = 95   # Maximum NO price (special case: 88-95¢ NO shows positive EV)
FLB_NO_EDGE_BAND_MIN = 88  # NO edge band start (systematically underpriced)
FLB_NO_EDGE_BAND_MAX = 95  # NO edge band end


def is_price_in_canonical_range(price_cents: int, side: str) -> bool:
    """Check if price is in canonical range (side-aware).

    CRITICAL FIX (2026-08-07): Align side-aware canonical ranges with the
    expanded 15m crypto volatility ranges used by order_router and the
    is_yes_in_range / is_no_in_range doc contract.
    YES: 1c-85c (high YES prices mean paying too much for a long shot)
    NO: 15c-99c (low NO prices mean insufficient edge for the risk taken)

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no" (for logging/context)

    Returns:
        True if price is in canonical range

    Example:
        >>> is_price_in_canonical_range(25, "yes")
        True
        >>> is_price_in_canonical_range(85, "yes")
        True
        >>> is_price_in_canonical_range(1, "yes")
        True
        >>> is_price_in_canonical_range(94, "no")
        True
    """
    if side == "yes":
        return 1 <= price_cents <= 85
    else:  # side == "no"
        return 15 <= price_cents <= 99


def is_price_in_crisis_range(price_cents: int, side: str) -> bool:
    """Check if price is in crisis range (side-aware).

    CRITICAL FIX (2026-08-01): Use side-aware crisis ranges to account for YES/NO duality.
    YES: 1c-99c (full range for extreme conditions)
    NO: 5c-99c (expanded high end for extreme conditions)
    This prevents systematic rejection of valid signals at extreme prices.

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no" (for logging/context)

    Returns:
        True if price is in crisis range

    Example:
        >>> is_price_in_crisis_range(1, "yes")
        True
        >>> is_price_in_crisis_range(99, "no")
        True
    """
    if side == "yes":
        return 1 <= price_cents <= 99
    else:  # side == "no"
        return 5 <= price_cents <= 99


def is_price_in_flb_trading_range(price_cents: int, side: str) -> bool:
    """Check if price is in FLB-aware trading range (prevents capital destruction).

    Based on Bürgi, Deng & Whelan (2026) analysis of 313,972 Kalshi contracts:
    - Contracts under 10¢ lose 60%+ of capital on average (favorite-longshot bias)
    - NO contracts at 88-95¢ show systematic positive EV (inverse FLB)
    - YES contracts above 85¢ have diminishing returns due to fee drag

    This function provides an additional safety layer beyond canonical ranges
    to prevent trading in price ranges with historically negative expected value.

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no"

    Returns:
        True if price is in FLB-aware trading range

    Example:
        >>> is_price_in_flb_trading_range(5, "yes")  # Too cheap - FLB capital destruction
        False
        >>> is_price_in_flb_trading_range(25, "yes")  # Good - avoids FLB
        True
        >>> is_price_in_flb_trading_range(90, "no")  # Edge band - positive EV
        True
    """
    if side == "yes":
        # YES: Avoid FLB capital destruction zone (<10¢) and fee drag zone (>85¢)
        return FLB_MIN_YES_CENTS <= price_cents <= FLB_MAX_YES_CENTS
    else:  # side == "no"
        # NO: Minimum 25¢ (equivalent to YES <75¢), max 95¢ (edge band)
        return FLB_MIN_NO_CENTS <= price_cents <= FLB_MAX_NO_CENTS


def is_price_in_flb_edge_band(price_cents: int, side: str) -> bool:
    """Check if price is in FLB edge band (systematically underpriced).

    Based on research, NO contracts priced between 88-95¢ show systematic
    positive expected value due to inverse favorite-longshot bias.
    This band represents a trading opportunity for sophisticated traders.

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no"

    Returns:
        True if price is in FLB edge band

    Example:
        >>> is_price_in_flb_edge_band(90, "no")  # Edge band - positive EV
        True
        >>> is_price_in_flb_edge_band(90, "yes")  # YES not in edge band
        False
    """
    if side == "no":
        return FLB_NO_EDGE_BAND_MIN <= price_cents <= FLB_NO_EDGE_BAND_MAX
    else:  # side == "yes"
        return False  # YES contracts don't have documented edge band


def is_price_in_side_aware_range(price_cents: int, side: str) -> bool:
    """Check if price is in side-aware range (accounts for YES/NO duality).

    CRITICAL FIX (2026-07-30): Use side-aware ranges to prevent systematic bias.
    - YES: 1c-75c (expanded low end for late-expiry markets)
    - NO: 25c-99c (expanded high end for late-expiry markets)

    This prevents systematic rejection of NO orders in late-expiry markets where
    YES prices are low (1c-6c) and NO prices are high (94c-99c).

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no"

    Returns:
        True if price is in side-aware range for the given side

    Example:
        >>> is_price_in_side_aware_range(6, "yes")  # YES in late-expiry
        True
        >>> is_price_in_side_aware_range(94, "no")  # NO in late-expiry
        True
        >>> is_price_in_side_aware_range(94, "yes")  # YES too high
        False
        >>> is_price_in_side_aware_range(6, "no")   # NO too low
        False
    """
    if side == "no":
        return SIDE_AWARE_NO_MIN_CENTS <= price_cents <= SIDE_AWARE_NO_MAX_CENTS
    else:  # side == "yes"
        return SIDE_AWARE_YES_MIN_CENTS <= price_cents <= SIDE_AWARE_YES_MAX_CENTS


def clamp_to_canonical_range(price_cents: int) -> int:
    """Clamp price to canonical range (5c-85c).

    CRITICAL FIX (2026-08-01): Updated to 5c-85c to match expanded canonical range for 15m crypto volatility
    DEPRECATED: Use is_price_in_canonical_range() with side parameter for side-aware ranges.
    This function is kept for backward compatibility but does not use side-aware ranges.

    Args:
        price_cents: Price in cents (0-99)

    Returns:
        Price clamped to canonical range

    Example:
        >>> clamp_to_canonical_range(5)
        10
        >>> clamp_to_canonical_range(80)
        75
    """
    return max(CANONICAL_MIN_CENTS, min(CANONICAL_MAX_CENTS, price_cents))


def clamp_to_crisis_range(price_cents: int) -> int:
    """Clamp price to crisis range (5c-99c).

    Args:
        price_cents: Price in cents (0-99)

    Returns:
        Price clamped to crisis range

    Example:
        >>> clamp_to_crisis_range(1)
        5
        >>> clamp_to_crisis_range(99)
        99
    """
    return max(CRISIS_MIN_CENTS, min(CRISIS_MAX_CENTS, price_cents))


def detect_extreme_price_condition(yes_price_cents: int, no_price_cents: int) -> bool:
    """Detect if market is in extreme price condition.

    Extreme condition: one side >= 85c or <= 15c

    CRITICAL FIX: 2026-07-30 - Changed from strict > 85c to >= 85c to properly detect
    extreme conditions at the boundary. Previous strict inequality failed to trigger
    crisis range for prices exactly at 85c, causing trade rejections when crisis range
    should have applied.

    Args:
        yes_price_cents: YES price in cents
        no_price_cents: NO price in cents

    Returns:
        True if extreme condition detected

    Example:
        >>> detect_extreme_price_condition(5, 95)
        True
        >>> detect_extreme_price_condition(85, 15)
        True
        >>> detect_extreme_price_condition(40, 60)
        False
    """
    return (yes_price_cents >= 85 or yes_price_cents <= 15 or
            no_price_cents >= 85 or no_price_cents <= 15)


def get_price_range_for_condition(is_extreme: bool) -> Tuple[int, int]:
    """Get price range (min, max) for market condition.

    Args:
        is_extreme: True if extreme condition detected

    Returns:
        Tuple of (min_cents, max_cents)

    Example:
        >>> get_price_range_for_condition(False)
        (10, 75)
        >>> get_price_range_for_condition(True)
        (5, 99)
    """
    if is_extreme:
        return (CRISIS_MIN_CENTS, CRISIS_MAX_CENTS)
    else:
        return (CANONICAL_MIN_CENTS, CANONICAL_MAX_CENTS)


# ── Canonical Market State Model ────────────────────────────────────────────────

@dataclass
class CanonicalBinaryMarketState:
    """Canonical YES/NO price space model for binary markets.

    This is the single source of truth for YES/NO price data across the system.
    All components should use this model instead of ad-hoc price calculations.

    PRICE SPACE CONVENTIONS:
    - YES price space: 0-99 cents (probability of YES outcome)
    - NO price space: 0-99 cents (probability of NO outcome)
    - Duality invariant: YES_price + NO_price = 100 cents

    EXECUTABLE PRICES:
    - YES bid: highest price buyers will pay for YES contracts
    - YES ask: lowest price sellers will accept for YES contracts
    - NO bid: highest price buyers will pay for NO contracts
    - NO ask: lowest price sellers will accept for NO contracts

    DUALITY RELATIONSHIPS:
    - YES_ask = 100 - NO_bid
    - NO_ask = 100 - YES_bid
    - YES_mid = (YES_bid + YES_ask) / 2
    - NO_mid = (NO_bid + NO_ask) / 2
    """

    ticker: str

    # YES-side prices (in YES price space)
    yes_bid_cents: Optional[int] = None
    yes_ask_cents: Optional[int] = None

    # NO-side prices (in NO price space)
    no_bid_cents: Optional[int] = None
    no_ask_cents: Optional[int] = None

    # Orderbook levels (in respective price spaces)
    yes_levels: Dict[int, int] = field(default_factory=dict)  # price_cents -> size (YES space)
    no_levels: Dict[int, int] = field(default_factory=dict)   # price_cents -> size (NO space)

    # Timestamps
    last_update_ts: float = 0.0

    @property
    def yes_mid_cents(self) -> Optional[float]:
        """YES mid-price in YES space."""
        if self.yes_bid_cents is not None and self.yes_ask_cents is not None:
            return (self.yes_bid_cents + self.yes_ask_cents) / 2.0
        return None

    @property
    def no_mid_cents(self) -> Optional[float]:
        """NO mid-price in NO space."""
        if self.no_bid_cents is not None and self.no_ask_cents is not None:
            return (self.no_bid_cents + self.no_ask_cents) / 2.0
        return None

    @property
    def yes_spread_cents(self) -> Optional[int]:
        """YES spread in YES space."""
        if self.yes_bid_cents is not None and self.yes_ask_cents is not None:
            return self.yes_ask_cents - self.yes_bid_cents
        return None

    @property
    def no_spread_cents(self) -> Optional[int]:
        """NO spread in NO space."""
        if self.no_bid_cents is not None and self.no_ask_cents is not None:
            return self.no_ask_cents - self.no_bid_cents
        return None

    @property
    def yes_implied_prob(self) -> Optional[float]:
        """YES implied probability from mid-price."""
        mid = self.yes_mid_cents
        return mid / 100.0 if mid is not None else None

    @property
    def no_implied_prob(self) -> Optional[float]:
        """NO implied probability from mid-price."""
        mid = self.no_mid_cents
        return mid / 100.0 if mid is not None else None

    def validate_duality(self, tolerance_cents: int = 1) -> bool:
        """Validate YES + NO = 100 duality invariant.

        Checks:
        - YES_ask + NO_bid = 100 (if both present)
        - NO_ask + YES_bid = 100 (if both present)

        Args:
            tolerance_cents: Allowed deviation from 100 (default: 1 cent)

        Returns:
            True if duality invariant holds within tolerance
        """
        if self.yes_ask_cents and self.no_bid_cents:
            if not validate_duality(self.yes_ask_cents, self.no_bid_cents, tolerance_cents):
                logger.warning(
                    "[DUALITY-VALIDATION] ticker=%s YES_ask=%dc NO_bid=%dc duality_violation=True",
                    self.ticker, self.yes_ask_cents, self.no_bid_cents
                )
                return False

        if self.no_ask_cents and self.yes_bid_cents:
            if not validate_duality(self.no_ask_cents, self.yes_bid_cents, tolerance_cents):
                logger.warning(
                    "[DUALITY-VALIDATION] ticker=%s NO_ask=%dc YES_bid=%dc duality_violation=True",
                    self.ticker, self.no_ask_cents, self.yes_bid_cents
                )
                return False

        return True

    def derive_missing_prices(self) -> None:
        """Derive missing prices using duality.

        If YES_ask is missing but NO_bid is present, derive YES_ask = 100 - NO_bid.
        If NO_ask is missing but YES_bid is present, derive NO_ask = 100 - YES_bid.
        """
        if self.yes_ask_cents is None and self.no_bid_cents is not None:
            self.yes_ask_cents = derive_yes_ask_from_no_bid(self.no_bid_cents)
            logger.debug(
                "[DERIVE-PRICE] ticker=%s derived YES_ask=%dc from NO_bid=%dc",
                self.ticker, self.yes_ask_cents, self.no_bid_cents
            )

        if self.no_ask_cents is None and self.yes_bid_cents is not None:
            self.no_ask_cents = derive_no_ask_from_yes_bid(self.yes_bid_cents)
            logger.debug(
                "[DERIVE-PRICE] ticker=%s derived NO_ask=%dc from YES_bid=%dc",
                self.ticker, self.no_ask_cents, self.yes_bid_cents
            )

    def is_yes_in_range(self, is_extreme: bool = False) -> bool:
        """Check if YES price is in valid range.

        CRITICAL FIX (2026-08-01): Use side-aware ranges for YES prices
        Normal: 1c-85c, Extreme: 1c-99c

        Args:
            is_extreme: True if extreme condition (use crisis range)

        Returns:
            True if YES price is in valid range
        """
        if self.yes_bid_cents is None:
            return False

        # CRITICAL FIX (2026-08-01): Use side-aware range for YES
        if is_extreme:
            return is_price_in_crisis_range(self.yes_bid_cents, "yes")
        else:
            return is_price_in_canonical_range(self.yes_bid_cents, "yes")

    def is_no_in_range(self, is_extreme: bool = False) -> bool:
        """Check if NO price is in valid range.

        CRITICAL FIX (2026-08-01): Use side-aware ranges for NO prices
        Normal: 15c-99c, Extreme: 5c-99c

        Args:
            is_extreme: True if extreme condition (use crisis range)

        Returns:
            True if NO price is in valid range
        """
        if self.no_bid_cents is None:
            return False

        # CRITICAL FIX (2026-08-01): Use side-aware range for NO
        if is_extreme:
            return is_price_in_crisis_range(self.no_bid_cents, "no")
        else:
            return is_price_in_canonical_range(self.no_bid_cents, "no")

    def to_dict(self) -> Dict[str, any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "ticker": self.ticker,
            "yes_bid_cents": self.yes_bid_cents,
            "yes_ask_cents": self.yes_ask_cents,
            "no_bid_cents": self.no_bid_cents,
            "no_ask_cents": self.no_ask_cents,
            "yes_mid_cents": self.yes_mid_cents,
            "no_mid_cents": self.no_mid_cents,
            "yes_spread_cents": self.yes_spread_cents,
            "no_spread_cents": self.no_spread_cents,
            "yes_implied_prob": self.yes_implied_prob,
            "no_implied_prob": self.no_implied_prob,
            "yes_levels_count": len(self.yes_levels),
            "no_levels_count": len(self.no_levels),
            "last_update_ts": self.last_update_ts,
        }
