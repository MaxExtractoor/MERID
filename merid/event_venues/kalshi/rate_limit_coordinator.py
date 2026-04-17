"""Global rate limit coordinator shared across REST/WS clients.

Wraps the per-instance KalshiTokenBucket with a global singleton
that provides unified utilization metrics and WS subscription tracking.

Rate-limit semantics (B1/B2 fix)
---------------------------------
The previous design returned False when a window was full, but ALL callers
ignored the return value — the rate limiter was purely decorative.

The new design uses *async waiting*: ``acquire_ws_permit()`` and
``acquire_rest_permit()`` suspend the caller until a permit is available in
the current (or next) window instead of returning immediately.  This makes
throttling transparent to the caller and guarantees no subscription is
silently dropped because it raced past the window check.

Window semantics: a fixed 1-second tumbling window.  Up to N permits are
granted per window; when the window is full, callers wait until the window
resets (sleeps for the remaining window time) and then compete again under
the lock.  This ensures at most N operations per second without any
external retry logic in callers.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.rate_limit_coordinator")


@dataclass
class RateLimitBudget:
    """Global rate limit budget shared across REST/WS/FIX.

    REST clients have their own per-instance KalshiTokenBucket.
    This coordinator adds:
    - WS subscription rate tracking (5 subscriptions/sec by default)
    - Unified utilization reporting for observability
    - Global budget ceiling for combined REST+WS operations
    """

    max_requests_per_second: int = 10
    max_ws_subscriptions_per_second: int = 5

    def __post_init__(self) -> None:
        self._lock: asyncio.Lock = asyncio.Lock()
        self._window_start: float = time.monotonic()
        self._rest_count: int = 0
        self._ws_count: int = 0
        self._total_rest_acquires: int = 0
        self._total_ws_acquires: int = 0
        # Denials are now rare (callers wait instead of failing) — kept for
        # backwards-compatible metrics only.
        self._rest_denials: int = 0
        self._ws_denials: int = 0

    def _maybe_reset_window(self) -> None:
        """Reset 1-second window if expired. Must be called inside lock."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._rest_count = 0
            self._ws_count = 0

    def _window_remaining(self) -> float:
        """Seconds until the current window expires. Call inside lock."""
        elapsed = time.monotonic() - self._window_start
        return max(0.0, 1.0 - elapsed)

    # ── Public async permit methods ─────────────────────────────────────

    async def acquire_ws_permit(self) -> None:
        """Wait until a WS subscription permit is available, then consume it.

        Never raises; never silently discards — the caller will proceed once
        the rate-limit window has room, even if that means waiting for one or
        more window resets.
        """
        while True:
            async with self._lock:
                self._maybe_reset_window()
                if self._ws_count < self.max_ws_subscriptions_per_second:
                    self._ws_count += 1
                    self._total_ws_acquires += 1
                    return
                # Window is full — compute how long until it resets
                wait = self._window_remaining()
                self._ws_denials += 1
                logger.debug(
                    "WS subscription rate limited: %d/%d in window — "
                    "waiting %.3fs for next window",
                    self._ws_count,
                    self.max_ws_subscriptions_per_second,
                    wait,
                )
            # Release the lock BEFORE sleeping so other callers are not
            # blocked while we wait.
            await asyncio.sleep(max(wait, 0.001))
            # Loop back and try again under the lock.

    async def acquire_rest_permit(self) -> None:
        """Wait until a REST permit is available, then consume it."""
        while True:
            async with self._lock:
                self._maybe_reset_window()
                if self._rest_count < self.max_requests_per_second:
                    self._rest_count += 1
                    self._total_rest_acquires += 1
                    return
                wait = self._window_remaining()
                self._rest_denials += 1
                logger.debug(
                    "REST rate limited by coordinator: %d/%d in window — "
                    "waiting %.3fs for next window",
                    self._rest_count,
                    self.max_requests_per_second,
                    wait,
                )
            await asyncio.sleep(max(wait, 0.001))

    async def acquire_request_permit(self, client_type: str = "rest") -> bool:
        """Backwards-compatible wrapper — now blocks until a permit is granted.

        Previously returned False on overflow; callers ignored the return value.
        This shim preserves the call signature while switching to the correct
        wait-then-proceed semantics.  Always returns True.
        """
        if client_type == "ws":
            await self.acquire_ws_permit()
        else:
            await self.acquire_rest_permit()
        return True

    def get_utilization(self) -> Dict[str, float]:
        """Get current rate limit utilization (0.0–1.0) for observability."""
        # Read without lock — slightly stale is acceptable for metrics
        return {
            "rest_utilization": self._rest_count / max(self.max_requests_per_second, 1),
            "ws_utilization": self._ws_count / max(self.max_ws_subscriptions_per_second, 1),
            "total_rest_acquires": self._total_rest_acquires,
            "total_ws_acquires": self._total_ws_acquires,
            "rest_denials": self._rest_denials,
            "ws_denials": self._ws_denials,
        }


# ── Global singleton ───────────────────────────────────────────────────────

_coordinator: Optional[RateLimitBudget] = None


def get_rate_limit_coordinator() -> RateLimitBudget:
    """Get the global rate limit coordinator singleton."""
    global _coordinator
    if _coordinator is None:
        _coordinator = RateLimitBudget()
    return _coordinator
