"""Global Telegram circuit breaker — shared across all send paths.

When Telegram returns HTTP 429 (flood control) or the ``python-telegram-bot``
library raises ``RetryAfter``, *any* sender should call ``trip(seconds)`` to
lock out **all** Telegram sends for the requested duration.

Every send path should call ``is_open()`` before attempting an HTTP call.
If it returns ``True``, the caller must skip the send silently.

Thread-safe and process-global (module-level state).
"""

from __future__ import annotations

import threading
import time

from utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_blocked_until: float = 0.0  # monotonic time


def trip(seconds: float, source: str = "unknown") -> None:
    """Trip the breaker — block all TG sends for *seconds*."""
    global _blocked_until
    with _lock:
        new_deadline = time.monotonic() + seconds
        if new_deadline > _blocked_until:
            _blocked_until = new_deadline
            logger.warning(
                "TG circuit breaker TRIPPED by %s — all sends blocked for %.0fs",
                source, seconds,
            )


def is_open() -> bool:
    """Return ``True`` if the breaker is open (sends should be skipped)."""
    return time.monotonic() < _blocked_until


def remaining_seconds() -> float:
    """Seconds until the breaker closes (0 if already closed)."""
    return max(0.0, _blocked_until - time.monotonic())


def reset() -> None:
    """Manually close the breaker (e.g. after operator intervention)."""
    global _blocked_until
    with _lock:
        _blocked_until = 0.0
        logger.info("TG circuit breaker manually RESET")
