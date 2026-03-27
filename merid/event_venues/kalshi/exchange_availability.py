"""Kalshi Exchange Availability — venue maintenance window guard.

Prevents orders from being sent during scheduled or detected Kalshi exchange
maintenance windows.

Usage::

    from merid.event_venues.kalshi.exchange_availability import (
        KalshiExchangeAvailability,
        get_exchange_availability,
    )

    avail = get_exchange_availability()
    if not avail.trading_open_now():
        raise VenueUnavailableError("Kalshi venue is not available for trading")
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.exchange_availability")


class VenueUnavailableError(RuntimeError):
    """Raised when an order is attempted during a venue maintenance window."""


class KalshiExchangeAvailability:
    """Tracks Kalshi exchange availability and maintenance windows.

    In the absence of a live status endpoint, availability defaults to *open*
    unless explicitly overridden via ``set_maintenance_mode()``.  The
    ``MERID_KALSHI_MAINTENANCE`` environment variable can force maintenance mode
    at startup (``"1"`` or ``"true"`` = maintenance).

    Attributes
    ----------
    _maintenance : bool
        True when the venue is in maintenance and orders must be blocked.
    _reason : str | None
        Human-readable reason for the current maintenance window.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        _env = os.getenv("MERID_KALSHI_MAINTENANCE", "").strip().lower()
        self._maintenance: bool = _env in {"1", "true", "yes"}
        self._reason: Optional[str] = (
            "MERID_KALSHI_MAINTENANCE env forced" if self._maintenance else None
        )
        self._updated_at: float = time.time()

    # ── Public API ──────────────────────────────────────────────────────────

    def trading_open_now(self) -> bool:
        """Return ``True`` iff the Kalshi venue is currently open for trading.

        Thread-safe; safe to call from async contexts.
        """
        with self._lock:
            return not self._maintenance

    def set_maintenance_mode(self, active: bool, reason: str = "") -> None:
        """Programmatically set maintenance mode.

        Parameters
        ----------
        active:
            ``True`` to enter maintenance (block orders); ``False`` to resume.
        reason:
            Optional human-readable reason string for logging / observability.
        """
        with self._lock:
            prev = self._maintenance
            self._maintenance = active
            self._reason = reason or None
            self._updated_at = time.time()

        if active and not prev:
            logger.warning(
                "[exchange-availability] Kalshi venue entered MAINTENANCE: %s",
                reason or "(no reason given)",
            )
        elif not active and prev:
            logger.info(
                "[exchange-availability] Kalshi venue resumed TRADING: %s",
                reason or "(no reason given)",
            )

    def summary(self) -> dict:
        """Return a dict snapshot suitable for health / observability endpoints."""
        with self._lock:
            return {
                "trading_open": not self._maintenance,
                "maintenance": self._maintenance,
                "reason": self._reason,
                "updated_at": datetime.fromtimestamp(
                    self._updated_at, tz=timezone.utc
                ).isoformat(),
            }


# ── Module-level singleton ──────────────────────────────────────────────────

_exchange_availability: Optional[KalshiExchangeAvailability] = None
_singleton_lock = threading.Lock()


def get_exchange_availability() -> KalshiExchangeAvailability:
    """Return the module-level KalshiExchangeAvailability singleton."""
    global _exchange_availability
    if _exchange_availability is None:
        with _singleton_lock:
            if _exchange_availability is None:
                _exchange_availability = KalshiExchangeAvailability()
    return _exchange_availability
