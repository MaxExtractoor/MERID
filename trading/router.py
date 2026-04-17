"""Shim module exposing new MERID execution router for legacy imports — DEPRECATED.

Superseded by merid/pipeline/router.py (TradeRouter with full risk gating,
mode management, and instrument resolution). Kept for backward compatibility.
"""

from __future__ import annotations

import threading
from typing import Optional

from merid.execution.base import TradeExecutor, TradeResult
from merid.execution.router import ExecutionRouter as _ExecutionRouter, TraderIdentity
from trading.adapters.base import TradeRequest, TradeSide
from trading.adapters.registry import get_adapter

import trading.adapters  # noqa: F401 - ensure default adapters register


_router: Optional[_ExecutionRouter] = None
_router_lock = threading.Lock()


def _adapter_executor_factory(venue: str) -> Optional[TradeExecutor]:
    adapter = get_adapter(venue)
    if adapter is None:
        return None

    class AdapterExecutor(TradeExecutor):
        def __init__(self, wrapped_adapter):
            self._adapter = wrapped_adapter
            self.venue = wrapped_adapter.venue

        async def get_quote(self, symbol, side, amount):  # pragma: no cover - shim
            raise NotImplementedError("Adapter-based executors do not support get_quote")

        async def execute_trade(self, symbol, side, amount, order_type="market", price=None, metadata=None):
            request = TradeRequest(
                venue=self._adapter.venue,
                symbol=symbol,
                side=TradeSide(side.lower()),
                quantity=amount,
                order_type=TradeRequest.__dataclass_fields__["order_type"].default,
                price=price,
                metadata=metadata or {},
            )
            result = self._adapter.submit_order(request)
            return TradeResult(
                success=result.status == "executed",
                venue=result.venue,
                symbol=result.symbol,
                side=result.side.value,
                size=result.quantity,
                price=result.executed_price,
                tx_id=result.venue_order_id or result.transaction_hash,
                error=result.metadata.get("error"),
                metadata=result.metadata,
            )

        async def get_positions(self):  # pragma: no cover - shim
            return []

    return AdapterExecutor(adapter)


def get_execution_router() -> _ExecutionRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = _ExecutionRouter(executor_factory=_adapter_executor_factory)
    return _router
