"""Main event loop registry for cross-thread coroutine execution.

Worker threads that need to run coroutines on the app's main event loop
must NEVER call ``asyncio.run(coro)`` if the coroutine touches any object
(HTTP session, websocket, async-Lock, asyncio queue, etc.) bound to the
main loop.  Doing so corrupts Windows IOCP state — the proactor for the
new throw-away loop tries to register IOCP handles for sockets/futures
already registered on the main loop, producing spurious

    ConnectionResetError: [WinError 995] The I/O operation has been aborted
    asyncio.exceptions.InvalidStateError: invalid state

errors which can subsequently propagate up into uvicorn's `main_loop` and
cause silent server shutdowns.

Pattern:

    # In web/main.py during startup, after the main loop is created:
    from core.event_loop_registry import register_main_loop
    register_main_loop(loop)

    # In sync adapter code running on a worker thread:
    from core.event_loop_registry import run_on_main_loop
    result = run_on_main_loop(some_coro(), timeout=15)

The helper falls back to a fresh ``asyncio.run`` only when no main loop
is registered (e.g. unit tests).  Production code must always have a
loop registered at startup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Optional

_main_loop: Optional[asyncio.AbstractEventLoop] = None
_logger = logging.getLogger(__name__)


def register_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the application's primary asyncio event loop.

    Called once at process startup before any worker threads run.
    Calling it a second time replaces the registration (useful for
    test resets or hot-reload scenarios).
    """
    global _main_loop
    _main_loop = loop
    _logger.info("[event_loop_registry] Main loop registered: %r", loop)


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the registered main loop, or None if not yet registered."""
    return _main_loop


def clear_main_loop() -> None:
    """Forget the registered main loop (test helper)."""
    global _main_loop
    _main_loop = None


def run_on_main_loop(coro: Awaitable[Any], timeout: float = 15.0) -> Any:
    """Run a coroutine on the registered main loop and block for its result.

    Safe to call from any worker thread.  Raises ``RuntimeError`` if
    called from inside the main loop itself (would deadlock) or if no
    main loop is registered.

    Args:
        coro:    The coroutine to schedule on the main loop.
        timeout: Maximum seconds to wait for completion.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Whatever the coroutine raises.
        RuntimeError: if called from the main loop's own thread, or if
            no main loop is registered.
        concurrent.futures.TimeoutError: if the coroutine doesn't finish
            in `timeout` seconds.
    """
    loop = _main_loop
    if loop is None:
        raise RuntimeError(
            "No main event loop registered. Call register_main_loop() during "
            "application startup before invoking run_on_main_loop()."
        )

    # Detect "called from the main loop itself" — would deadlock the
    # caller forever waiting for its own loop to make progress.
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        raise RuntimeError(
            "run_on_main_loop() called from the main loop's own thread; "
            "use 'await coro' directly instead."
        )

    if not loop.is_running():
        raise RuntimeError(
            "Main loop is registered but not currently running — cannot "
            "schedule coroutine."
        )

    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)
