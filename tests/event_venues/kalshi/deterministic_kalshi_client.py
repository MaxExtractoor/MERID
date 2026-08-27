"""Deterministic, in-memory Kalshi exchange simulator.

Implements both the low-level ``KalshiVenueClient``-style result API used by the
P0 execution tests and the normalized ``KalshiExecutionPort`` boundary so it can
be injected into ``merid.event_venues.kalshi.port.get_kalshi_execution_port``.

No network calls, no respx, fully synchronous in-memory state with explicit time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from merid.event_venues.base import (
    EventMarket,
    EventOutcome,
    PlacedOrder,
    VenueOrder,
    VenuePosition,
    VenueTrade,
)
from merid.event_venues.kalshi.binary_price_space import legacy_to_v2
from merid.event_venues.kalshi.port import (
    CancelResult,
    CreateOrderRequest,
    CreateOrderResponse,
    Fill,
    FillsResponse,
    HistoricalFillsResponse,
    HistoricalPositionsResponse,
    MarketResult,
    Order,
    Position,
    PositionsResponse,
)
from merid.resilience.result import OperationResult


# ---------------------------------------------------------------------------
# Dual-purpose return wrappers
# ---------------------------------------------------------------------------


class _CancelResult(CancelResult):
    """CancelResult that also works as a bool for lower-level callers."""

    def __bool__(self) -> bool:
        return self.success


class _MarketResult(MarketResult):
    """MarketResult that can be used like an Optional[EventMarket] as well."""

    def __bool__(self) -> bool:
        return self.success and self.market is not None

    def __getattr__(self, name: str) -> Any:
        if self.market is not None:
            return getattr(self.market, name)
        raise AttributeError(name)


class _PositionsList(list):
    """List of VenuePosition that also exposes the port-style ``positions``."""

    def __init__(
        self,
        iterable: Any = (),
        positions: Optional[List[Position]] = None,
        cursor: Optional[str] = None,
    ) -> None:
        super().__init__(iterable)
        self.positions: List[Position] = positions if positions is not None else []
        self.cursor: Optional[str] = cursor


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class DeterministicKalshiClient:
    """In-memory Kalshi simulator that is also a ``KalshiExecutionPort``."""

    def __init__(self) -> None:
        self._time: int = 0
        self._orderbooks: Dict[str, Dict[str, Any]] = {}
        self._orders: Dict[str, PlacedOrder] = {}
        self._client_to_order: Dict[str, str] = {}
        self._next_order_id: int = 1
        self._fills: List[Dict[str, Any]] = []
        self._next_fill_id: int = 1
        self._balance_usd: Decimal = Decimal("0")
        self._locked_usd: Decimal = Decimal("0")
        # YES positions are accessed directly by tests; keep the legacy names.
        self._position_yes: Dict[str, Decimal] = {}
        self._position_cost: Dict[str, Decimal] = {}
        self._position_no: Dict[str, Decimal] = {}
        self._position_no_cost: Dict[str, Decimal] = {}
        self._market_positions: List[Dict[str, Any]] = []
        self._event_positions: List[Dict[str, Any]] = []
        self._historical_positions: List[VenuePosition] = []
        self._markets: Dict[str, EventMarket] = {}
        self._expired_markets: set = set()
        self._timeout_after_submit: Optional[str] = None

    # ---------------------------------------------------------------------
    # Time / setup helpers
    # ---------------------------------------------------------------------

    def set_time(self, ts: int) -> None:
        self._time = int(ts)

    def get_time(self) -> int:
        return self._time

    def set_orderbook(
        self,
        ticker: str,
        best_bid_cents: int,
        best_ask_cents: int,
        bid_size: Any,
        ask_size: Any,
    ) -> None:
        self._orderbooks[ticker] = {
            "best_bid_cents": int(best_bid_cents),
            "best_ask_cents": int(best_ask_cents),
            "bid_size": Decimal(str(bid_size)),
            "ask_size": Decimal(str(ask_size)),
        }

    def set_balance(self, balance: Any, locked: Any) -> None:
        self._balance_usd = Decimal(str(balance))
        self._locked_usd = Decimal(str(locked))

    def set_initial_position(
        self, ticker: str, outcome: str, size: Any, avg_price_cents: int = 0
    ) -> None:
        size_d = Decimal(str(size))
        avg = Decimal(str(avg_price_cents)) / Decimal(100)
        cost = size_d * avg
        if outcome == "yes":
            self._position_yes[ticker] = size_d
            self._position_cost[ticker] = cost
        else:
            self._position_no[ticker] = size_d
            self._position_no_cost[ticker] = cost

    def set_live_positions(
        self,
        market_positions: Optional[List[Dict[str, Any]]] = None,
        event_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._market_positions = list(market_positions or [])
        self._event_positions = list(event_positions or [])

    def set_historical_positions(self, positions: Optional[List[VenuePosition]] = None) -> None:
        self._historical_positions = list(positions or [])

    def set_market(self, ticker: str, event_market: Optional[EventMarket] = None) -> None:
        if event_market is None:
            event_market = self._default_market(ticker, active=True, resolved=False)
        self._markets[ticker] = event_market

    def set_market_expired(self, ticker: str) -> None:
        self._expired_markets.add(ticker)
        if ticker in self._markets:
            self._markets[ticker].resolved = True
            self._markets[ticker].active = False

    def set_timeout_after_submit(self, mode: str) -> None:
        self._timeout_after_submit = mode

    def inject_fill(self, fill: Dict[str, Any]) -> None:
        self._fills.append(fill)

    # ---------------------------------------------------------------------
    # Connection lifecycle
    # ---------------------------------------------------------------------

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    # ---------------------------------------------------------------------
    # Order entry
    # ---------------------------------------------------------------------

    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        result = await self.place_order_result(order)
        return result.unwrap_or(None)

    async def place_order_result(
        self,
        order: VenueOrder,
        order_group_id: Optional[str] = None,
        self_trade_prevention_type: Optional[str] = None,
    ) -> OperationResult[Optional[PlacedOrder]]:
        client_order_id = order.client_order_id

        # Idempotency: existing client_order_id simply returns the recorded order.
        if client_order_id and client_order_id in self._client_to_order:
            oid = self._client_to_order[client_order_id]
            placed = self._orders[oid]
            self._maybe_expire(placed)
            return OperationResult.ok(placed)

        ticker = order.market_id
        if not ticker or not ticker.startswith("KX"):
            return OperationResult.fail(ValueError(f"Invalid ticker: {ticker}"))

        raw_price_cents = self._raw_price_cents(order)
        if raw_price_cents <= 0:
            return OperationResult.fail(ValueError("Order price must be > 0"))

        action = (order.side or "buy").lower()
        outcome = (order.outcome_id or "yes").lower()

        try:
            book_side, yes_price_cents = legacy_to_v2(action, outcome, raw_price_cents)
        except ValueError as e:
            return OperationResult.fail(e)

        # Reduce-only: must offset an existing position, and fills are capped by it.
        position = self._position_for_outcome(ticker, outcome)
        if order.reduce_only:
            if action == "sell" and position <= 0:
                return OperationResult.fail(
                    ValueError("Reduce-only sell has no long position to reduce")
                )
            if action == "buy" and position >= 0:
                return OperationResult.fail(
                    ValueError("Reduce-only buy has no short position to reduce")
                )
            if action == "sell":
                effective_size = min(order.size, position)
            else:
                effective_size = min(order.size, -position)
        else:
            effective_size = order.size

        # Match against the deterministic orderbook.
        book = self._orderbooks.get(ticker)
        fill_size = Decimal("0")
        fill_yes_cents = 0
        crosses = False
        blocked = False

        if book:
            if book_side == "bid":
                if yes_price_cents >= book["best_ask_cents"]:
                    fill_size = min(effective_size, book["ask_size"])
                    fill_yes_cents = book["best_ask_cents"]
                    crosses = True
            else:
                if yes_price_cents <= book["best_bid_cents"]:
                    fill_size = min(effective_size, book["bid_size"])
                    fill_yes_cents = book["best_bid_cents"]
                    crosses = True

        # Non-reduce orders below 10c in YES-space do not get filled.
        if crosses and not order.reduce_only and yes_price_cents < 10:
            fill_size = Decimal("0")
            fill_yes_cents = 0
            crosses = False
            blocked = True

        # FOK: all or nothing.
        tif = self._normalize_tif(order.time_in_force)
        if tif == "FOK" and fill_size < effective_size:
            fill_size = Decimal("0")
            fill_yes_cents = 0
            crosses = False

        order_id = self._new_order_id()
        placed = PlacedOrder(
            order_id=order_id,
            market_id=ticker,
            side=action,
            size=order.size,
            price=order.price if order.price is not None else Decimal("0"),
            filled_size=Decimal("0"),
            remaining_size=order.size,
            status="pending",
            venue="kalshi",
            created_at=datetime.fromtimestamp(self._time, tz=timezone.utc),
            raw_data={},
        )
        placed.client_order_id = client_order_id
        placed.outcome_id = outcome
        placed.time_in_force = tif
        placed._tif = tif
        if tif == "GTT":
            placed._expiration_ts = order.expiration_ts

        if fill_size > 0:
            fill_price_d = self._fill_price_dollars(fill_yes_cents, outcome)
            self._update_position(ticker, outcome, fill_size, fill_price_d, action)
            self._record_fill(
                ticker, outcome, action, order_id, fill_size, fill_yes_cents, fill_price_d
            )

            if order.reduce_only:
                remaining = Decimal("0")
            else:
                remaining = order.size - fill_size

            if remaining == 0:
                status = "filled"
            else:
                status = "partially_filled"
                if tif in ("IOC", "FOK"):
                    remaining = Decimal("0")

            placed.filled_size = fill_size
            placed.remaining_size = remaining
            placed.status = status
            placed.raw_data["average_fill_price"] = str(fill_price_d)
        else:
            if tif in ("IOC", "FOK") or blocked:
                placed.filled_size = Decimal("0")
                placed.remaining_size = Decimal("0")
                placed.status = "unfilled"
            elif tif == "GTT" and order.expiration_ts is not None and self._time > order.expiration_ts:
                placed.filled_size = Decimal("0")
                placed.remaining_size = Decimal("0")
                placed.status = "expired"
            else:
                placed.filled_size = Decimal("0")
                placed.remaining_size = order.size
                placed.status = "resting"

        placed.raw_data.update(
            {
                "order_id": order_id,
                "ticker": ticker,
                "client_order_id": client_order_id or "",
                "side": action,
                "outcome_id": outcome,
                "time_in_force": tif,
                "order_type": order.order_type or "limit",
                "count": str(order.size),
                "filled_count": str(placed.filled_size),
                "remaining_count": str(placed.remaining_size),
                "price": str(placed.price) if placed.price is not None else "",
                "status": placed.status,
                "order_group_id": order_group_id,
                "self_trade_prevention_type": self_trade_prevention_type,
            }
        )

        self._orders[order_id] = placed
        if client_order_id:
            self._client_to_order[client_order_id] = order_id

        # Timeout-after-submit: the order is recorded; we then return a timeout.
        if self._timeout_after_submit == "once":
            self._timeout_after_submit = None
            return OperationResult.fail(asyncio.TimeoutError("simulated timeout"))

        return OperationResult.ok(placed)

    # ---------------------------------------------------------------------
    # Order query
    # ---------------------------------------------------------------------

    async def get_order(
        self,
        order_id: Optional[str] = None,
        market_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Optional[Order]:
        if client_order_id:
            result = await self.get_order_by_client_id_result(client_order_id)
        elif order_id:
            result = await self.get_order_result(order_id)
        else:
            return None
        if not result.success or result.data is None:
            return None
        return self._placed_order_to_port_order(result.data)

    async def get_order_result(
        self, order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[Optional[PlacedOrder]]:
        placed = self._orders.get(order_id)
        if not placed:
            return OperationResult.ok(None)
        self._maybe_expire(placed)
        return OperationResult.ok(placed)

    async def get_order_by_client_id_result(
        self, client_order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[Optional[PlacedOrder]]:
        oid = self._client_to_order.get(client_order_id)
        if not oid:
            return OperationResult.ok(None)
        placed = self._orders[oid]
        if market_id and placed.market_id != market_id:
            return OperationResult.ok(None)
        self._maybe_expire(placed)
        return OperationResult.ok(placed)

    async def get_open_orders_result(
        self, market_id: Optional[str] = None
    ) -> OperationResult[List[PlacedOrder]]:
        open_orders: List[PlacedOrder] = []
        for placed in self._orders.values():
            self._maybe_expire(placed)
            if market_id and placed.market_id != market_id:
                continue
            if placed.status in ("canceled", "expired", "filled", "unfilled", "rejected"):
                continue
            if placed.remaining_size is None or placed.remaining_size <= 0:
                continue
            open_orders.append(placed)
        return OperationResult.ok(open_orders)

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[Order]:
        result = await self.get_open_orders_result(market_id)
        if not result.success or result.data is None:
            return []
        return [self._placed_order_to_port_order(o) for o in result.data]

    # ---------------------------------------------------------------------
    # Cancel
    # ---------------------------------------------------------------------

    async def cancel_order(
        self, order_id: str, market_id: Optional[str] = None
    ) -> _CancelResult:
        result = await self.cancel_order_result(order_id)
        return _CancelResult(
            success=result.success and bool(result.data),
            order_id=order_id,
            new_status="canceled",
            error=str(result.error) if not result.success else None,
        )

    async def cancel_order_result(
        self, order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[bool]:
        placed = self._orders.get(order_id)
        if not placed:
            return OperationResult.fail(ValueError(f"Order not found: {order_id}"))
        self._maybe_expire(placed)
        if placed.status == "canceled":
            return OperationResult.ok(True)
        if placed.status in ("filled", "expired", "unfilled", "rejected"):
            return OperationResult.fail(
                ValueError(f"Order is already in terminal state: {placed.status}")
            )
        placed.status = "canceled"
        placed.remaining_size = Decimal("0")
        return OperationResult.ok(True)

    # ---------------------------------------------------------------------
    # Fills
    # ---------------------------------------------------------------------

    async def get_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        ticker: Optional[str] = None,
        market_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> OperationResult[List[Dict[str, Any]]]:
        # Normalize to the KalshiExecutionPort interface (market_id == ticker).
        _ticker = market_id if market_id is not None else ticker
        filtered: List[Dict[str, Any]] = []
        for f in self._fills:
            if since_ts is not None:
                ts = self._parse_created_time(f.get("created_time"))
                if ts is not None and ts < since_ts:
                    continue
            if _ticker and f.get("ticker") != _ticker:
                continue
            if order_id and f.get("order_id") != order_id:
                continue
            filtered.append(f)

        if limit:
            filtered = filtered[:limit]

        port_fills = [self._fill_dict_to_port(f) for f in filtered]
        result = OperationResult.ok(filtered)
        result.fills = port_fills
        result.cursor = None
        return result

    async def get_historical_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
    ) -> HistoricalFillsResponse:
        result = await self.get_fills(cursor=cursor, since_ts=since_ts, limit=limit)
        return HistoricalFillsResponse(fills=result.fills, cursor=result.cursor)

    # ---------------------------------------------------------------------
    # Positions
    # ---------------------------------------------------------------------

    async def get_positions(self) -> _PositionsList:
        result = await self.get_positions_result()
        return result.data or _PositionsList([])

    async def get_positions_result(self) -> OperationResult[_PositionsList]:
        derived = self._derived_positions()
        live = self._parse_live_positions()

        by_key: Dict[Tuple[str, Optional[str]], VenuePosition] = {}
        for pos in derived:
            by_key[(pos.market_id, pos.outcome_id)] = pos
        for pos in live:
            by_key[(pos.market_id, pos.outcome_id)] = pos

        positions = list(by_key.values())
        port_positions = [self._venue_position_to_port(p) for p in positions]
        return OperationResult.ok(
            _PositionsList(positions, positions=port_positions, cursor=None)
        )

    async def get_historical_positions(
        self, cursor: Optional[str] = None
    ) -> HistoricalPositionsResponse:
        result = await self.get_historical_positions_result()
        positions = result.unwrap_or([])
        return HistoricalPositionsResponse(
            positions=[self._venue_position_to_port(p) for p in positions],
            cursor=None,
        )

    async def get_historical_positions_result(
        self,
    ) -> OperationResult[List[VenuePosition]]:
        return OperationResult.ok(list(self._historical_positions))

    # ---------------------------------------------------------------------
    # Balance
    # ---------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, Decimal]:
        result = await self.get_balance_result()
        return result.unwrap_or({"USD": Decimal("0"), "locked": Decimal("0")})

    async def get_balance_result(self) -> OperationResult[Dict[str, Decimal]]:
        return OperationResult.ok(
            {"USD": self._balance_usd, "locked": self._locked_usd}
        )

    # ---------------------------------------------------------------------
    # Market
    # ---------------------------------------------------------------------

    async def get_market(self, ticker: str) -> _MarketResult:
        result = await self.get_market_result(ticker)
        if not result.success:
            return _MarketResult(success=False, error=str(result.error))
        return _MarketResult(success=True, market=result.data)

    async def get_market_result(
        self, market_id: str
    ) -> OperationResult[Optional[EventMarket]]:
        if market_id in self._expired_markets:
            return OperationResult.ok(
                self._default_market(
                    market_id, active=False, resolved=True, resolution="expired"
                )
            )
        if market_id in self._markets:
            return OperationResult.ok(self._markets[market_id])
        return OperationResult.ok(self._default_market(market_id))

    # ---------------------------------------------------------------------
    # KalshiExecutionPort interface
    # ---------------------------------------------------------------------

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        order = VenueOrder(
            market_id=request.ticker,
            side=request.side,
            size=request.size,
            price=Decimal(request.price_cents) / Decimal(100)
            if request.price_cents is not None
            else None,
            order_type=request.order_type,
            outcome_id=request.outcome,
            client_order_id=request.client_order_id,
            time_in_force=request.time_in_force,
            expiration_ts=request.expiration_ts,
            post_only=request.post_only,
            idempotency_key=request.idempotency_key,
            reduce_only=request.reduce_only,
            source=request.source,
        )
        result = await self.place_order_result(
            order,
            order_group_id=request.order_group_id,
            self_trade_prevention_type=request.self_trade_prevention_type,
        )
        if not result.success or result.data is None:
            return CreateOrderResponse(success=False, error=str(result.error))
        placed = result.data

        avg_fill_price = placed.raw_data.get("average_fill_price")
        if avg_fill_price:
            average_price_cents = int(Decimal(str(avg_fill_price)) * Decimal(100))
        else:
            average_price_cents = (
                int(placed.price * 100) if placed.price is not None else None
            )

        price_cents = (
            int(placed.price * 100) if placed.price is not None else average_price_cents
        )

        return CreateOrderResponse(
            success=True,
            order_id=placed.order_id,
            client_order_id=request.client_order_id,
            status=self._normalize_port_status(placed.status),
            filled_size=placed.filled_size,
            remaining_size=placed.remaining_size or Decimal("0"),
            price_cents=price_cents,
            average_price_cents=average_price_cents,
            raw_data=placed.raw_data or {},
        )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _new_order_id(self) -> str:
        oid = f"ord-{self._next_order_id}"
        self._next_order_id += 1
        return oid

    def _new_fill_id(self) -> str:
        fid = f"fill-{self._next_fill_id}"
        self._next_fill_id += 1
        return fid

    def _normalize_tif(self, tif: Optional[str]) -> str:
        mapping = {
            "GTC": "GTC",
            "GOOD_TILL_CANCELED": "GTC",
            "GOODTILLCANCELED": "GTC",
            "IOC": "IOC",
            "IMMEDIATE_OR_CANCEL": "IOC",
            "IMMEDIATEORCANCEL": "IOC",
            "FOK": "FOK",
            "FILL_OR_KILL": "FOK",
            "FILLORKILL": "FOK",
            "GTT": "GTT",
            "GOOD_TILL_TIME": "GTT",
            "GOODTILLTIME": "GTT",
        }
        return mapping.get((tif or "GTC").upper().replace("_", ""), "GTC")

    def _raw_price_cents(self, order: VenueOrder) -> int:
        if order.price is not None:
            return int((order.price * Decimal(100)).to_integral_value())

        # Market-order fallback against the current book.
        book = self._orderbooks.get(order.market_id)
        if not book:
            return 50

        action = (order.side or "buy").lower()
        outcome = (order.outcome_id or "yes").lower()

        if outcome == "yes":
            return book["best_ask_cents"] if action == "buy" else book["best_bid_cents"]
        else:
            return (
                100 - book["best_bid_cents"]
                if action == "buy"
                else 100 - book["best_ask_cents"]
            )

    def _fill_price_dollars(self, fill_yes_cents: int, outcome: str) -> Decimal:
        if outcome == "yes":
            return Decimal(fill_yes_cents) / Decimal(100)
        return Decimal(100 - fill_yes_cents) / Decimal(100)

    def _position_for_outcome(self, ticker: str, outcome: str) -> Decimal:
        if outcome == "yes":
            return self._position_yes.get(ticker, Decimal("0"))
        return self._position_no.get(ticker, Decimal("0"))

    def _update_position(
        self,
        ticker: str,
        outcome: str,
        fill_size: Decimal,
        fill_price_d: Decimal,
        side: str,
    ) -> None:
        if outcome == "yes":
            size_map = self._position_yes
            cost_map = self._position_cost
        else:
            size_map = self._position_no
            cost_map = self._position_no_cost

        current_size = size_map.get(ticker, Decimal("0"))
        current_cost = cost_map.get(ticker, Decimal("0"))

        if side == "buy":
            new_size = current_size + fill_size
            new_cost = current_cost + fill_size * fill_price_d
        else:
            avg = current_cost / current_size if current_size != 0 else fill_price_d
            new_size = current_size - fill_size
            new_cost = current_cost - fill_size * avg
            if new_size == 0:
                new_cost = Decimal("0")

        size_map[ticker] = new_size
        cost_map[ticker] = new_cost

        if side == "buy":
            self._balance_usd -= fill_size * fill_price_d
        else:
            self._balance_usd += fill_size * fill_price_d

    def _record_fill(
        self,
        ticker: str,
        outcome: str,
        side: str,
        order_id: str,
        fill_size: Decimal,
        fill_yes_cents: int,
        fill_price_d: Decimal,
    ) -> None:
        self._fills.append(
            {
                "trade_id": self._new_fill_id(),
                "order_id": order_id,
                "market_ticker": ticker,
                "side": outcome,
                "action": side,
                "count": int(fill_size),
                "yes_price": fill_yes_cents,
                "no_price": 100 - fill_yes_cents,
                "price": str(fill_price_d),
                "fee": "0",
                "created_time": datetime.fromtimestamp(
                    self._time, tz=timezone.utc
                ).isoformat(),
            }
        )

    def _market_is_resolved(self, ticker: str) -> bool:
        if ticker in self._expired_markets:
            return True
        market = self._markets.get(ticker)
        if market is not None:
            return bool(market.resolved)
        return False

    def _maybe_expire(self, placed: PlacedOrder) -> None:
        tif = getattr(placed, "_tif", "").upper()
        exp = getattr(placed, "_expiration_ts", None)
        if tif == "GTT" and exp is not None and self._time > exp:
            if placed.status in ("resting", "partially_filled", "open", "pending"):
                placed.status = "expired"
                placed.remaining_size = Decimal("0")
        if self._market_is_resolved(placed.market_id):
            if placed.status in ("resting", "partially_filled", "open", "pending"):
                placed.status = "expired"
                placed.remaining_size = Decimal("0")

    def _placed_order_to_port_order(self, placed: PlacedOrder) -> Order:
        raw = placed.raw_data or {}
        order = Order(
            order_id=placed.order_id,
            client_order_id=raw.get("client_order_id") or placed.order_id,
            ticker=placed.market_id,
            side=raw.get("side", "buy"),
            outcome=raw.get("outcome_id", "yes"),
            size=placed.size,
            filled_size=placed.filled_size,
            remaining_size=placed.remaining_size or Decimal("0"),
            price_cents=int(placed.price * 100) if placed.price is not None else None,
            status=self._normalize_port_status(placed.status),
            time_in_force=raw.get("time_in_force", "GTC"),
            created_at=placed.created_at,
            order_group_id=raw.get("order_group_id"),
            raw_data=raw,
        )
        # Extra attributes so the object works for low-level callers too.
        order.market_id = placed.market_id
        order.id = placed.order_id
        order.price = placed.price
        order.venue = "kalshi"
        return order

    def _normalize_port_status(self, status: str) -> str:
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

    def _derived_positions(self) -> List[VenuePosition]:
        positions: List[VenuePosition] = []
        for ticker, size in self._position_yes.items():
            if size == 0:
                continue
            cost = self._position_cost.get(ticker, Decimal("0"))
            avg = cost / size if size != 0 else Decimal("0")
            positions.append(
                VenuePosition(
                    market_id=ticker,
                    outcome_id="yes",
                    size=size,
                    average_entry_price=avg,
                    venue="kalshi",
                )
            )
        for ticker, size in self._position_no.items():
            if size == 0:
                continue
            cost = self._position_no_cost.get(ticker, Decimal("0"))
            avg = cost / size if size != 0 else Decimal("0")
            positions.append(
                VenuePosition(
                    market_id=ticker,
                    outcome_id="no",
                    size=size,
                    average_entry_price=avg,
                    venue="kalshi",
                )
            )
        return positions

    def _parse_live_positions(self) -> List[VenuePosition]:
        positions: List[VenuePosition] = []
        for raw in self._market_positions + self._event_positions:
            if isinstance(raw, VenuePosition):
                positions.append(raw)
                continue
            if not isinstance(raw, dict):
                continue
            ticker = raw.get("ticker") or raw.get("market_ticker") or raw.get("market_id", "")
            outcome = (
                raw.get("side")
                or raw.get("outcome_id")
                or raw.get("outcome")
                or "yes"
            )
            count = (
                raw.get("count")
                or raw.get("position_fp")
                or raw.get("count_fp")
                or 0
            )
            try:
                size = Decimal(str(count))
            except InvalidOperation:
                size = Decimal("0")

            if "avg_price_cents" in raw:
                avg = Decimal(str(raw["avg_price_cents"])) / Decimal(100)
            else:
                avg_val = (
                    raw.get("avg_price_dollars")
                    or raw.get("avg_price")
                    or raw.get("average_entry_price")
                    or 0
                )
                try:
                    avg = Decimal(str(avg_val))
                except InvalidOperation:
                    avg = Decimal("0")

            positions.append(
                VenuePosition(
                    market_id=ticker,
                    outcome_id=outcome,
                    size=size,
                    average_entry_price=avg,
                    venue="kalshi",
                )
            )
        return positions

    def _venue_position_to_port(self, pos: VenuePosition) -> Position:
        return Position(
            ticker=pos.market_id,
            outcome=pos.outcome_id or "yes",
            size=pos.size,
            average_entry_price_cents=int(pos.average_entry_price * 100),
            realized_pnl_usd=pos.realized_pnl,
            unrealized_pnl_usd=pos.unrealized_pnl,
            raw_data={},
        )

    def _parse_created_time(self, ts_str: Optional[str]) -> Optional[float]:
        if not ts_str:
            return None
        ts_str = str(ts_str).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            return None

    def _fill_dict_to_port(self, f: Dict[str, Any]) -> Fill:
        return Fill(
            fill_id=f.get("trade_id") or f.get("id", ""),
            order_id=f.get("order_id", ""),
            ticker=f.get("market_ticker") or f.get("ticker", ""),
            side=f.get("action", ""),
            outcome=f.get("outcome_id") or f.get("side", "yes"),
            size=Decimal(str(f.get("count") or f.get("size", 0))),
            price_cents=int(float(f.get("price", 0)) * 100),
            fee_usd=Decimal(str(f.get("fee") or 0)),
            timestamp=None,
            raw_data=f,
        )

    def _default_market(
        self,
        ticker: str,
        active: bool = True,
        resolved: bool = False,
        resolution: Optional[str] = None,
    ) -> EventMarket:
        return EventMarket(
            market_id=ticker,
            venue="kalshi",
            question=ticker,
            description="",
            outcomes=[
                EventOutcome(
                    outcome_id="yes",
                    outcome_name="Yes",
                    price=Decimal("0.5"),
                    best_bid=Decimal("0.5"),
                    best_ask=Decimal("0.5"),
                ),
                EventOutcome(
                    outcome_id="no",
                    outcome_name="No",
                    price=Decimal("0.5"),
                    best_bid=Decimal("0.5"),
                    best_ask=Decimal("0.5"),
                ),
            ],
            active=active,
            resolved=resolved,
            resolution=resolution,
        )
