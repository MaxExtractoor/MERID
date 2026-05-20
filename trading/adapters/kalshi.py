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

        Schedules the coroutine on the registered main loop via
        ``run_coroutine_threadsafe``.  Calling ``asyncio.run`` here (or in a
        thread-pool worker) creates a fresh event loop that the venue
        client's HTTP/socket resources don't belong to — corrupting Windows
        IOCP state and producing InvalidStateError + WinError 995.
        """
        if not self._venue_client:
            return []
        try:
            from core.event_loop_registry import run_on_main_loop, get_main_loop
            if get_main_loop() is None:
                logger.debug(
                    "Kalshi balance fetch skipped: main loop not yet registered"
                )
                return []
            bal = run_on_main_loop(self._venue_client.get_balance(), timeout=10)
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

        Schedules the coroutine on the registered main loop via
        ``run_coroutine_threadsafe``.  Calling ``asyncio.run`` here creates
        a fresh event loop the venue client's resources don't belong to,
        corrupting Windows IOCP state (InvalidStateError + WinError 995).

        OPTIMIZATION (2026-05-11): Reduced timeout from 15s to 8s and improved fallback.
        Use position cache as primary fallback with faster timeout to reduce main loop blocking.
        """
        if not self._venue_client:
            return []
        try:
            from core.event_loop_registry import run_on_main_loop, get_main_loop
            if get_main_loop() is None:
                logger.debug(
                    "Kalshi positions fetch skipped: main loop not yet registered"
                )
                return []
            # Reduced timeout from 15s to 8s to minimize main loop blocking
            positions = run_on_main_loop(
                self._venue_client.get_positions(), timeout=8
            )
        except Exception as exc:
            logger.debug("Kalshi positions fetch timed out (%s) - using position cache", type(exc).__name__)
            # FALLBACK: Use position cache when REST API times out
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                cache = get_position_cache()
                cached_positions = cache.get_all_positions(validate_freshness=False)
                
                if cached_positions:
                    results = []
                    for market_id, pos in cached_positions.items():
                        results.append(PositionSnapshot(
                            symbol=market_id,
                            quantity=float(pos.contracts),
                            entry_price=float(pos.avg_price_cents) / 100.0 if pos.avg_price_cents else 0.0,
                            mark_price=float(pos.avg_price_cents) / 100.0 if pos.avg_price_cents else 0.0,  # CachedPosition doesn't have current_price_cents
                            unrealized_pnl=float(pos.unrealized_pnl_usd) if pos.unrealized_pnl_usd else 0.0,
                            metadata={"venue": "kalshi", "outcome": pos.side or "", "source": "position_cache"},
                        ))
                    logger.debug("Kalshi positions: using %d positions from cache", len(results))
                    return results
            except Exception as cache_exc:
                logger.error("Position cache fallback failed: %s", cache_exc)
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
            from core.event_loop_registry import run_on_main_loop, get_main_loop
            if get_main_loop() is None:
                raise RuntimeError(
                    "main loop not registered; cannot submit live order"
                )
            placed = run_on_main_loop(adapter.submit_order(order), timeout=30.0)
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
