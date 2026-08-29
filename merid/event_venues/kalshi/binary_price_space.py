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
from decimal import Decimal
from enum import StrEnum
from typing import Any, Dict, Mapping, Optional, Tuple, Union
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


class SideValidationError(ValueError):
    """A record is missing, invalid, or internally inconsistent about its outcome side."""


class PositionDataError(SideValidationError):
    """A position record has missing, invalid, or self-contradictory outcome side data."""


class Side(StrEnum):
    """Canonical binary market side (traded contract side).

    This is the single source of truth for the ``yes``/``no`` vocabulary in
    the Kalshi venue integration.  Every other representation (signal side,
    intent side, outcome side, position side) must translate through this
    table; no code path is permitted to re-derive it with ad-hoc ``if``/``==``
    logic.

    Invariant: ``Side.YES`` (the YES contract) and ``Side.NO`` (the NO
    contract) always sum to a dollar; the canonical price space conversions
    preserve this.
    """

    YES = "yes"
    NO = "no"

    def flip(self) -> "Side":
        """Return the opposite side."""
        return Side.NO if self is Side.YES else Side.YES


# Backward-compatible alias used by existing code and tests.
# ``OutcomeSide`` is the held-outcome vocabulary; it is the same canonical
# enum because the held outcome of an order is always one of ``yes``/``no``.
OutcomeSide = Side


class BookSide(StrEnum):
    """Kalshi V2 book side.

    Invariant (Kalshi V2): ``bid`` is the YES side of the book,
    ``ask`` is the NO side of the book.

    - BUY_YES  and SELL_NO  rest on the ``bid``.
    - SELL_YES and BUY_NO   rest on the ``ask``.

    This is *not* the same as "buy = bid / sell = ask".  Book side is a
    function of the **held outcome** produced by the order, not the action.
    """

    BID = "bid"  # ≡ YES
    ASK = "ask"  # ≡ NO


def _try_parse_side(value: Any) -> Optional[str]:
    """Return canonical 'yes' or 'no' if ``value`` is parseable, otherwise None.

    Interprets raw outcome side names and Kalshi order direction strings by
    their resulting long exposure: BUY_YES and SELL_NO are long YES; BUY_NO
    and SELL_YES are long NO.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in ("yes", "no"):
        return lowered
    # Kalshi-formatted order direction -> resulting long exposure.
    exposure_aliases = {
        "buy_yes": "yes",
        "sell_no": "yes",
        "buy_no": "no",
        "sell_yes": "no",
    }
    if lowered in exposure_aliases:
        return exposure_aliases[lowered]
    return None


def canonical_outcome_side(raw: Any) -> OutcomeSide:
    """Return the canonical OutcomeSide for a raw side value.

    Raises PositionDataError for missing, blank, or unknown values.  Does not
    default to YES under any circumstance.
    """
    if raw is None:
        raise PositionDataError(f"unknown outcome side: {raw!r}")
    value = str(raw).strip()
    if not value:
        raise PositionDataError(f"unknown outcome side: {raw!r}")
    lowered = value.lower()
    if lowered == "yes":
        return OutcomeSide.YES
    if lowered == "no":
        return OutcomeSide.NO
    # Allow legacy Kalshi action aliases but fail closed on anything else.
    exposure_aliases = {
        "buy_yes": OutcomeSide.YES,
        "sell_no": OutcomeSide.YES,
        "buy_no": OutcomeSide.NO,
        "sell_yes": OutcomeSide.NO,
    }
    if lowered in exposure_aliases:
        return exposure_aliases[lowered]
    raise PositionDataError(f"unknown outcome side: {raw!r}")


def _parse_signed_quantity(record: Mapping[str, Any]) -> Optional[Decimal]:
    """Return a signed quantity from position_fp or signed_size, or None."""
    for key in ("position_fp", "signed_size"):
        raw = record.get(key)
        if raw is None:
            continue
        try:
            return Decimal(str(raw))
        except Exception:
            continue
    return None


def require_canonical_outcome_side(
    record: Mapping[str, Any],
    *,
    context: str,
    fields: tuple[str, ...] = ("outcome_side", "outcome_id", "side", "kalshi_side", "book_side"),
    allow_signed_infer: bool = True,
) -> OutcomeSide:
    """Extract and validate a single canonical outcome side from ``record``.

    - All present, parseable side fields must agree.  A conflict between
      e.g. ``outcome_id=no`` and ``outcome_side=yes`` raises ``PositionDataError``.
    - YES must correspond to a non-negative signed quantity; NO to a
      non-positive signed quantity.  A contradiction raises ``PositionDataError``.
    - If no side field is present and ``allow_signed_infer`` is true, the side
      is inferred from ``position_fp`` / ``signed_size``: positive -> YES,
      negative -> NO.  Zero or missing is an error.
    - Never defaults to YES.
    """
    parsed_sides: list[tuple[str, OutcomeSide]] = []
    for field_name in fields:
        raw = record.get(field_name)
        if raw is None:
            continue
        try:
            side = canonical_outcome_side(raw)
        except PositionDataError:
            # Non-side value in this field (e.g. book_side='ask') is ignored.
            continue
        parsed_sides.append((field_name, side))

    if parsed_sides:
        first_field, selected = parsed_sides[0]
        if len({s for _, s in parsed_sides}) > 1:
            raise PositionDataError(
                f"{context}: inconsistent side fields {parsed_sides!r}"
            )
    elif allow_signed_infer:
        signed = _parse_signed_quantity(record)
        if signed is None:
            raise PositionDataError(f"{context}: missing or invalid outcome side")
        if signed > 0:
            selected = OutcomeSide.YES
        elif signed < 0:
            selected = OutcomeSide.NO
        else:
            raise PositionDataError(f"{context}: zero-size position has no side")
    else:
        raise PositionDataError(f"{context}: missing or invalid outcome side")

    # Validate sign agreement when a signed quantity is available.
    signed = _parse_signed_quantity(record)
    if signed is not None:
        if selected == OutcomeSide.YES and signed < 0:
            raise PositionDataError(
                f"{context}: side {selected.value} conflicts with negative signed quantity {signed}"
            )
        if selected == OutcomeSide.NO and signed > 0:
            raise PositionDataError(
                f"{context}: side {selected.value} conflicts with positive signed quantity {signed}"
            )

    return selected


def require_outcome_side(
    record: Mapping[str, Any],
    *,
    context: str,
    fields: tuple[str, ...] = ("outcome_side", "outcome_id", "side", "kalshi_side"),
) -> str:
    """Extract a single canonical outcome side from ``record``.

    Tries ``fields`` in order.  Missing or invalid values raise
    ``SideValidationError`` instead of defaulting to a side.

    Accepts: yes/no, BUY_YES/SELL_YES/BUY_NO/SELL_NO.
    """
    return require_canonical_outcome_side(
        record, context=context, fields=fields, allow_signed_infer=False
    ).value


def require_consistent_outcome_side(
    record: Mapping[str, Any],
    *,
    context: str,
    fields: tuple[str, ...] = ("outcome_side", "outcome_id", "side", "kalshi_side"),
) -> str:
    """Extract outcome side and require all supplied side fields to agree."""
    return require_canonical_outcome_side(
        record, context=context, fields=fields
    ).value


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


# ── Canonical Side Mapping Table (playbook 2026-08-27) ──────────────────────────
#
# The following functions are the single permitted place where Side/BookSide
# translations happen.  Every other module must call these; no hand-rolled
# ``if side == "yes"`` logic is allowed.


def outcome_from_action(action: str, side: Side) -> Side:
    """Return the held outcome side produced by a (traded_side, action) order.

    Canonical Kalshi exposure matrix:
        - buy YES  -> long YES
        - sell NO  -> long YES
        - buy NO   -> long NO
        - sell YES -> long NO

    Args:
        action: ``buy`` or ``sell``
        side: the traded contract side (``Side.YES`` or ``Side.NO``)

    Returns:
        The resulting held outcome side.

    Example:
        >>> outcome_from_action("buy", Side.YES)
        <Side.YES: 'yes'>
        >>> outcome_from_action("sell", Side.NO)
        <Side.YES: 'yes'>
        >>> outcome_from_action("buy", Side.NO)
        <Side.NO: 'no'>
    """
    action_lower = action.lower()
    if action_lower not in ("buy", "sell"):
        raise ValueError(f"Invalid action: {action!r}. Must be 'buy' or 'sell'.")
    if side not in (Side.YES, Side.NO):
        raise ValueError(f"Invalid side: {side!r}. Must be Side.YES or Side.NO.")

    # buy the traded side -> long that side; sell the traded side -> long opposite
    return side if action_lower == "buy" else side.flip()


def book_from_outcome(outcome: Side) -> BookSide:
    """Return the Kalshi V2 book side for an order that produces ``outcome``.

    Invariant: bid <-> long YES, ask <-> long NO.

    Args:
        outcome: the held outcome side produced by the order

    Returns:
        ``BookSide.BID`` for YES exposure, ``BookSide.ASK`` for NO exposure.

    Example:
        >>> book_from_outcome(Side.YES)
        <BookSide.BID: 'bid'>
        >>> book_from_outcome(Side.NO)
        <BookSide.ASK: 'ask'>
    """
    if outcome not in (Side.YES, Side.NO):
        raise ValueError(f"Invalid outcome: {outcome!r}. Must be Side.YES or Side.NO.")
    return BookSide.BID if outcome is Side.YES else BookSide.ASK


def book_price_cents(side: Side, price_cents: int) -> int:
    """Return the YES-space price for an order on ``side`` at ``price_cents``.

    Kalshi V2 only has one price space (YES cents).  A YES-side order keeps
    its price; a NO-side order is reflected across the complement.

    Args:
        side: the traded contract side
        price_cents: limit price in the side's own space (0-100 cents)

    Returns:
        The price in YES-space cents.

    Example:
        >>> book_price_cents(Side.YES, 60)
        60
        >>> book_price_cents(Side.NO, 30)
        70
    """
    if side not in (Side.YES, Side.NO):
        raise ValueError(f"Invalid side: {side!r}. Must be Side.YES or Side.NO.")
    return price_cents if side is Side.YES else 100 - price_cents


def book_price_dollars(side: Side, price_dollars: Union[Decimal, float]) -> Decimal:
    """Return the price in the side's own canonical dollar price space.

    This is the type-safe identity carrier used for YES/NO duality checks.
    It does **not** convert prices; it asserts that the supplied price is a
    valid probability in [0.0, 1.0] and returns it in the side's own space.
    """
    p = price_dollars if isinstance(price_dollars, Decimal) else Decimal(str(price_dollars))
    if side not in (Side.YES, Side.NO):
        raise ValueError(f"Invalid side: {side!r}. Must be Side.YES or Side.NO.")
    if not (Decimal("0") <= p <= Decimal("1")):
        raise ValueError(f"Price {p} out of range [0, 1]")
    return p


# Convenience name matching the playbook.
book_price = book_price_dollars


def to_v2_order(side: Side, action: str, price_cents: int) -> Tuple[BookSide, int]:
    """Convert a (traded_side, action, price_cents) order to Kalshi V2.

    This is the canonical order-encoding path.  It collapses the four legacy
    order forms into (book_side, yes_space_price_cents).

    Returns:
        ``(book_side, yes_space_price_cents)``

    Example:
        >>> to_v2_order(Side.NO, "buy", 30)
        (<BookSide.ASK: 'ask'>, 70)
        >>> to_v2_order(Side.YES, "sell", 55)
        (<BookSide.ASK: 'ask'>, 55)
    """
    book = book_from_outcome(outcome_from_action(action, side))
    yes_price = book_price_cents(side, price_cents)
    return book, yes_price


class SideReconciliationError(SideValidationError):
    """A fill or position from the venue disagrees with the internal side."""


def reconcile_venue_side(
    internal_side: Side,
    venue_outcome_side: Side,
    fill_id: str,
    ticker: str,
) -> bool:
    """Fail loudly if a venue-reported side disagrees with the internal side.

    This is the reconciliation guard from the 2026-08-27 playbook.  A mismatch
    is evidence of a side-inversion bug and must trigger a halt for the ticker
    (``reconciliation_halted``) rather than be silently absorbed.

    Args:
        internal_side: the side the system expected/intended for this fill
        venue_outcome_side: the side Kalshi reported in the fill/position
        fill_id: immutable fill id for the audit trail
        ticker: market ticker for routing halt targeting

    Returns:
        True if the sides agree.

    Raises:
        SideReconciliationError: if the sides disagree.
    """
    if internal_side != venue_outcome_side:
        raise SideReconciliationError(
            f"Side reconciliation failed: internal={internal_side.value} "
            f"venue={venue_outcome_side.value} fill={fill_id} ticker={ticker}"
        )
    return True


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
        return +int(qty)
    if (action, side) in {("sell", "yes"), ("buy", "no")}:
        return -int(qty)

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
        return +int(contracts)
    if side == "no":
        return -int(contracts)
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

    The canonical rule is:

        - long YES  -> non-negative signed exposure
        - long NO   -> non-positive signed exposure

    When ``outcome_or_side`` is missing, the sign of ``position_fp`` is trusted:
    positive -> long YES, negative -> long NO.  When ``outcome_or_side`` is
    present, it is the source of truth and a contradictory ``position_fp`` sign
    raises ``PositionDataError`` instead of silently choosing one field.

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
    raw_side = (outcome_or_side or "").lower().strip()

    if not raw_side:
        # No textual side: infer purely from the signed quantity.
        if position_fp == 0:
            return 0
        return int(position_fp)

    canonical = canonical_outcome_side(raw_side)
    if position_fp == 0:
        return 0

    if canonical == OutcomeSide.NO:
        return -abs(int(position_fp))

    # canonical == YES; the signed quantity must not be negative.
    if int(position_fp) < 0:
        raise PositionDataError(
            f"[NORMALIZE-REST-POSITION] {ticker}: side={canonical.value} conflicts "
            f"with negative position_fp={position_fp}"
        )
    return abs(int(position_fp))


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


def held_outcome_from_legacy(side: str, action: str) -> str:
    """Return the long outcome side from a legacy Kalshi (action, side) pair.

    The canonical Kalshi matrix is:
        BUY_YES  -> long YES
        SELL_NO  -> long YES
        BUY_NO   -> long NO
        SELL_YES -> long NO

    This is exactly the same mapping used by :func:`yes_delta`, but it returns
    the held outcome side instead of the signed YES exposure.

    Args:
        side: "yes" or "no" (the traded contract side)
        action: "buy" or "sell"

    Returns:
        The held outcome side ("yes" or "no")

    Raises:
        ValueError: for unsupported side/action combinations
    """
    side_lower = (side or "").lower()
    action_lower = (action or "").lower()

    if (action_lower, side_lower) in (("buy", "yes"), ("sell", "no")):
        return "yes"
    if (action_lower, side_lower) in (("buy", "no"), ("sell", "yes")):
        return "no"

    raise ValueError(f"Unsupported legacy side/action: side={side}, action={action}")


def traded_side_from_held(held_side: str, action: str) -> str:
    """Return the raw traded contract side given a held outcome and action.

    Inverse of :func:`held_outcome_from_legacy`:
        - BUY held  -> trade the held side
        - SELL held -> trade the opposite side (which makes you long the held)

    Args:
        held_side: "yes" or "no" (the long outcome side)
        action: "buy" or "sell"

    Returns:
        The traded contract side ("yes" or "no")

    Raises:
        ValueError: for unsupported held_side/action combinations
    """
    held = (held_side or "").lower()
    act = (action or "").lower()

    if act == "buy":
        if held == "yes":
            return "yes"
        if held == "no":
            return "no"
    elif act == "sell":
        if held == "yes":
            return "no"  # selling NO is long YES
        if held == "no":
            return "yes"  # selling YES is long NO

    raise ValueError(f"Unsupported held/action: held={held_side}, action={action}")


def book_side_from_outcome_action(held_side: str, action: str) -> str:
    """Return the Kalshi V2 book side (bid/ask) for a given held outcome and action.

    Mapping:
        - BUY YES  -> bid (buy YES)
        - SELL NO  -> bid (buy YES)
        - BUY NO   -> ask (sell YES)
        - SELL YES -> ask (sell YES)
    """
    traded = traded_side_from_held(held_side, action)
    act = (action or "").lower()
    # bid = buy YES / sell NO; ask = sell YES / buy NO
    if (act == "buy" and traded == "yes") or (act == "sell" and traded == "no"):
        return "bid"
    return "ask"


# ── Canonical Price Range Checking ─────────────────────────────────────────────

# Canonical price ranges (NON-NEGOTIABLE invariants)
# CRITICAL FIX (2026-08-14): Fail-closed to the symmetric 10c-75c entry range
# that the GlobalAllocator enforces.  This is the single source of truth for
# executable entry prices and prevents extreme longshot / shortshot losses.
# It overrules the earlier 1c-85c / 15c-99c expansion that allowed 97c NO fills.
CANONICAL_MIN_CENTS = 10  # Production entry range minimum
CANONICAL_MAX_CENTS = 75  # Production entry range maximum
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
    """Check if price is in the production canonical entry range.

    CRITICAL FIX (2026-08-14): Fail-closed to the symmetric 10c-75c entry
    range.  This is the single source of truth for order eligibility across
    agent_grid, order_router, order_gate, loop_15m, and Kalshi client.  It
    prevents the extreme longshot / shortshot fills (e.g. 97c) that drained
    the bankroll.

    Args:
        price_cents: Price in cents (0-99)
        side: "yes" or "no" (for logging/context)

    Returns:
        True if price is in canonical entry range

    Example:
        >>> is_price_in_canonical_range(25, "yes")
        True
        >>> is_price_in_canonical_range(75, "yes")
        True
        >>> is_price_in_canonical_range(10, "yes")
        True
        >>> is_price_in_canonical_range(94, "no")
        False
    """
    return CANONICAL_MIN_CENTS <= price_cents <= CANONICAL_MAX_CENTS


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
    """Clamp price to canonical entry range (10c-75c).

    CRITICAL FIX (2026-08-14): Aligned with the symmetric 10c-75c production
    entry range.  DEPRECATED: prefer is_price_in_canonical_range() with side.

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
