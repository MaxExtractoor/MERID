"""
ASGI fatal error guard for MERID.
Wraps uvicorn to capture fatal loop errors and initiate graceful shutdown with attribution.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import uvicorn
from utils.logger import get_logger

logger = get_logger("web.asgi_guard")


class ShutdownReason(Enum):
    """Canonical shutdown reasons for MERID."""
    USER_REQUEST = "user_request"          # SIGTERM from operator/system
    SIGINT = "sigint"                      # Ctrl-C
    ASGI_FATAL = "asgi_fatal"              # Unrecoverable ASGI/loop error
    HEALTH_LOOP_LAG = "health_loop_lag"    # Loop-lag monitor halt
    VENUE_FATAL = "venue_fatal"            # All venue connections lost
    KILLSWITCH_LIMIT = "killswitch_limit"  # 50/h error threshold
    MEMORY_PRESSURE = "memory_pressure"    # OOM conditions
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ShutdownEvent:
    """Structured shutdown event for logging and metrics."""
    reason: ShutdownReason
    sub_reason: Optional[str] = None  # Exception type, specific trigger
    initiator_module: str = "asgi_guard"
    stack_summary: Optional[str] = None
    fatal_error_type: Optional[str] = None
    fatal_error_message: Optional[str] = None

    def to_log_line(self) -> str:
        parts = [
            f"shutdown_reason={self.reason.value}",
            f"initiator={self.initiator_module}",
        ]
        if self.sub_reason:
            parts.append(f"sub_reason={self.sub_reason}")
        if self.fatal_error_type:
            parts.append(f"fatal_error_type={self.fatal_error_type}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shutdown_reason": self.reason.value,
            "sub_reason": self.sub_reason,
            "initiator_module": self.initiator_module,
            "fatal_error_type": self.fatal_error_type,
            "fatal_error_message": self.fatal_error_message,
            "stack_summary": self.stack_summary,
        }


# Global state for shutdown attribution (set before signaling)
_current_shutdown: Optional[ShutdownEvent] = None
_shutdown_lock = threading.Lock()


def get_shutdown_reason() -> Optional[ShutdownEvent]:
    """Get the current shutdown reason if shutdown is in progress."""
    return _current_shutdown


def set_shutdown_reason(event: ShutdownEvent) -> None:
    """Set the shutdown reason atomically."""
    global _current_shutdown
    with _shutdown_lock:
        _current_shutdown = event


def is_shutting_down() -> bool:
    """Check if shutdown has been initiated."""
    return _current_shutdown is not None


class FatalErrorClassifier:
    """Classifies exceptions into shutdown reasons."""

    WINDOWS_FATAL_ERRORS = (
        "WinError 995",           # I/O operation aborted
        "WinError 10038",         # Socket operation on non-socket
        "WinError 10054",         # Connection reset by peer
        "WinError 10060",         # Connection timed out
    )

    ASGI_LOOP_ERRORS = (
        "InvalidStateError",      # asyncio invalid state
        "CancelledError",         # Task cancellation
        "asyncio.CancelledError",
    )

    @classmethod
    def classify(cls, exc: BaseException) -> ShutdownReason:
        """Classify an exception into a shutdown reason."""
        exc_type = type(exc).__name__
        exc_str = str(exc)

        # Windows I/O fatal errors
        if any(code in exc_str for code in cls.WINDOWS_FATAL_ERRORS):
            return ShutdownReason.ASGI_FATAL

        # asyncio loop corruption
        if exc_type in cls.ASGI_LOOP_ERRORS:
            return ShutdownReason.ASGI_FATAL

        # Connection/transport errors that indicate loop corruption
        if "transport" in exc_str.lower() and "closed" in exc_str.lower():
            return ShutdownReason.ASGI_FATAL

        return ShutdownReason.UNKNOWN


class MERIDUvicornServer(uvicorn.Server):
    """Custom uvicorn server with fatal error capture."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fatal_error: Optional[BaseException] = None
        self._shutdown_reason: Optional[ShutdownReason] = None

    async def shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        """Override shutdown to capture attribution before calling parent."""
        # Determine reason before shutdown starts
        if sig == signal.SIGINT:
            reason = ShutdownReason.SIGINT
            sub_reason = "ctrl_c"
        elif sig == signal.SIGTERM:
            reason = ShutdownReason.USER_REQUEST
            sub_reason = "sigterm"
        elif self._fatal_error:
            reason = FatalErrorClassifier.classify(self._fatal_error)
            sub_reason = type(self._fatal_error).__name__
        else:
            reason = ShutdownReason.UNKNOWN
            sub_reason = None

        # Build structured event
        event = ShutdownEvent(
            reason=reason,
            sub_reason=sub_reason,
            initiator_module="asgi_guard",
            fatal_error_type=type(self._fatal_error).__name__ if self._fatal_error else None,
            fatal_error_message=str(self._fatal_error) if self._fatal_error else None,
            stack_summary=traceback.format_exc(limit=5) if self._fatal_error else None,
        )

        # Log structured shutdown
        logger.critical("SHUTDOWN_INITIATED %s", event.to_log_line())
        set_shutdown_reason(event)

        # Call parent shutdown
        await super().shutdown(sig=sig)

    def handle_exception(self, loop: asyncio.AbstractEventLoop, context: dict) -> None:
        """Handle event loop exceptions - capture fatal errors."""
        exc = context.get("exception")
        message = context.get("message", "")

        if exc:
            # Classify the error
            reason = FatalErrorClassifier.classify(exc)

            # Log with context
            logger.error(
                "ASGI_EXCEPTION reason=%s exc_type=%s message=%s",
                reason.value,
                type(exc).__name__,
                message,
                exc_info=exc if reason == ShutdownReason.ASGI_FATAL else None,
            )

            # Store fatal errors for attribution in shutdown
            if reason == ShutdownReason.ASGI_FATAL:
                self._fatal_error = exc

                # Increment metrics counter
                try:
                    from monitoring.metrics import MERID_ASGI_FATAL_ERRORS_TOTAL
                    MERID_ASGI_FATAL_ERRORS_TOTAL.labels(
                        error_type=type(exc).__name__,
                        source="asgi",
                    ).inc()
                except Exception:
                    pass

        # Call default handler
        super().handle_exception(loop, context)


def run_merid_guarded(
    app: str,
    host: str = "0.0.0.0",
    port: int = 8000,
    **kwargs,
) -> None:
    """
    Run uvicorn with MERID fatal error guarding.

    This is the production entrypoint - use instead of uvicorn.run().
    """
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        **kwargs,
    )

    server = MERIDUvicornServer(config)

    # Install exception handler on the loop
    def install_handler():
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(server.handle_exception)

    # Run with proper signal handling
    try:
        install_handler()
        server.run()
    except KeyboardInterrupt:
        # Normal Ctrl-C - attribution handled in shutdown()
        pass
    except Exception as e:
        # Uncaught fatal - capture and re-raise for process manager
        logger.critical("FATAL_UNCAUGHT %s: %s", type(e).__name__, e, exc_info=True)
        raise


# Integration with lifespan for structured shutdown logging
async def get_lifespan_shutdown_reason() -> Optional[ShutdownEvent]:
    """
    Called from _app_lifespan() to get shutdown attribution.
    Returns None if shutdown is normal (not yet set).
    """
    return get_shutdown_reason()
