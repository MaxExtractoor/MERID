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
from core.fault_manager import get_fault_manager

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

    # These Windows errors are often benign during WebSocket close/reconnect
    WINDOWS_BENIGN_ERRORS = (
        "WinError 995",           # ERROR_OPERATION_ABORTED - expected during close
        "WinError 10054",         # WSAECONNRESET - connection reset during close
    )

    # These are genuinely fatal Windows errors
    WINDOWS_FATAL_ERRORS = (
        "WinError 10038",         # WSAENOTSOCK - socket operation on non-socket
        "WinError 10060",         # WSAETIMEDOUT - connection timed out
    )

    ASGI_LOOP_ERRORS = (
        "InvalidStateError",      # asyncio invalid state
        "CancelledError",         # Task cancellation
        "asyncio.CancelledError",
    )

    @classmethod
    def is_benign_ws_error(cls, exc: BaseException) -> bool:
        """Check if exception is a benign WebSocket/Windows error.

        These errors are expected during forced WebSocket close or process shutdown
        and should not trigger fatal error handling or server shutdown.

        NOTE: This is the classmethod version used by ASGI fatal error classification.
        A similar instance method exists in KalshiWebSocket._is_benign_ws_error()
        for WebSocket-level error handling. Keep logic aligned between both.
        """
        import errno

        # CancelledError is always benign
        if isinstance(exc, asyncio.CancelledError):
            return True

        # Connection errors during close are benign
        if isinstance(exc, (ConnectionError, ConnectionAbortedError, ConnectionResetError)):
            return True

        # OSError with specific Windows error codes
        if isinstance(exc, OSError):
            winerror = getattr(exc, "winerror", None)
            if winerror in (995, 10054):  # ERROR_OPERATION_ABORTED, WSAECONNRESET
                return True
            errno_code = getattr(exc, "errno", None)
            if errno_code in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE, 104, 10053, 10058):
                return True

        # RuntimeError with specific closed/transport messages
        if isinstance(exc, RuntimeError):
            msg = str(exc).lower()
            if any(x in msg for x in ["websocket", "connection", "closed", "transport"]):
                return True

        # Check string representation for known benign patterns
        exc_str = str(exc)
        if any(code in exc_str for code in cls.WINDOWS_BENIGN_ERRORS):
            return True

        return False

    @classmethod
    def classify(cls, exc: BaseException) -> ShutdownReason:
        """Classify an exception into a shutdown reason.

        Benign WebSocket close errors are downgraded to UNKNOWN to prevent
        unnecessary server shutdown while still capturing them in logs.
        """
        exc_type = type(exc).__name__
        exc_str = str(exc)

        # First check if this is a benign WebSocket close error
        if cls.is_benign_ws_error(exc):
            logger.debug(
                "FatalErrorClassifier: Downgrading %s to benign (WebSocket close)",
                exc_type,
            )
            return ShutdownReason.UNKNOWN

        # Windows I/O fatal errors (excluding benign ones)
        # Check both string representation and winerror attribute
        if any(code in exc_str for code in cls.WINDOWS_FATAL_ERRORS):
            return ShutdownReason.ASGI_FATAL
        if isinstance(exc, OSError):
            winerror = getattr(exc, "winerror", None)
            if winerror in (10038, 10060):  # WSAENOTSOCK, WSAETIMEDOUT
                return ShutdownReason.ASGI_FATAL

        # asyncio loop corruption
        if exc_type in cls.ASGI_LOOP_ERRORS:
            return ShutdownReason.ASGI_FATAL

        # Connection/transport errors that indicate loop corruption
        if "transport" in exc_str.lower() and "closed" in exc_str.lower():
            # But not if it looks like a benign WebSocket close
            if not cls.is_benign_ws_error(exc):
                return ShutdownReason.ASGI_FATAL

        return ShutdownReason.UNKNOWN


class MERIDUvicornServer(uvicorn.Server):
    """Custom uvicorn server with fatal error capture."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fatal_error: Optional[BaseException] = None
        self._shutdown_reason: Optional[ShutdownReason] = None

    async def shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        """Override shutdown to capture attribution before calling parent.
        
        DEGRADED-MODE: Only proceed with shutdown if FaultManager
        determines multi-signal critical conditions are met.
        """
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

        # DEGRADED-MODE: Check with FaultManager before allowing shutdown
        if reason == ShutdownReason.ASGI_FATAL and self._fatal_error:
            fm = get_fault_manager()
            # Get lag metrics for decision
            try:
                from merid.diagnostics.loop_lag import get_loop_lag_monitor
                lag_stats = get_loop_lag_monitor().get_health()
                lag_ms = lag_stats["stats"]["current_ms"]
                lag_p95 = lag_stats["stats"]["p95_ms"]
            except Exception:
                lag_ms = 0.0
                lag_p95 = 0.0
            
            # Ask FaultManager if we should shutdown
            should_shutdown = fm.should_initiate_shutdown(lag_ms, lag_p95)
            if not should_shutdown:
                logger.warning(
                    "[SHUTDOWN-BLOCKED] ASGI_FATAL detected but FaultManager "
                    "determined shutdown should not proceed. "
                    "Venue degradation applied instead. Continuing operation."
                )
                # Reset fatal error so we don't keep trying to shutdown
                self._fatal_error = None
                return  # Don't shutdown - continue running

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
        """Handle event loop exceptions - capture fatal errors.
        
        DEGRADED-MODE: Venue-specific ASGI_FATAL errors degrade the venue,
        not the entire system. Global shutdown only occurs for multi-signal
        critical failures determined by FaultManager.
        """
        exc = context.get("exception")
        message = context.get("message", "")

        if exc:
            # Classify the error
            reason = FatalErrorClassifier.classify(exc)
            exc_type = type(exc).__name__

            # Log with context
            logger.error(
                "ASGI_EXCEPTION reason=%s exc_type=%s message=%s",
                reason.value,
                exc_type,
                message,
                exc_info=exc if reason == ShutdownReason.ASGI_FATAL else None,
            )

            # Store fatal errors for attribution in shutdown
            if reason == ShutdownReason.ASGI_FATAL:
                # DEGRADED-MODE: Check if this is a venue-specific error
                # (e.g., Kalshi WebSocket errors) - degrade venue, not system
                is_venue_error = self._is_venue_specific_error(exc, message)
                
                if is_venue_error:
                    # Mark venue as degraded via FaultManager
                    fm = get_fault_manager()
                    venue = self._extract_venue_from_error(exc, message)
                    fm.mark_venue_degraded(
                        venue, 
                        f"asgi_fatal: {exc_type}",
                        metrics={"error_message": str(exc)[:200]}
                    )
                    logger.warning(
                        "[VENUE-DEGRADED] venue=%s due to ASGI_FATAL. "
                        "Server continues running in degraded mode.",
                        venue
                    )
                else:
                    # System-wide fatal error - store for shutdown decision
                    self._fatal_error = exc
                    # Increment metrics counter
                    try:
                        from monitoring.metrics import MERID_ASGI_FATAL_ERRORS_TOTAL
                        MERID_ASGI_FATAL_ERRORS_TOTAL.labels(
                            error_type=exc_type,
                            source="asgi",
                        ).inc()
                    except Exception:
                        pass

        # Call default handler
        super().handle_exception(loop, context)
    
    def _is_venue_specific_error(self, exc: BaseException, message: str) -> bool:
        """Check if an error is specific to a venue (not system-wide).
        
        Venue-specific errors:
        - WebSocket connection errors to external venues
        - Venue-specific timeouts or resets
        
        System-wide errors:
        - asyncio loop corruption
        - Memory exhaustion
        - Port binding failures
        """
        exc_str = str(exc).lower()
        exc_type = type(exc).__name__
        
        # Check for Kalshi/WebSocket specific patterns
        venue_patterns = [
            "kalshi",
            "websocket",
            "ws.close",
            "wss://",
            "connection reset",
            "connection refused",
            "winerror 10054",  # WSAECONNRESET - benign during close
            "winerror 10060",  # WSAETIMEDOUT - venue timeout
        ]
        
        for pattern in venue_patterns:
            if pattern in exc_str or pattern in message.lower():
                return True
        
        # Check for venue-specific error types
        if exc_type in ("ConnectionError", "ConnectionResetError"):
            return True
        
        # Check winerror codes that are venue-specific
        if isinstance(exc, OSError):
            winerror = getattr(exc, "winerror", None)
            if winerror in (10054, 10060):  # WSAECONNRESET, WSAETIMEDOUT
                return True
        
        return False
    
    def _extract_venue_from_error(self, exc: BaseException, message: str) -> str:
        """Extract venue name from error message/content."""
        exc_str = str(exc).lower()
        msg_lower = message.lower()
        
        if "kalshi" in exc_str or "kalshi" in msg_lower:
            return "kalshi"
        
        # Default venue for WebSocket errors
        if "websocket" in exc_str or "websocket" in msg_lower:
            return "kalshi"  # Primary WebSocket venue
        
        return "unknown"


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
