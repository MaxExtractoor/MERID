from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional


class BackgroundQueue:
    """Simple background queue that runs callables in a thread pool and
    provides a coroutine-friendly submit API.

    This is intentionally small and well-tested. For production you may want
    to replace it with a full-featured queue (Redis/RQ, Celery, Dramatiq,
    or an async task runner).
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: set[asyncio.Future] = set()
        self._closed = False

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    def submit_sync(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> asyncio.Future:
        """Submit a synchronous callable to run in a thread pool and return an
        awaitable future. Instruments metrics for counting and duration.
        """
        if self._closed:
            raise RuntimeError("BackgroundQueue is closed")
        if self._loop is None:
            # allow submit_sync outside of start for convenience in tests
            loop = asyncio.get_event_loop()
        else:
            loop = self._loop

        # Wrap the function to measure execution time and emit metrics
        from time import perf_counter
        try:
            from web.metrics import metrics
        except Exception:
            metrics = None

        def _wrapped() -> Any:
            if metrics:
                metrics.inc("background_tasks_submitted")
            start = perf_counter()
            res = func(*args, **kwargs)
            elapsed = perf_counter() - start
            if metrics:
                metrics.observe("background_task_duration_seconds", elapsed)
                metrics.inc("background_tasks_completed")
            return res

        fut = loop.run_in_executor(self._executor, _wrapped)
        pending_future = asyncio.ensure_future(fut)
        self._pending.add(pending_future)

        # remove from pending when done
        def _on_done(_f: asyncio.Future) -> None:
            self._pending.discard(_f)
            if metrics:
                metrics.set_gauge("background_tasks_pending", float(len(self._pending)))

        pending_future.add_done_callback(_on_done)
        if metrics:
            metrics.set_gauge("background_tasks_pending", float(len(self._pending)))
        return fut

    def submit_coro(self, coro: "asyncio.Future | asyncio.Task | Callable[..., Any]") -> asyncio.Task:
        """Schedule an async coroutine on the event loop and return the Task."""
        if self._closed:
            raise RuntimeError("BackgroundQueue is closed")
        if self._loop is None:
            loop = asyncio.get_event_loop()
        else:
            loop = self._loop
        task = loop.create_task(coro)
        self._pending.add(task)

        def _on_done(_t: asyncio.Task) -> None:
            self._pending.discard(_t)

        task.add_done_callback(_on_done)
        return task

    async def stop(self, timeout: float | None = None) -> None:
        """Gracefully wait for pending tasks and shutdown the executor."""
        self._closed = True
        if not self._pending:
            self._executor.shutdown(wait=False)
            return

        # Wait for all pending tasks to finish or timeout
        await asyncio.wait(self._pending, timeout=timeout)
        self._executor.shutdown(wait=False)
        self._pending.clear()

    def __enter__(self) -> "BackgroundQueue":
        raise RuntimeError("BackgroundQueue should be used with async start/stop")

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - defensive
        pass
