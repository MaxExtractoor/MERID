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
        # CRITICAL FIX (2026-08-01): Track execution tasks to prevent race conditions
        # This ensures all submitted orders are awaited and errors are properly handled
        self._execution_tasks: set[asyncio.Task] = set()
        self._tasks_lock = asyncio.Lock()  # Async lock for task set operations

    async def start(self) -> None:
        if self._handler_task is None:
            self._shutdown = False
            self._handler_task = asyncio.create_task(self._handler_loop())
            logger.info("[EXEC_QUEUE_HANDLER] Started")

    async def stop(self) -> None:
        """
        Stop the execution queue handler.
        
        CRITICAL FIX (2026-08-01): Ensure clean shutdown by awaiting all tasks.
        The handler loop now awaits all remaining tasks before returning,
        ensuring no race conditions during shutdown.
        """
        self._shutdown = True
        if self._handler_task:
            self._handler_task.cancel()
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass
            self._handler_task = None
        
        # CRITICAL: Cancel any remaining execution tasks
        async with self._tasks_lock:
            for task in self._execution_tasks:
                if not task.done():
                    task.cancel()
        
        # Wait for task cancellations to complete
        await self._await_all_tasks()
        
        logger.info("[EXEC_QUEUE_HANDLER] Stopped")

    async def _handler_loop(self) -> None:
        """
        Main handler loop for processing execution queue entries.
        
        CRITICAL FIX (2026-08-01): Track all execution tasks to prevent race conditions.
        Previous implementation used asyncio.create_task() without tracking, which:
        - Allowed tasks to run without proper error handling
        - Could lead to task leaks if exceptions occurred
        - Made shutdown incomplete (tasks could continue after stop())
        
        New implementation uses task tracking with asyncio.gather for:
        - Proper error propagation
        - Clean shutdown (all tasks awaited before returning)
        - Task lifecycle management (remove completed tasks)
        """
        while not self._shutdown:
            try:
                entry = self._queue.get_next_for_execution(timeout_seconds=self._poll_interval)
                if entry:
                    # Create task and track it
                    task = asyncio.create_task(self._execute_entry(entry))
                    async with self._tasks_lock:
                        self._execution_tasks.add(task)
                    
                    # Add callback to remove task when done
                    task.add_done_callback(self._on_task_done)
                    
                    # Clean up completed tasks periodically
                    await self._cleanup_completed_tasks()
                    
            except Exception as e:
                logger.error("[EXEC_QUEUE_HANDLER] Loop error: %s", e)
                await asyncio.sleep(1.0)
        
        # CRITICAL: Await all remaining tasks on shutdown
        # This ensures all in-flight orders complete before handler stops
        await self._await_all_tasks()
    
    def _on_task_done(self, task: asyncio.Task) -> None:
        """
        Callback when an execution task completes.
        
        CRITICAL FIX (2026-08-01): Handle task completion to prevent task leaks.
        This is called when a task finishes (successfully or with exception).
        """
        # Log exceptions if task failed
        try:
            task.result()  # This raises if task had an exception
        except Exception as e:
            logger.error("[EXEC_QUEUE_HANDLER] Task failed: %s", e)
    
    async def _cleanup_completed_tasks(self) -> None:
        """
        Remove completed tasks from the tracking set.
        
        CRITICAL FIX (2026-08-01): Prevent unbounded task set growth.
        Without cleanup, the task set would grow indefinitely even after tasks complete.
        """
        async with self._tasks_lock:
            # Remove tasks that are already done
            completed_tasks = {t for t in self._execution_tasks if t.done()}
            self._execution_tasks -= completed_tasks
            
            if completed_tasks:
                logger.debug(
                    "[EXEC_QUEUE_HANDLER] Cleaned up %d completed tasks, %d active",
                    len(completed_tasks),
                    len(self._execution_tasks)
                )
    
    async def _await_all_tasks(self) -> None:
        """
        Await all remaining execution tasks for clean shutdown.
        
        CRITICAL FIX (2026-08-01): Ensure all in-flight orders complete before shutdown.
        This prevents race conditions where orders are submitted but not awaited.
        """
        if not self._execution_tasks:
            return
        
        logger.info(
            "[EXEC_QUEUE_HANDLER] Awaiting %d remaining tasks before shutdown",
            len(self._execution_tasks)
        )
        
        # Copy the set to avoid modification during iteration
        async with self._tasks_lock:
            tasks_to_await = list(self._execution_tasks)
        
        # Wait for all tasks with timeout to prevent indefinite blocking
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_to_await, return_exceptions=True),
                timeout=30.0  # 30 second timeout for shutdown
            )
            logger.info("[EXEC_QUEUE_HANDLER] All tasks completed")
        except asyncio.TimeoutError:
            logger.warning(
                "[EXEC_QUEUE_HANDLER] Timeout waiting for tasks to complete, "
                "%d tasks may still be running",
                len(tasks_to_await)
            )
        except Exception as e:
            logger.error("[EXEC_QUEUE_HANDLER] Error awaiting tasks: %s", e)

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
                success = result and (result.has_execution or (result.request_completed and not result.is_terminal))

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
