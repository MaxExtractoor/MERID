"""Settlement-grade price precision utilities.

Separates three concepts explicitly:

1. Raw source precision — preserve exactly what the provider supplied.
2. Settlement precision — use the market's live ``custom_strike.round_digits``.
3. Display precision — only apply formatting when writing logs/UI.

All signal-path code should use :func:`parse_price` to ingest prices as
:class:`Decimal` and should never round/quantize until the final consumer
(settlement model or display logger).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Final, Optional


@dataclass(frozen=True)
class AssetPrecision:
    settlement_digits: int
    settlement_quantum: Decimal


# Fallback table: used for startup validation and when Kalshi metadata is
# temporarily unavailable.  The canonical source is Kalshi's
# ``custom_strike.round_digits``.
PRECISION: Final[Dict[str, AssetPrecision]] = {
    "BTC": AssetPrecision(2, Decimal("0.01")),
    "ETH": AssetPrecision(2, Decimal("0.01")),
    "SOL": AssetPrecision(4, Decimal("0.0001")),
    "XRP": AssetPrecision(4, Decimal("0.0001")),
    "DOGE": AssetPrecision(7, Decimal("0.0000001")),
}


def get_asset_settlement_digits(asset: str, fallback: Optional[int] = None) -> int:
    """Return the expected settlement digits for ``asset``.

    If ``fallback`` is provided and the asset is not in the table, ``fallback``
    is returned.  If no fallback is provided, ``4`` is returned as a
    conservative default that never silently collapses precision to 2.
    """
    asset = (asset or "").upper().strip()
    if asset in PRECISION:
        return PRECISION[asset].settlement_digits
    if fallback is not None and isinstance(fallback, int) and fallback >= 0:
        return fallback
    return 4


def get_asset_settlement_quantum(asset: str) -> Decimal:
    """Return the settlement quantum for ``asset``."""
    asset = (asset or "").upper().strip()
    if asset in PRECISION:
        return PRECISION[asset].settlement_quantum
    return Decimal("0.0001")


def parse_price(raw: Any) -> Optional[Decimal]:
    """Parse a price value into a :class:`Decimal` without loss.

    Accepts ``Decimal``, ``int``, ``float``, or ``str``.  ``float`` values are
    converted via ``str`` so the nearest decimal representation is used rather
    than the binary artifact.  Returns ``None`` for missing/invalid inputs.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        # Strip optional leading $ or currency marks but keep sign/digits.
        s = re.sub(r"^[^\d\-\.]+", "", s)
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def settlement_round(price: Decimal, digits: int) -> Decimal:
    """Quantize ``price`` to the market's settlement quantum exactly once.

    Uses ``ROUND_HALF_UP`` to match Kalshi's official settlement rounding.
    """
    if not isinstance(price, Decimal):
        raise TypeError(f"settlement_round expected Decimal, got {type(price)}")
    if not price.is_finite():
        raise ValueError(f"settlement_round requires a finite price, got {price}")
    if digits < 0:
        raise ValueError(f"settlement digits must be non-negative, got {digits}")
    quantum = Decimal(1).scaleb(-digits)
    return price.quantize(quantum, rounding=ROUND_HALF_UP)


def format_price(asset: str, price: Any, fallback_digits: int = 4) -> str:
    """Format ``price`` for display using the asset's settlement digits.

    This is **display only**.  It must never be called before computation.
    """
    if price is None:
        return "None"
    d = parse_price(price)
    if d is None:
        return str(price)
    digits = get_asset_settlement_digits(asset, fallback=fallback_digits)
    try:
        return f"{d:.{digits}f}"
    except Exception:
        return str(d)


def retained_decimal_places(price: Decimal) -> int:
    """Return the number of decimal places retained by ``price``.

    For ``Decimal('0.0848348')`` this returns ``7``.  For integers it
    returns ``0``.
    """
    if not isinstance(price, Decimal):
        return 0
    if not price.is_finite():
        return 0
    exp = price.as_tuple().exponent
    if isinstance(exp, int):
        return max(0, -exp)
    return 0


def assert_market_precision(
    asset: str,
    price: Decimal,
    market_digits: int,
    require_at_least: bool = True,
) -> None:
    """Fail fast if ``price`` does not retain enough precision for ``market_digits``.

    If ``require_at_least`` is ``True`` (the default), the price must retain
    at least ``market_digits`` decimal places.  This catches the observed DOGE
    case where a 4-decimal ``0.0848`` is fed into a 7-decimal market.
    """
    asset = (asset or "").upper().strip()
    if not isinstance(price, Decimal):
        raise TypeError(f"{asset}: expected Decimal price, got {type(price)}")
    if not price.is_finite():
        raise ValueError(f"{asset}: price is not finite: {price}")

    expected_digits = get_asset_settlement_digits(asset, fallback=market_digits)
    if market_digits != expected_digits:
        raise ValueError(
            f"{asset}: catalog precision {market_digits} does not match "
            f"expected settlement precision {expected_digits}"
        )

    retained = retained_decimal_places(price)
    if require_at_least and retained < market_digits:
        raise ValueError(
            f"{asset}: price {price} retains only {retained} decimals; "
            f"market requires {market_digits}"
        )


def extract_custom_strike_round_digits(raw: Dict[str, Any]) -> Optional[int]:
    """Parse ``custom_strike.round_digits`` from a Kalshi market raw record.

    Returns ``None`` if the field is missing or invalid.
    """
    custom = raw.get("custom_strike")
    if not isinstance(custom, dict):
        return None
    rd = custom.get("round_digits")
    if rd is None:
        return None
    try:
        return int(rd)
    except (TypeError, ValueError):
        return None
