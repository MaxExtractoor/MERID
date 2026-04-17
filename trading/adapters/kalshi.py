"""Kalshi prediction market adapter.

Balance/telemetry reads use the canonical KalshiVenueClient.
Order submission routes through merid/event_venues/kalshi/venue_adapter
(resilient async client with circuit breaker, paper/live mode gating).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List

from trading.adapters.base import (
    BalanceSnapshot,
    OrderResult,
    PositionSnapshot,
    TradeRequest,
    TradingVenueAdapterBase,
)
from trading.adapters.registry import register_adapter
from utils.logger import get_logger

logger = get_logger("trading.adapters.kalshi")


class KalshiPredictionAdapter(TradingVenueAdapterBase):
    """Kalshi adapter — balance/position reads + live/paper order submission."""

    venue = "kalshi"
    supports_trading = True

    def __init__(self) -> None:
        super().__init__(use_mock=False)
        self._venue_client = None
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client as get_venue_client
            self._venue_client = get_venue_client()
        except Exception as exc:
            logger.warning("Kalshi venue client unavailable: %s", exc)

    # ------------------------------------------------------------------ #
    # Live implementations
    # ------------------------------------------------------------------ #
    def _get_balances_live(self) -> List[BalanceSnapshot]:
        """Fetch actual balances from Kalshi REST API.
        
        Uses asyncio.run_coroutine_threadsafe to avoid deadlocks when called
        from a sync context inside a running event loop.
        """
        if not self._venue_client:
            return []
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Called from inside running loop - use run_coroutine_threadsafe
                # This requires the loop to be running in a different thread
                # or we need to use a thread pool to avoid deadlock
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._venue_client.get_balance()
                    )
                    bal = future.result(timeout=10)
            else:
                bal = loop.run_until_complete(self._venue_client.get_balance())
        except Exception as exc:
            logger.error("Kalshi balance fetch failed: %s", exc, exc_info=True)
            return []
        usd_value = float(bal.get("USD", 0))
        return [
            BalanceSnapshot(
                asset="USD",
                total=usd_value,
                available=usd_value,
                usd_value=usd_value,
                metadata={},
            )
        ]

    def _get_positions_live(self) -> List[PositionSnapshot]:
        """Fetch actual positions from Kalshi REST API.
        
        Uses thread pool execution to avoid deadlocks when called
        from a sync context inside a running event loop.
        """
        if not self._venue_client:
            return []
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # Called from a sync context inside a running event loop
                # (e.g. a thread pool worker). Use run_coroutine_threadsafe
                # so we can block the calling thread without deadlocking.
                import concurrent.futures as _cf
                fut = _cf.Future()

                async def _fetch() -> None:
                    try:
                        fut.set_result(await self._venue_client.get_positions())
                    except Exception as _e:
                        fut.set_exception(_e)

                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(_fetch(), loop=loop)
                )
                positions = fut.result(timeout=15)
            else:
                positions = asyncio.run(self._venue_client.get_positions())
        except Exception as exc:
            logger.error("Kalshi positions fetch failed: %s", exc, exc_info=True)
            return []
        results = []
        for vp in positions:
            results.append(PositionSnapshot(
                symbol=vp.market_id,
                quantity=float(vp.size),
                entry_price=float(vp.average_entry_price) if vp.average_entry_price else 0.0,
                mark_price=0.0,  # VenuePosition doesn't carry mark_price
                unrealized_pnl=float(vp.unrealized_pnl) if vp.unrealized_pnl else 0.0,
                metadata={"venue": "kalshi", "outcome": vp.outcome_id or ""},
            ))
        return results

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
                metadata={"error": str(exc)},
            )

        executed_price = float(placed.price) if placed.price else 0.0
        return OrderResult(
            venue=self.venue,
            symbol=request.symbol,
            side=request.side,
            quantity=float(placed.filled_size),
            executed_price=executed_price,
            status=placed.status,
            venue_order_id=placed.order_id,
            metadata={"raw": placed.raw_data},
        )


register_adapter(KalshiPredictionAdapter())
