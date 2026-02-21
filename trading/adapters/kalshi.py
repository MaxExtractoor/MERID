"""Kalshi prediction market adapter.

Balance/telemetry reads use the legacy kalshi_client shim.
Order submission routes through merid/event_venues/kalshi/venue_adapter
(resilient async client with circuit breaker, paper/live mode gating).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List

from trading.adapters.base import BalanceSnapshot, OrderResult, TradeRequest, TradingVenueAdapterBase
from trading.adapters.registry import register_adapter
from trading.integrations.kalshi_client import fetch_kalshi_balance, get_kalshi_client
from utils.logger import get_logger

logger = get_logger("trading.adapters.kalshi")


class KalshiPredictionAdapter(TradingVenueAdapterBase):
    """Kalshi adapter — balance reads + live/paper order submission."""

    venue = "kalshi"
    supports_trading = True

    def __init__(self) -> None:
        super().__init__(use_mock=False)
        try:
            self._client = get_kalshi_client()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Kalshi client unavailable: %s", exc)
            self.use_mock = True
            self._client = None

    # ------------------------------------------------------------------ #
    # Live implementations
    # ------------------------------------------------------------------ #
    def _get_balances_live(self) -> List[BalanceSnapshot]:
        snapshot = fetch_kalshi_balance()
        amount = snapshot.get("balance") or 0
        try:
            usd_value = float(amount) / 100.0
        except (TypeError, ValueError):  # pragma: no cover
            usd_value = 0.0
        return [
            BalanceSnapshot(
                asset="USD",
                total=usd_value,
                available=usd_value,
                usd_value=usd_value,
                metadata=snapshot.get("raw", {}),
            )
        ]

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:
        """Submit a live or paper order via the Kalshi venue adapter."""
        from merid.event_venues.kalshi.venue_adapter import KalshiVenueAdapter
        from merid.event_venues.base import VenueOrder

        # Map TradeRequest → VenueOrder
        price = Decimal(str(request.price)) if request.price else None
        order = VenueOrder(
            market_id=request.symbol,
            side=request.side.value,  # "buy" / "sell"
            size=Decimal(str(request.quantity)),
            price=price,
            order_type="limit" if price else "market",
            outcome_id="yes",  # default; caller can override via metadata
            client_order_id=request.client_reference,
        )
        if request.metadata.get("outcome_id"):
            order = VenueOrder(
                market_id=order.market_id,
                side=order.side,
                size=order.size,
                price=order.price,
                order_type=order.order_type,
                outcome_id=request.metadata["outcome_id"],
                client_order_id=order.client_order_id,
            )

        adapter = KalshiVenueAdapter()
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # Called from a sync context inside a running event loop
                # (e.g. a thread pool worker).  Use run_coroutine_threadsafe
                # so we can block the calling thread without deadlocking.
                import concurrent.futures as _cf
                fut = _cf.Future()

                async def _submit() -> None:
                    try:
                        fut.set_result(await adapter.submit_order(order))
                    except Exception as _e:
                        fut.set_exception(_e)

                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(_submit(), loop=loop)
                )
                placed = fut.result(timeout=30.0)
            else:
                placed = asyncio.run(adapter.submit_order(order))
        except Exception as exc:
            logger.error("Kalshi _submit_order_live failed: %s", exc)
            return OrderResult(
                venue=self.venue,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                executed_price=0.0,
                status="rejected",
                error=str(exc),
            )

        executed_price = float(placed.price) if placed.price else 0.0
        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=float(placed.filled_size),
            executed_price=executed_price,
            status=placed.status,
            order_id=placed.order_id,
            raw=placed.raw_data,
        )


register_adapter(KalshiPredictionAdapter())
