"""Anti-corruption adapter: normalized ``KalshiExecutionPort`` DTOs -> legacy ledger dicts.

This is the narrow boundary between the new async port and the legacy fills ledger /
position cache.  It is intentionally fail-closed: any missing identity or quantity
field becomes a ``PortLedgerAdapterError`` instead of a malformed ledger dict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from merid.event_venues.kalshi.port import Fill, Position


class PortLedgerAdapterError(ValueError):
    """Raised when a port DTO cannot be safely converted to a legacy ledger dict."""

    def __init__(self, message: str, *, field: Optional[str] = None, value: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


def _coerce_decimal(value: Any, name: str) -> Decimal:
    """Coerce a value to Decimal; raise a typed error on failure."""
    if value is None:
        raise PortLedgerAdapterError(f"{name} is required", field=name, value=value)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PortLedgerAdapterError(
            f"{name}={value!r} is not a valid decimal",
            field=name,
            value=value,
        ) from exc


def _quantity_cc_from_count_fp(value: Any, name: str) -> int:
    """Convert a fixed-point contract count to an integer of centi-contracts.

    Kalshi V2 supports fractional contracts at 0.01 minimum granularity.
    A count of `1.55` becomes `155` centi-contracts; `0.49` becomes `49`.
    Rounding is never applied. The result must be a positive integer.
    """
    decimal_value = _coerce_decimal(value, name)
    # Multiply by 100 exactly, then drop the Decimal scale without rounding.
    # `as_tuple().exponent` is -2 when the value is exact to two decimals.
    quantity_cc = int(decimal_value * Decimal("100"))
    if quantity_cc <= 0:
        raise PortLedgerAdapterError(
            f"{name} must be positive, got {quantity_cc} centi-contracts",
            field=name,
            value=value,
        )
    return quantity_cc


def _coerce_non_negative_cc(value: Any, name: str) -> int:
    """Coerce a value to non-negative centi-contracts."""
    decimal_value = _coerce_decimal(value, name)
    quantity_cc = int(decimal_value * Decimal("100"))
    if quantity_cc < 0:
        raise PortLedgerAdapterError(
            f"{name} must be non-negative, got {quantity_cc} centi-contracts",
            field=name,
            value=value,
        )
    return quantity_cc


def _timestamp_to_float(ts: Any) -> Optional[float]:
    """Preserve the source timestamp as a Unix float.  Returns None for a missing source ts."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        # Preserve the source timestamp exactly (do not rewrite to ingestion time).
        return ts.replace(tzinfo=timezone.utc).timestamp() if ts.tzinfo is None else ts.timestamp()
    try:
        return float(ts)
    except (ValueError, TypeError):
        return None


def _validate_side(side: Optional[str], name: str, allowed: tuple[str, ...]) -> str:
    """Validate a categorical side/outcome field."""
    if not side:
        raise PortLedgerAdapterError(f"{name} is required", field=name, value=side)
    side = side.lower()
    if side not in allowed:
        raise PortLedgerAdapterError(
            f"{name} must be one of {allowed}, got {side!r}",
            field=name,
            value=side,
        )
    return side


def port_fill_to_ledger_dict(fill: Fill) -> Dict[str, Any]:
    """Convert a normalized ``Fill`` to the dict expected by ``KalshiFillsLedger._parse_fill``.

    Fail-closed on missing identity or quantity fields:
      - ``fill_id`` and ``ticker`` must be present.
      - ``size`` must be a positive fixed-point count.
      - ``price_cents`` must be present (legacy display) but is not canonical.
      - ``side`` must be ``buy`` or ``sell``.
      - ``outcome`` must be ``yes`` or ``no``.

    The returned dict preserves both the source ``timestamp`` and the ``ingested_at``
    time, and it does not silently default missing count or price to zero/None.
    Quantity is converted to integer centi-contracts (``quantity_cc``) and the
    exact fixed-point count is preserved in ``count_fp``.
    """
    if fill is None:
        raise PortLedgerAdapterError("fill is None", field="fill")

    if not fill.fill_id:
        raise PortLedgerAdapterError("fill.fill_id is missing or empty", field="fill_id", value=fill.fill_id)
    if not fill.ticker:
        raise PortLedgerAdapterError("fill.ticker is missing or empty", field="ticker", value=fill.ticker)

    # Quantity must be present and positive, in fixed-point contracts.
    quantity_cc = _quantity_cc_from_count_fp(fill.size, "fill.size")

    # Price: prefer exact dollar price from raw_data; fall back to price_cents as display only.
    price_dollars: Optional[Decimal] = None
    raw = fill.raw_data or {}
    if isinstance(raw, dict):
        outcome = _validate_side(fill.outcome, "fill.outcome", ("yes", "no"))
        price_key = "yes_price_dollars" if outcome == "yes" else "no_price_dollars"
        if raw.get(price_key):
            try:
                price_dollars = _coerce_decimal(raw[price_key], price_key)
            except PortLedgerAdapterError:
                price_dollars = None
        elif raw.get("price_dollars"):
            try:
                price_dollars = _coerce_decimal(raw["price_dollars"], "price_dollars")
            except PortLedgerAdapterError:
                price_dollars = None
    if price_dollars is None:
        if fill.price_cents is None:
            raise PortLedgerAdapterError("fill.price_cents is missing and no exact price_dollars available", field="price_cents", value=fill.price_cents)
        try:
            price_dollars = Decimal(fill.price_cents) / Decimal("100")
        except Exception as exc:
            raise PortLedgerAdapterError(
                f"fill.price_cents={fill.price_cents!r} is not a valid price",
                field="price_cents",
                value=fill.price_cents,
            ) from exc

    # Direction fields must be explicit and valid.
    action = _validate_side(fill.side, "fill.side", ("buy", "sell"))
    outcome = _validate_side(fill.outcome, "fill.outcome", ("yes", "no"))

    # Fee: do not default to a number when missing, but the legacy ledger treats a
    # missing fee as zero.  Preserve None explicitly so downstream can distinguish it.
    fee_dollars: Optional[str] = None
    if fill.fee_usd is not None:
        fee_dollars = str(fill.fee_usd)

    source_ts = _timestamp_to_float(fill.timestamp)
    ingestion_ts = datetime.now(timezone.utc).timestamp()

    return {
        # Identity
        "fill_id": fill.fill_id,
        "trade_id": fill.trade_id or fill.fill_id,
        "order_id": fill.order_id,
        "client_order_id": fill.client_order_id,
        "market_ticker": fill.ticker,
        "ticker": fill.ticker,
        "market_id": fill.ticker,
        # Direction
        "action": action,
        "side": outcome,
        "outcome_side": outcome,
        # Quantity: count_fp is the exact fixed-point string; quantity_cc is integer centi-contracts.
        "count": str(fill.size),
        "count_fp": str(fill.size),
        "size": str(fill.size),
        "quantity_cc": quantity_cc,
        # Price
        "price": str(price_dollars),
        "price_dollars": str(price_dollars),
        # Fee
        "fee": fee_dollars if fee_dollars is not None else "0",
        "fee_paid": fee_dollars if fee_dollars is not None else "0",
        # Timestamps
        "timestamp": source_ts,
        "created_time": source_ts,
        "ingested_at": ingestion_ts,
        # Provenance
        "source": "http_poller",
        "raw_data": fill.raw_data if fill.raw_data is not None else {},
        # 2026-08-27: Maintain client_tag alias so legacy ledger promotion never
        # dereferences a missing attribute when the dict is parsed back.
        "client_tag": fill.client_order_id,
    }


def port_position_to_ledger_dict(position: Position) -> Dict[str, Any]:
    """Convert a normalized ``Position`` to the dict expected by legacy consumers.

    Fail-closed on missing identity or quantity fields:
      - ``ticker`` must be present.
      - ``size`` must be present.
      - ``outcome`` must be ``yes`` or ``no`` for non-zero positions.
      - ``average_entry_price_cents`` must be present and non-zero for non-zero positions.

    Signed NO exposure is normalized to canonical ``side`` + absolute ``count``.
    Missing or negative ``size`` with an empty side flips the side and takes the
    absolute value, matching Kalshi's REST convention for NO positions.
    """
    if position is None:
        raise PortLedgerAdapterError("position is None", field="position")

    if not position.ticker:
        raise PortLedgerAdapterError("position.ticker is missing or empty", field="ticker", value=position.ticker)
    if position.size is None:
        raise PortLedgerAdapterError("position.size is missing", field="size", value=position.size)

    size = _coerce_decimal(position.size, "position.size")

    if position.average_entry_price_cents is None:
        raise PortLedgerAdapterError(
            "position.average_entry_price_cents is missing",
            field="average_entry_price_cents",
            value=position.average_entry_price_cents,
        )
    try:
        avg_price_cents = int(position.average_entry_price_cents)
    except Exception as exc:
        raise PortLedgerAdapterError(
            f"position.average_entry_price_cents={position.average_entry_price_cents!r} is not a valid integer",
            field="average_entry_price_cents",
            value=position.average_entry_price_cents,
        ) from exc

    # Side handling: explicit outcome if present, otherwise infer only from signed size.
    side = (position.outcome or "").lower().strip()
    if size == 0:
        # Settled/closed position: side does not affect exposure, but preserve it if given.
        if not side:
            side = "yes"
    else:
        if not side:
            # Kalshi REST convention: a negative position_fp with no side means a NO position.
            if size < 0:
                size = -size
                side = "no"
            else:
                # Positive size with an empty side would require inventing a side.
                raise PortLedgerAdapterError(
                    "position.outcome is missing for non-zero position",
                    field="outcome",
                    value=position.outcome,
                )
        elif side not in ("yes", "no"):
            raise PortLedgerAdapterError(
                f"position.outcome must be 'yes' or 'no', got {side!r}",
                field="outcome",
                value=position.outcome,
            )
        else:
            # Signed exposure normalization: negative size inverts the side.
            if size < 0:
                size = -size
                side = "no" if side == "yes" else "yes"

        # Non-zero open positions must have a real entry price.
        if avg_price_cents <= 0:
            raise PortLedgerAdapterError(
                f"position.average_entry_price_cents must be positive for non-zero position, got {avg_price_cents}",
                field="average_entry_price_cents",
                value=avg_price_cents,
            )

    # Compute canonical quantity from the normalized, sign-correct size.
    quantity_cc = int(size * Decimal("100"))
    # contracts is kept for legacy consumers as display whole contracts (floor), not canonical.
    contracts = int(size)

    return {
        # Identity
        "market_ticker": position.ticker,
        "market_id": position.ticker,
        "ticker": position.ticker,
        # Direction
        "side": side,
        "outcome": side,
        # Quantity: quantity_cc is canonical; contracts is display-only.
        "quantity_cc": quantity_cc,
        "contracts": contracts,
        "count": contracts,
        "quantity": contracts,
        # Price
        "avg_price_cents": avg_price_cents,
        "avg_price": avg_price_cents,
        # PnL (preserved, not defaulted)
        "realized_pnl_usd": str(position.realized_pnl_usd) if position.realized_pnl_usd is not None else None,
        "unrealized_pnl_usd": str(position.unrealized_pnl_usd) if position.unrealized_pnl_usd is not None else None,
        # Provenance
        "raw_data": position.raw_data if position.raw_data is not None else {},
    }


def port_fills_to_ledger_dicts(fills: list) -> list[Dict[str, Any]]:
    """Convert a list of ``Fill`` DTOs, skipping any that fail validation and logging why."""
    out: list[Dict[str, Any]] = []
    for fill in fills:
        try:
            out.append(port_fill_to_ledger_dict(fill))
        except PortLedgerAdapterError as exc:
            from utils.logger import get_logger
            logger = get_logger("merid.event_venues.kalshi.port_ledger_adapter")
            logger.warning("Skipping malformed fill: %s", exc, extra={"field": exc.field, "value": str(exc.value)})
    return out


def port_positions_to_ledger_dicts(positions: list) -> list[Dict[str, Any]]:
    """Convert a list of ``Position`` DTOs, skipping any that fail validation."""
    out: list[Dict[str, Any]] = []
    for position in positions:
        try:
            out.append(port_position_to_ledger_dict(position))
        except PortLedgerAdapterError as exc:
            from utils.logger import get_logger
            logger = get_logger("merid.event_venues.kalshi.port_ledger_adapter")
            logger.warning("Skipping malformed position: %s", exc, extra={"field": exc.field, "value": str(exc.value)})
    return out
