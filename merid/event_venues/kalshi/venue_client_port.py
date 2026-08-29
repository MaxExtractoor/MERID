"""Adapter: wrap the production ``KalshiVenueClient`` in the ``KalshiExecutionPort``.

This keeps the HTTP-specific normalization (Kalshi V1/V2 wire formats, cursor
pagination, PlacedOrder/VenueOrder conversions) in one place so the simulator
and tests don't have to reimplement it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.event_venues.base import EventMarket, PlacedOrder, VenueOrder, VenuePosition
from merid.event_venues.kalshi.binary_price_space import v2_to_legacy
from utils.logger import get_logger
from merid.event_venues.kalshi.client import get_kalshi_client, KalshiVenueClient
from merid.event_venues.kalshi.port import (
    BalanceResult,
    CancelResult,
    CreateOrderRequest,
    CreateOrderResponse,
    Fill,
    FillsResponse,
    HistoricalFillsResponse,
    HistoricalPositionsResponse,
    KalshiExecutionPort,
    MarketResult,
    Order,
    OrderbookLevel,
    OrderbookResult,
    OrderGroup,
    OrderGroupsResult,
    Position,
    PositionsResponse,
)


logger = get_logger("merid.event_venues.kalshi.venue_client_port")


class KalshiVenueClientExecutionPort:
    """Production port implementation backed by ``KalshiVenueClient``."""

    def __init__(self, client: Optional[KalshiVenueClient] = None) -> None:
        self._client = client or get_kalshi_client()

    async def connect(self) -> None:
        await self._client.connect()

    async def close(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Order lifecycle
    # ------------------------------------------------------------------

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        firewall_approval_id = request.metadata.get("firewall_decision_id")

        # Enforce ExecutionRiskFirewall approval token for reduce-only / exit orders.
        is_exit = (
            bool(request.reduce_only)
            or request.metadata.get("entry_or_exit") in ("exit", "close")
            or bool(firewall_approval_id)
        )
        if is_exit:
            from merid.event_venues.kalshi.execution_risk_firewall import ExecutionRiskFirewall

            firewall = ExecutionRiskFirewall.get_instance()
            if firewall.is_enforced():
                decision = firewall.get_decision(request.client_order_id) if request.client_order_id else None
                if not decision or decision.decision_id != firewall_approval_id:
                    logger.critical(
                        "[PORT-FIREWALL-REJECT] client_order_id=%s missing/invalid approval token",
                        request.client_order_id,
                    )
                    return CreateOrderResponse(
                        success=False,
                        error="firewall:missing_or_invalid_approval_token",
                    )

        order = VenueOrder(
            market_id=request.ticker,
            side=request.side,
            size=request.size,
            price=Decimal(request.price_cents) / Decimal(100) if request.price_cents is not None else None,
            order_type=request.order_type,
            outcome_id=request.outcome,
            client_order_id=request.client_order_id,
            time_in_force=request.time_in_force,
            expiration_ts=request.expiration_ts,
            post_only=request.post_only,
            idempotency_key=request.idempotency_key,
            reduce_only=request.reduce_only,
            source=request.source,
            take_profit_price_cents=request.take_profit_price_cents,
            stop_loss_price_cents=request.stop_loss_price_cents,
            firewall_approval_id=firewall_approval_id,
            exchange_index=request.exchange_index,
            self_trade_prevention_type=request.self_trade_prevention_type,
            max_execution_cost_cents=request.max_execution_cost_cents,
        )

        result = await self._client.place_order_result(
            order,
            order_group_id=request.order_group_id,
            self_trade_prevention_type=request.self_trade_prevention_type,
            exchange_index=request.exchange_index,
        )

        if not result.success or result.data is None:
            return CreateOrderResponse(success=False, error=str(result.error))

        placed: PlacedOrder = result.data
        return _placed_order_to_response(placed, request.client_order_id)

    async def get_order(
        self,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        market_id: Optional[str] = None,
    ) -> Optional[Order]:
        if client_order_id:
            result = await self._client.get_order_by_client_id_result(client_order_id, market_id=market_id)
        elif order_id:
            result = await self._client.get_order_result(order_id, market_id)
        else:
            return None

        if not result.success or result.data is None:
            return None
        return _placed_order_to_order(result.data)

    async def cancel_order(self, order_id: str) -> CancelResult:
        result = await self._client.cancel_order_result(order_id)
        if result.success and result.data:
            return CancelResult(success=True, order_id=order_id, new_status="canceled")
        return CancelResult(success=False, order_id=order_id, error=str(result.error))

    async def get_open_orders(self, ticker: Optional[str] = None) -> List[Order]:
        result = await self._client.get_open_orders_result(ticker)
        if not result.success or result.data is None:
            return []
        return [_placed_order_to_order(o) for o in result.data]

    # ------------------------------------------------------------------
    # Positions / fills
    # ------------------------------------------------------------------

    async def get_positions(self) -> PositionsResponse:
        result = await self._client.get_positions_result()
        if not result.success or result.data is None:
            return PositionsResponse(positions=[], cursor=None)
        return PositionsResponse(
            positions=[_venue_position_to_position(p) for p in result.data],
            cursor=result.metadata.get("cursor"),
        )

    async def get_historical_positions(self, cursor: Optional[str] = None) -> HistoricalPositionsResponse:
        # Kalshi does not expose a separate "historical positions" REST endpoint,
        # but the V2 position stream and settled events include closed positions.
        # For now, delegate to get_positions and rely on downstream filtering.
        result = await self._client.get_positions_with_filters(
            filters={"nonzero": None}, limit=200  # type: ignore[arg-type]
        )
        if not result.success or result.data is None:
            return HistoricalPositionsResponse(positions=[], cursor=None)

        positions: List[VenuePosition] = []
        for _, pos_data in result.data.items():
            if isinstance(pos_data, list):
                positions.extend([_venue_position_to_position(p) for p in pos_data if isinstance(p, VenuePosition)])
        return HistoricalPositionsResponse(
            positions=positions,
            cursor=result.metadata.get("cursor"),
        )

    async def get_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        market_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> FillsResponse:
        result = await self._client.get_fills(
            limit=limit, since_ts=since_ts, ticker=market_id, order_id=order_id
        )
        if not result.success or result.data is None:
            return FillsResponse(fills=[], cursor=None)
        raw_fills = _aggregate_v2_fills(result.data)
        return FillsResponse(
            fills=[_venue_trade_to_fill(t) for t in raw_fills],
            cursor=result.metadata.get("cursor"),
        )

    async def get_historical_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
    ) -> HistoricalFillsResponse:
        # Kalshi fills are returned from /portfolio/history; the Kalshi client
        # has `get_portfolio_history` which we map here.
        result = await self._client.get_portfolio_history(limit=limit)
        if not result.success or result.data is None:
            return HistoricalFillsResponse(fills=[], cursor=None)

        history = result.data.get("history", [])
        fills: List[Fill] = []
        for entry in history:
            fills.append(Fill(
                fill_id=entry.get("id", ""),
                trade_id=entry.get("trade_id", ""),
                order_id=entry.get("order_id", ""),
                client_order_id=entry.get("client_order_id"),
                ticker=entry.get("ticker", ""),
                side=entry.get("side", ""),
                outcome=entry.get("outcome", ""),
                size=Decimal(str(entry.get("count", 0))),
                price_cents=int(float(entry.get("price", 0)) * 100),
                fee_usd=Decimal(str(entry.get("fees_paid", 0))) if entry.get("fees_paid") is not None else None,
                timestamp=None,
                raw_data=entry,
            ))
        return HistoricalFillsResponse(fills=fills, cursor=None)

    # ------------------------------------------------------------------
    # Market
    # ------------------------------------------------------------------

    async def get_market(self, ticker: str) -> MarketResult:
        result = await self._client.get_market_result(ticker)
        if not result.success:
            return MarketResult(success=False, error=str(result.error))
        return MarketResult(success=True, market=result.data)

    # ------------------------------------------------------------------
    # Account and market-data reads
    # ------------------------------------------------------------------

    @property
    def is_circuit_open(self) -> bool:
        return getattr(self._client, "is_circuit_open", False)

    async def get_balance(self) -> BalanceResult:
        result = await self._client.get_balance_result()
        if not result.success or result.data is None:
            return BalanceResult(success=False, error=str(result.error))
        return BalanceResult(
            success=True,
            available_usd=result.data.get("USD"),
            locked_usd=result.data.get("locked"),
            raw=result.data,
        )

    async def get_order_groups(self, limit: int = 200) -> OrderGroupsResult:
        result = await self._client.get_order_groups(limit=limit)
        if not result.success or result.data is None:
            return OrderGroupsResult(success=False, error=str(result.error))
        groups = []
        for raw_group in result.data:
            group_id = raw_group.get("id", raw_group.get("order_group_id", ""))
            orders = [
                _dict_to_order(order)
                for order in raw_group.get("orders", [])
            ]
            groups.append(OrderGroup(group_id=group_id, orders=orders, raw=raw_group))
        return OrderGroupsResult(
            success=True,
            groups=groups,
            raw=result.data,
            latency_ms=result.latency_ms or 0.0,
        )

    async def get_orderbook(self, ticker: str) -> OrderbookResult:
        result = await self._client.get_orderbook_result(ticker)
        if not result.success or result.data is None:
            return OrderbookResult(success=False, error=str(result.error))
        ob = result.data
        yes_levels = [
            OrderbookLevel(price_cents=int(price * 100), size=size, side="yes")
            for price, size in ob.bids
        ]
        no_levels = [
            OrderbookLevel(price_cents=int(price * 100), size=size, side="no")
            for price, size in ob.asks
        ]
        _ob_raw = getattr(ob, "raw_data", None)
        return OrderbookResult(
            success=True,
            yes_levels=yes_levels,
            no_levels=no_levels,
            timestamp=ob.timestamp.timestamp() if ob.timestamp else None,
            raw={"venue_orderbook": _ob_raw} if _ob_raw else {},
        )


# ------------------------------------------------------------------
# Conversions
# ------------------------------------------------------------------

def _placed_order_to_response(placed: PlacedOrder, client_order_id: Optional[str]) -> CreateOrderResponse:
    if placed.price is not None:
        # Round to the nearest cent; Kalshi V2 prices can arrive as decimals
        # like 0.0670 (6.7c) and truncation would understate fills.
        price_cents_int = int(round(placed.price * Decimal("100")))
    else:
        price_cents_int = None
    average_price_cents = price_cents_int
    price_cents = price_cents_int
    return CreateOrderResponse(
        success=True,
        order_id=placed.order_id,
        client_order_id=client_order_id or placed.raw_data.get("client_order_id"),
        status=_normalize_status(placed.status),
        filled_size=placed.filled_size,
        remaining_size=placed.remaining_size,
        price_cents=price_cents,
        average_price_cents=average_price_cents,
        raw_data=placed.raw_data or {},
    )


def _dict_to_order(raw: Dict[str, Any]) -> Order:
    """Convert a raw order dict (from order groups) into the normalized ``Order``."""
    price = raw.get("price", raw.get("yes_price", raw.get("no_price")))
    price_cents = int(float(price) * 100) if price is not None else None
    return Order(
        order_id=raw.get("order_id", "") or raw.get("id", ""),
        client_order_id=raw.get("client_order_id"),
        ticker=raw.get("market_id", "") or raw.get("ticker", ""),
        side=raw.get("side", "buy"),
        outcome=raw.get("outcome_id", ""),
        size=Decimal(str(raw.get("count", 0))),
        filled_size=Decimal(str(raw.get("filled_count", 0))),
        remaining_size=Decimal(str(raw.get("remaining_count", 0))),
        price_cents=price_cents,
        status=_normalize_status(raw.get("status", "pending")),
        time_in_force=raw.get("time_in_force", "GTC"),
        created_at=None,
        order_group_id=raw.get("order_group_id"),
        raw_data=raw,
    )


def _placed_order_to_order(placed: PlacedOrder) -> Order:
    return Order(
        order_id=placed.order_id,
        client_order_id=placed.raw_data.get("client_order_id") if placed.raw_data else None,
        ticker=placed.market_id,
        side=placed.raw_data.get("side", "buy") if placed.raw_data else "buy",
        outcome=placed.raw_data.get("outcome_id", "yes") if placed.raw_data else "yes",
        size=placed.size,
        filled_size=placed.filled_size,
        remaining_size=placed.remaining_size or Decimal("0"),
        price_cents=int(placed.price * 100) if placed.price is not None else None,
        status=_normalize_status(placed.status),
        time_in_force=placed.raw_data.get("time_in_force", "GTC") if placed.raw_data else "GTC",
        created_at=placed.created_at,
        order_group_id=placed.raw_data.get("order_group_id") if placed.raw_data else None,
        raw_data=placed.raw_data or {},
    )


def _venue_position_to_position(pos: VenuePosition) -> Position:
    # Preserve the source side exactly; fail-closed normalization happens at the
    # port -> ledger adapter, not here, so missing/empty outcomes remain detectable.
    _exchange_index = pos.exchange_index
    if _exchange_index is None and pos.raw_data:
        try:
            _exchange_index = int(pos.raw_data.get("exchange_index"))
        except Exception:
            _exchange_index = None
    return Position(
        ticker=pos.market_id,
        outcome=pos.outcome_id or "",
        size=pos.size,
        average_entry_price_cents=int(pos.average_entry_price * 100),
        realized_pnl_usd=pos.realized_pnl,
        unrealized_pnl_usd=pos.unrealized_pnl,
        raw_data={"venue_position": pos.raw_data} if pos.raw_data else {},
        exchange_index=_exchange_index,
    )


def _aggregate_v2_fills(raw_fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate V2 fill records that are split pieces of the same execution.

    Kalshi's ``/portfolio/fills`` can split a single contract execution into
    multiple records (e.g. 0.01 + 0.99) sharing the same ``fill_id``/``trade_id``.
    Grouping by the immutable ``fill_id`` first keeps the ledger position count
    exact while preserving one record per unique fill.  When ``fill_id`` is absent,
    fall back to the execution identity (order, timestamp, price, side).
    """
    groups: Dict[tuple, Dict[str, Any]] = {}
    for raw in raw_fills:
        fill_id = raw.get("fill_id") or raw.get("trade_id") or raw.get("id") or ""
        order_id = raw.get("order_id") or ""
        created = raw.get("created_time") or raw.get("created_at") or ""
        ts = raw.get("ts")
        ticker = raw.get("market_ticker") or raw.get("ticker") or ""
        yes_price = raw.get("yes_price_dollars")
        no_price = raw.get("no_price_dollars")
        action = raw.get("action") or raw.get("taker_action") or ""
        book_side = raw.get("book_side") or ""
        outcome_side = raw.get("outcome_side") or raw.get("side") or ""

        # Group by the immutable fill_id when present.  If an order fills at
        # different times or prices, it remains a separate fill.
        if fill_id:
            key = ("fill_id", fill_id)
        else:
            key = (
                order_id,
                str(created),
                str(ts),
                ticker,
                str(yes_price),
                str(no_price),
                str(action),
                str(book_side),
                str(outcome_side),
            )

        existing = groups.get(key)
        if existing is None:
            groups[key] = dict(raw)
            continue

        # Sum quantity and fee.
        try:
            existing_count = Decimal(str(existing.get("count_fp", "0")))
        except Exception:
            existing_count = Decimal("0")
        try:
            raw_count = Decimal(str(raw.get("count_fp", "0")))
        except Exception:
            raw_count = Decimal("0")
        total_count = existing_count + raw_count
        # Preserve two-decimal fixed-point form.
        existing["count_fp"] = f"{total_count:.2f}"

        try:
            existing_fee = Decimal(str(existing.get("fee_cost", "0")))
        except Exception:
            existing_fee = Decimal("0")
        try:
            raw_fee = Decimal(str(raw.get("fee_cost", "0")))
        except Exception:
            raw_fee = Decimal("0")
        total_fee = existing_fee + raw_fee
        existing["fee_cost"] = str(total_fee)

    return list(groups.values())


def _venue_trade_to_fill(trade: Any) -> Fill:
    from merid.event_venues.base import VenueTrade
    if isinstance(trade, VenueTrade):
        # VenueTrade carries the market price in dollars and the outcome side,
        # but not the user's action.  Best-effort: price in the known side.
        side = (trade.side or "").lower()
        if side in ("buy", "sell"):
            action, outcome = side, "yes"
        elif side in ("yes", "no"):
            action, outcome = "buy", side
        else:
            action, outcome = "buy", "yes"
        price_cents = (
            int(round(trade.price * Decimal("100")))
            if trade.price is not None else 0
        )
        return Fill(
            fill_id=trade.trade_id,
            trade_id=trade.trade_id,
            order_id=trade.order_id,
            client_order_id=None,
            ticker=trade.market_id,
            side=action,
            outcome=outcome,
            size=trade.size or Decimal("0"),
            price_cents=price_cents,
            fee_usd=trade.fee,
            timestamp=trade.timestamp,
            raw_data={},
        )

    # Kalshi V2 /portfolio/fills uses a single YES-space book.
    # Required fields for canonical conversion: action, book_side, outcome_side,
    # yes_price_dollars (or no_price_dollars), count_fp, created_time/ts.
    ticker = (
        trade.get("market_ticker")
        or trade.get("ticker")
        or trade.get("market_id")
        or trade.get("event_ticker")
        or ""
    )
    action = (trade.get("action") or trade.get("taker_action") or "").lower()
    book_side = (trade.get("book_side") or "").lower()
    outcome_side = (trade.get("outcome_side") or trade.get("side") or "").lower()

    def _yes_space_cents() -> int:
        yes_price = trade.get("yes_price_dollars")
        no_price = trade.get("no_price_dollars")
        price = trade.get("price")
        if yes_price not in (None, ""):
            return int(round(float(yes_price) * 100))
        if no_price not in (None, ""):
            return 100 - int(round(float(no_price) * 100))
        if price not in (None, ""):
            p = float(price)
            if p < 1.0:
                return int(round(p * 100))
            return int(round(p))
        return 0

    price_cents = 0
    try:
        if (
            action in ("buy", "sell")
            and book_side in ("bid", "ask")
            and outcome_side in ("yes", "no")
        ):
            canonical_action, canonical_outcome, price_cents = v2_to_legacy(
                book_side, _yes_space_cents(), outcome_side, action
            )
            action = canonical_action
            outcome = canonical_outcome
        else:
            raise ValueError("missing V2 fill fields")
    except Exception:
        # Fallback for V1 / legacy dicts that expose the user's action/outcome directly.
        outcome = (
            trade.get("outcome_id") or trade.get("outcome") or trade.get("side") or ""
        ).lower()
        if outcome in ("buy", "sell") and not action:
            action, outcome = outcome, "yes"
        if outcome not in ("yes", "no"):
            outcome = "yes"
        if action not in ("buy", "sell"):
            action = "buy"
        legacy_price = trade.get("price", 0)
        if legacy_price not in (None, ""):
            p = float(legacy_price)
            price_cents = int(round(p * 100)) if p < 1.0 else int(round(p))

    # Size: V2 uses count_fp; legacy used count/size.
    size = Decimal("0")
    for key in ("count_fp", "count", "size", "filled_count", "quantity"):
        val = trade.get(key)
        if val is not None and val != "":
            try:
                size = Decimal(str(val))
                break
            except Exception:
                continue

    # Fee: V2 uses fee_cost (dollars); legacy used fee (cents or dollars).
    fee_usd = None
    if trade.get("fee_cost") not in (None, ""):
        fee_usd = Decimal(str(trade["fee_cost"]))
    elif trade.get("fee") not in (None, ""):
        try:
            f = Decimal(str(trade["fee"]))
            fee_usd = f / Decimal("100") if f > Decimal("1") else f
        except Exception:
            fee_usd = None

    # Timestamp: prefer ISO created_time, then Unix ts (seconds).
    ts = trade.get("created_time") or trade.get("created_at")
    timestamp = None
    if ts:
        try:
            if isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            elif isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            timestamp = None
    if timestamp is None and trade.get("ts") not in (None, ""):
        try:
            timestamp = datetime.fromtimestamp(float(trade["ts"]), tz=timezone.utc)
        except Exception:
            timestamp = None

    return Fill(
        fill_id=trade.get("fill_id") or trade.get("trade_id") or trade.get("id") or "",
        trade_id=trade.get("trade_id", ""),
        order_id=trade.get("order_id", ""),
        client_order_id=trade.get("client_order_id"),
        ticker=ticker,
        side=action,
        outcome=outcome,
        size=size,
        price_cents=price_cents,
        fee_usd=fee_usd,
        timestamp=timestamp,
        raw_data=trade,
    )


def _normalize_status(status: str) -> str:
    s = (status or "pending").lower()
    if s in ("pending", "open", "live", "resting"):
        return "resting"
    if s in ("partially_filled", "partial"):
        return "partially_filled"
    if s == "unfilled":
        return "unfilled"
    if s in ("cancelled", "canceled"):
        return "canceled"
    if s == "rejected":
        return "rejected"
    if s == "expired":
        return "expired"
    if s == "filled":
        return "filled"
    return s
