"""Alpaca equities adapter powered by Alpaca Trade API."""

from __future__ import annotations

from typing import Any, Dict, List

from trading.adapters.base import (
    BalanceSnapshot,
    OrderResult,
    PositionSnapshot,
    TradeRequest,
    TradeSide,
    TradingVenueAdapterBase,
)
from trading.adapters.registry import register_adapter
from trading.integrations import fetch_account_snapshot, get_alpaca_client
from utils.logger import get_logger

logger = get_logger("trading.adapters.alpaca")


class AlpacaEquitiesAdapter(TradingVenueAdapterBase):
    """Routes spot equity orders through Alpaca."""

    venue = "alpaca"
    supports_trading = True

    def __init__(self) -> None:
        super().__init__(use_mock=False)
        try:
            self._client = get_alpaca_client()
        except Exception as exc:  # pragma: no cover - defensive against missing creds
            logger.warning("Alpaca client unavailable: %s", exc)
            self._client = None
            self.use_mock = True
        self._default_time_in_force = "day"

    # ------------------------------------------------------------------ #
    # Live implementations
    # ------------------------------------------------------------------ #
    def _get_balances_live(self) -> List[BalanceSnapshot]:
        snapshot = fetch_account_snapshot()
        try:
            cash = float(snapshot.get("cash", 0.0))
            portfolio_value = float(snapshot.get("portfolio_value", cash))
        except (TypeError, ValueError):  # pragma: no cover
            cash = 0.0
            portfolio_value = 0.0
        return [
            BalanceSnapshot(
                asset="USD",
                total=portfolio_value,
                available=cash,
                usd_value=portfolio_value,
                metadata=snapshot,
            )
        ]

    def _get_positions_live(self) -> List[PositionSnapshot]:
        if not self._client:
            return []
        try:
            positions = self._client.list_positions()
        except Exception as exc:  # pragma: no cover - network/SDK specific
            logger.error("Failed to fetch Alpaca positions: %s", exc)
            return []

        snapshots: List[PositionSnapshot] = []
        for pos in positions:
            raw = getattr(pos, "_raw", None) or getattr(pos, "__dict__", {})
            try:
                snapshots.append(
                    PositionSnapshot(
                        symbol := raw.get("symbol") or pos.symbol,
                        quantity=float(raw.get("qty") or raw.get("qty_available") or pos.qty),
                        entry_price=float(raw.get("avg_entry_price") or 0.0),
                        mark_price=float(raw.get("current_price") or raw.get("market_price") or 0.0),
                        unrealized_pnl=float(raw.get("unrealized_pl") or 0.0),
                        metadata=raw,
                    )
                )
            except Exception:  # pragma: no cover - skip malformed row
                continue
        return snapshots

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:  # type: ignore[override]
        if not self._client:
            raise RuntimeError("Alpaca adapter unavailable - verify API credentials")

        side = "buy" if request.side == TradeSide.BUY else "sell"
        order_type = request.order_type.value.lower()
        tif = request.metadata.get("time_in_force") if isinstance(request.metadata, dict) else None
        tif = str(tif or self._default_time_in_force)
        payload: Dict[str, Any] = {
            "symbol": request.symbol,
            "qty": request.quantity,
            "side": side,
            "type": order_type if order_type in {"market", "limit"} else "market",
            "time_in_force": tif,
            "client_order_id": request.client_reference,
        }
        if payload["type"] == "limit":
            if request.price is None:
                raise RuntimeError("Limit orders require price for Alpaca adapter")
            payload["limit_price"] = request.price

        logger.info("Submitting Alpaca order %s", payload)
        order = self._client.submit_order(**payload)
        raw = getattr(order, "_raw", None) or getattr(order, "__dict__", {})
        executed_price = float(raw.get("filled_avg_price") or request.price or 0.0)
        filled_qty = float(raw.get("filled_qty") or 0.0) or request.quantity

        metadata = {
            "alpaca_order_id": raw.get("id") or order.id,
            "status": raw.get("status"),
            "raw": raw,
        }
        fills = [
            {
                "qty": raw.get("filled_qty"),
                "price": raw.get("filled_avg_price"),
                "status": raw.get("status"),
            }
        ]

        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=filled_qty,
            executed_price=executed_price,
            status=raw.get("status", "submitted"),
            venue_order_id=str(raw.get("id")),
            metadata={"fills": fills, **metadata},
        )


register_adapter(AlpacaEquitiesAdapter())
