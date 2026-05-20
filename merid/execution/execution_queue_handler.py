"""Execution Queue Handler — Processes queue entries through to order execution.

Handles the flow:
    1. Dequeue validated entry from TopEdgeExecutionQueue
    2. Submit to OrderRouter
    3. Handle confirmation/rejection
    4. Update ticker state (PENDING → OPEN or IDLE)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from utils.logger import get_logger
from merid.execution.execution_queue import (
    TopEdgeExecutionQueue,
    ExecutionQueueEntry,
    get_execution_queue,
)

logger = get_logger("merid.execution.execution_queue_handler")


class ExecutionQueueHandler:
    """Async handler for processing execution queue entries."""

    def __init__(
        self,
        queue: Optional[TopEdgeExecutionQueue] = None,
        poll_interval_seconds: float = 0.1,
        max_concurrent: int = 5,
    ):
        self._queue = queue or get_execution_queue()
        self._poll_interval = poll_interval_seconds
        self._max_concurrent = max_concurrent
        self._shutdown = False
        self._handler_task: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_entries: Dict[str, ExecutionQueueEntry] = {}
        self._lock = threading.Lock()
        self._orders_submitted = 0
        self._orders_accepted = 0
        self._orders_rejected = 0

    async def start(self) -> None:
        if self._handler_task is None:
            self._shutdown = False
            self._handler_task = asyncio.create_task(self._handler_loop())
            logger.info("[EXEC_QUEUE_HANDLER] Started")

    async def stop(self) -> None:
        self._shutdown = True
        if self._handler_task:
            self._handler_task.cancel()
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass
            self._handler_task = None
        logger.info("[EXEC_QUEUE_HANDLER] Stopped")

    async def _handler_loop(self) -> None:
        while not self._shutdown:
            try:
                entry = self._queue.get_next_for_execution(timeout_seconds=self._poll_interval)
                if entry:
                    asyncio.create_task(self._execute_entry(entry))
            except Exception as e:
                logger.error("[EXEC_QUEUE_HANDLER] Loop error: %s", e)
                await asyncio.sleep(1.0)

    async def _execute_entry(self, entry: ExecutionQueueEntry) -> None:
        async with self._semaphore:
            entry_id = entry.entry_id
            ticker = entry.ticker

            with self._lock:
                self._active_entries[entry_id] = entry

            logger.info(
                "[EXEC_QUEUE_HANDLER] EXECUTING entry=%s ticker=%s agent=%s",
                entry_id, ticker, entry.agent_id
            )

            try:
                self._orders_submitted += 1
                # Integrate with order router
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                
                # Build order intent from queue entry
                intent = OrderIntent(
                    ticker=ticker,
                    side=entry.side,
                    action="buy" if entry.side.lower() in ("yes", "buy", "long") else "sell",
                    price_cents=entry.limit_price_cents if hasattr(entry, 'limit_price_cents') else 0,
                    count=entry.size_contracts,
                    order_type="limit" if hasattr(entry, 'limit_price_cents') and entry.limit_price_cents > 0 else "market",
                    time_in_force="gtc",
                    source=f"execution_queue_handler:{entry.agent_id}",
                    agent_id=entry.agent_id,
                )
                
                # Route order asynchronously
                result = await route_order_async(intent)
                success = result.success if result else False

                if success:
                    self._orders_accepted += 1
                    self._queue.mark_executed(entry_id, ticker, success=True)
                else:
                    self._orders_rejected += 1
                    self._queue.mark_executed(entry_id, ticker, success=False)

            except Exception as e:
                logger.exception("[EXEC_QUEUE_HANDLER] Execution failed: %s", e)
                self._queue.mark_executed(entry_id, ticker, success=False)

            finally:
                with self._lock:
                    self._active_entries.pop(entry_id, None)

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "submitted": self._orders_submitted,
            "accepted": self._orders_accepted,
            "rejected": self._orders_rejected,
            "active": len(self._active_entries),
        }


# Global singleton
_handler: Optional[ExecutionQueueHandler] = None
_handler_lock = threading.Lock()


def get_execution_queue_handler(
    poll_interval_seconds: float = 0.1,
    max_concurrent: int = 5,
) -> ExecutionQueueHandler:
    global _handler
    with _handler_lock:
        if _handler is None:
            _handler = ExecutionQueueHandler(
                poll_interval_seconds=poll_interval_seconds,
                max_concurrent=max_concurrent,
            )
        return _handler
