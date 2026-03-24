"""
Task supervision utilities for MERID runtime

Provides:
1. Task supervision with error handling and telemetry
2. Shutdown timeout wrappers
3. Task registry for tracking background tasks
"""

import asyncio
import time
from typing import List, Callable, Awaitable, Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Global task registry
_background_tasks: List[asyncio.Task] = []


def register_task(task: asyncio.Task, name: Optional[str] = None) -> asyncio.Task:
    """
    Register a background task for supervision

    Args:
        task: The asyncio.Task to register
        name: Optional name for the task (used in logging)

    Returns:
        The same task (for chaining)
    """
    if name and task.get_name() == "":
        task.set_name(name)

    _background_tasks.append(task)
    logger.debug(f"Registered task: {task.get_name() or '<unnamed>'}")
    return task


def get_background_tasks() -> List[asyncio.Task]:
    """Get list of all registered background tasks"""
    return _background_tasks.copy()


def supervised_task(name: str):
    """
    Decorator that adds error handling and telemetry to background tasks

    Usage:
        @supervised_task("price-feed")
        async def price_feed_loop():
            while True:
                # ...
    """
    def decorator(coro_func: Callable[..., Awaitable]):
        async def wrapper(*args, **kwargs):
            try:
                logger.info(f"Task {name} starting...")
                return await coro_func(*args, **kwargs)
            except asyncio.CancelledError:
                logger.info(f"Task {name} cancelled")
                raise
            except Exception as exc:
                logger.error(f"Task {name} failed with exception", exc_info=exc)
                # Send alert if alert manager available
                try:
                    from core.alerts import get_alert_manager
                    alert_mgr = get_alert_manager()
                    await alert_mgr.send_alert(
                        level="critical",
                        title=f"Background task {name} failed",
                        message=str(exc)
                    )
                except Exception:
                    pass  # Alert failed, nothing we can do
                raise
        wrapper.__name__ = coro_func.__name__
        wrapper.__doc__ = coro_func.__doc__
        return wrapper
    return decorator


async def shutdown_with_timeout(
    coro: Awaitable,
    timeout: float = 10.0,
    component_name: str = "component"
) -> bool:
    """
    Execute a shutdown coroutine with timeout

    Args:
        coro: The coroutine to execute (e.g., component.stop())
        timeout: Maximum seconds to wait
        component_name: Name of component (for logging)

    Returns:
        True if shutdown completed, False if timed out
    """
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.error(f"{component_name}.stop() timed out after {timeout}s")
        return False
    except asyncio.CancelledError:
        logger.warning(f"{component_name}.stop() was cancelled")
        return False
    except Exception as exc:
        logger.error(f"{component_name}.stop() failed: {exc}", exc_info=True)
        return False


async def cancel_all_tasks(
    tasks: Optional[List[asyncio.Task]] = None,
    timeout: float = 5.0
) -> tuple[int, int]:
    """
    Cancel all tasks with timeout

    Args:
        tasks: List of tasks to cancel (or None for all registered tasks)
        timeout: Seconds to wait for cancellation

    Returns:
        Tuple of (cancelled_count, timeout_count)
    """
    if tasks is None:
        tasks = _background_tasks

    if not tasks:
        return (0, 0)

    # Cancel all
    for task in tasks:
        if not task.done():
            task.cancel()

    # Wait for cancellation with timeout
    start = time.time()
    cancelled = 0
    timed_out = 0

    for task in tasks:
        if task.done():
            cancelled += 1
            continue

        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            logger.warning(f"Task {task.get_name()} did not cancel (timeout)")
            timed_out += 1
            continue

        try:
            await asyncio.wait_for(task, timeout=remaining)
            cancelled += 1
        except (asyncio.CancelledError, asyncio.TimeoutError):
            # Expected for cancelled tasks
            cancelled += 1
        except Exception as exc:
            logger.debug(f"Task {task.get_name()} cancellation error: {exc}")
            cancelled += 1

    return (cancelled, timed_out)


class TaskManager:
    """
    Central task supervision manager

    Tracks all background tasks, provides health reporting,
    and handles graceful shutdown.
    """

    def __init__(self):
        self._tasks: List[asyncio.Task] = []
        self._task_start_times: dict[asyncio.Task, float] = {}
        self._task_errors: dict[str, int] = {}

    def create_task(
        self,
        coro: Awaitable,
        name: str
    ) -> asyncio.Task:
        """
        Create and register a supervised task

        Args:
            coro: Coroutine to run
            name: Task name

        Returns:
            The created task
        """
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)
        self._task_start_times[task] = time.time()

        # Add done callback for error tracking
        def on_done(t: asyncio.Task):
            try:
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        self._task_errors[name] = self._task_errors.get(name, 0) + 1
                        logger.error(f"Task {name} failed: {exc}", exc_info=exc)
            except Exception as e:
                logger.debug(f"Error in task done callback: {e}")

        task.add_done_callback(on_done)
        logger.debug(f"TaskManager: Created task {name}")
        return task

    def get_status(self) -> dict:
        """Get status of all tasks"""
        active = sum(1 for t in self._tasks if not t.done())
        failed = sum(1 for t in self._tasks if t.done() and not t.cancelled() and t.exception())
        cancelled = sum(1 for t in self._tasks if t.cancelled())

        return {
            "total": len(self._tasks),
            "active": active,
            "failed": failed,
            "cancelled": cancelled,
            "errors_by_task": dict(self._task_errors),
        }

    async def shutdown(self, timeout: float = 10.0) -> bool:
        """
        Gracefully shutdown all tasks

        Args:
            timeout: Maximum seconds to wait for all tasks

        Returns:
            True if all tasks stopped cleanly
        """
        logger.info(f"TaskManager: Shutting down {len(self._tasks)} tasks...")
        cancelled, timed_out = await cancel_all_tasks(self._tasks, timeout=timeout)
        logger.info(f"TaskManager: {cancelled} tasks stopped, {timed_out} timed out")
        return timed_out == 0


# Global task manager singleton
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get the global task manager singleton"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
