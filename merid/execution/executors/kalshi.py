
"""Kalshi Executor — Canonical execution interface for Kalshi API.

This module provides the KalshiExecutor class which wraps the order_router
for API endpoint use. It provides a unified interface for:
- Order placement/cancellation/amendment
- Position queries
- Fill history
- Balance/connection checks
"""

from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.order_router import (
    route_order_async,
    OrderIntent,
    OrderResult,
)
from merid.event_venues.kalshi.client import get_kalshi_client
from utils.logger import get_logger

logger = get_logger("merid.execution.executors.kalshi")


class KalshiExecutor:
    """Canonical executor for Kalshi orders.
    
    Wraps the order_router for use by API endpoints and provides
    synchronous-style interface for common operations.
    """
    
    def __init__(self):
        self._client = None
    
    async def _get_client(self):
        """Lazy-load Kalshi REST client."""
        if self._client is None:
            self._client = get_kalshi_client()
        return self._client
    
    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        count: int,
        take_profit_price_cents: Optional[int] = None,
        take_profit_r_multiple: Optional[float] = None,
        stop_loss_price_cents: Optional[int] = None,
        **kwargs
    ) -> OrderResult:
        """Place an order via the canonical order router.
        
        For 15m crypto entry orders (buy), exit targets (TP/SL) are required.
        If not provided, default TP is computed using the dynamic TP engine.
        """
        # Compute default TP/SL for 15m crypto entry orders if not provided
        if action == "buy" and ticker.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M")):
            if take_profit_price_cents is None and take_profit_r_multiple is None:
                try:
                    from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine
                    engine = DynamicTakeProfitEngine()
                    
                    # Default SL: 5 cents below entry (conservative)
                    if stop_loss_price_cents is None:
                        stop_loss_price_cents = max(1, price_cents - 5)
                    
                    # CRITICAL FIX (2026-08-04): A position is always long its own side.
                    # Profit for both YES and NO means own-side price rising -> LONG.
                    tp_plan = engine.compute_tp(
                        entry_price=price_cents / 100.0,
                        stop_price=stop_loss_price_cents / 100.0,
                        direction="LONG",
                        confidence=0.5,  # Default medium confidence
                    )
                    
                    take_profit_r_multiple = tp_plan.tp_r_multiple
                    logger.info(
                        "[EXECUTOR-TP] Computed default TP for %s: R=%.2f",
                        ticker, tp_plan.tp_r_multiple
                    )
                except Exception as tp_exc:
                    logger.warning("[EXECUTOR-TP] Failed to compute default TP: %s", tp_exc)
                    # Fallback to 1R
                    take_profit_r_multiple = 1.0
                    if stop_loss_price_cents is None:
                        stop_loss_price_cents = max(1, price_cents - 5)
        
        intent = OrderIntent(
            ticker=ticker,
            side=side,
            action=action,
            price_cents=price_cents,
            count=count,
            take_profit_price_cents=take_profit_price_cents,
            take_profit_r_multiple=take_profit_r_multiple,
            stop_loss_price_cents=stop_loss_price_cents,
            **kwargs
        )
        return await route_order_async(intent)
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a resting order."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot cancel order: Kalshi client not available")
            return False
        try:
            return await client.cancel_order(order_id)
        except Exception as exc:
            logger.error(f"Cancel order {order_id} failed: {exc}")
            return False
    
    async def amend_order(
        self,
        order_id: str,
        price_cents: Optional[int] = None,
        count: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Amend (cancel-replace) an existing order."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot amend order: Kalshi client not available")
            return None
        try:
            op_result = await client.amend_order(order_id, yes_price=price_cents, new_count=count)
            if op_result.success:
                return {"order_id": order_id, "result": op_result.data}
            logger.error(f"Amend order {order_id} rejected: {op_result.error}")
            return None
        except Exception as exc:
            logger.error(f"Amend order {order_id} failed: {exc}")
            return None
    
    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders from Kalshi."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot get orders: Kalshi client not available")
            return []
        try:
            placed_orders = await client.get_open_orders()
            return [
                {
                    "order_id": o.order_id,
                    "ticker": o.market_id,
                    "side": o.side,
                    "count": int(o.size),
                    "remaining_count": int(o.remaining_size) if o.remaining_size is not None else int(o.size) - int(o.filled_size),
                    "filled_count": int(o.filled_size),
                    "yes_price": int(o.price * 100) if o.price is not None else None,
                    "status": o.status,
                    "created_time": str(o.created_at) if o.created_at else None,
                }
                for o in placed_orders
            ]
        except Exception as exc:
            logger.error(f"Get orders failed: {exc}")
            return []
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions from Kalshi."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot get positions: Kalshi client not available")
            return []
        try:
            venue_positions = await client.get_positions()
            return [
                {
                    "ticker": p.market_id,
                    "outcome": p.outcome_id or "yes",
                    "size": float(p.size),
                    "avg_price": float(p.average_entry_price),
                    "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl is not None else 0.0,
                    "realized_pnl": float(p.realized_pnl) if p.realized_pnl is not None else 0.0,
                    "source": "executor",
                }
                for p in venue_positions
            ]
        except Exception as exc:
            logger.error(f"Get positions failed: {exc}")
            return []
    
    async def get_fills(
        self,
        since_hours: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get fill history from Kalshi."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot get fills: Kalshi client not available")
            return []
        try:
            import time
            since_ts = int(time.time() - since_hours * 3600) if since_hours else None
            op_result = await client.get_fills(limit=limit, since_ts=since_ts)
            return op_result.unwrap_or([])
        except Exception as exc:
            logger.error(f"Get fills failed: {exc}")
            return []
    
    async def get_balance(self) -> Optional[Dict[str, Any]]:
        """Get account balance from Kalshi."""
        client = await self._get_client()
        if not client:
            logger.error("Cannot get balance: Kalshi client not available")
            return None
        try:
            result = await client.get_balance()
            return result if isinstance(result, dict) else None
        except Exception as exc:
            logger.error(f"Get balance failed: {exc}")
            return None
    
    async def authenticate(self) -> bool:
        """Check API connectivity by attempting authentication."""
        client = await self._get_client()
        if not client:
            return False
        try:
            await client.get_balance()
            return True
        except Exception as exc:
            logger.debug(f"Authentication check failed: {exc}")
            return False
