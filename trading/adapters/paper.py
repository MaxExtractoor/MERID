"""Paper trading adapter that routes unified orders to the PaperTradingEngine."""

from __future__ import annotations

from typing import Dict

from trading.adapters.base import (
    OrderResult,
    TradeRequest,
    TradeSide,
    TradingVenueAdapterBase,
)
from trading.adapters.registry import register_adapter
from trading.paper_trading import get_paper_engine


class PaperTradingAdapter(TradingVenueAdapterBase):
    venue = "paper"
    supports_trading = True

    def __init__(self) -> None:
        super().__init__(use_mock=False)
        self._engine = get_paper_engine()

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:  # type: ignore[override]
        user_id = request.metadata.get("trader_id", "paper_router")
        side = "long" if request.side == TradeSide.BUY else "short"
        notional = request.metadata.get("notional_usd") or (request.price or 0.0) * request.quantity
        order = self._engine.place_order(
            user_id=user_id,
            asset=request.symbol,
            side=side,
            size_usd=float(notional or 0.0),
            order_type="market",
            price=request.price,
            leverage=int(request.metadata.get("leverage", 1)),
        )

        fills: Dict[str, float] = {
            "fill_price": order.fill_price or 0.0,
            "filled_size": order.filled_size or float(notional or 0.0),
        }
        status = "executed" if order.status.value == "filled" else order.status.value

        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            executed_price=order.fill_price or 0.0,
            status=status,
            metadata={"fills": [fills]},
        )


register_adapter(PaperTradingAdapter())
