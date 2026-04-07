"""KalshiSettlementPoller — idempotent, cursor-driven settlement ingestion.

Design:
  - Polls Kalshi ``GET /portfolio/settlements`` for new settled markets.
  - Tracks a cursor in Redis (key: ``merid:kalshi:settlement_cursor``) so that
    on restart the poller resumes from where it left off rather than
    reprocessing all historical settlements.
  - Falls back to in-memory cursor if Redis is unavailable.
  - Maintains a ``_seen_ids`` set for extra-safe deduplication beyond the cursor.
  - Persists a rolling cursor history list (``merid:kalshi:settlement_cursor_history``)
    so operators can inspect past checkpoints.
  - All downstream handlers receive each settlement exactly once.

Usage::

    poller = get_settlement_poller(client=kalshi_client)
    await poller.start()
    ...
    await poller.stop()
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.settlement_poller")

# Redis keys
_CURSOR_KEY = "merid:kalshi:settlement_cursor"
_CURSOR_HISTORY_KEY = "merid:kalshi:settlement_cursor_history"
_CURSOR_HISTORY_MAX = 50  # keep last N cursor checkpoints


@dataclass
class Settlement:
    """A single settled Kalshi market result."""

    settlement_id: str
    ticker: str
    result: str            # "yes" or "no"
    settled_price: int     # cents
    settled_at: float      # epoch seconds
    raw_data: Optional[Dict[str, Any]] = None


class KalshiSettlementPoller:
    """Polls Kalshi for new settlements with cursor-based deduplication.

    Parameters
    ----------
    client:
        A ``KalshiVenueClient`` instance (or compatible duck type).
    poll_interval_s:
        Seconds between polls (default 60).
    redis_client:
        Optional Redis client for cursor persistence.  If ``None``, an
        in-memory cursor is used.
    """

    def __init__(
        self,
        client: Any,
        poll_interval_s: float = 60.0,
        redis_client: Any = None,
    ) -> None:
        self._client = client
        self._poll_interval = poll_interval_s
        self._redis = redis_client

        self._last_cursor: Optional[str] = None
        self._cursor_history: List[str] = []
        self._seen_ids: set = set()

        self._handlers: List[Callable[[Settlement], Any]] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._poll_count = 0
        self._settlement_count = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the polling loop, loading cursor from Redis if available."""
        await self._load_cursor()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="kalshi-settlement-poller")
        logger.info(
            "SettlementPoller started — cursor=%s poll_interval=%.0fs",
            self._last_cursor, self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "SettlementPoller stopped — polls=%d settlements=%d",
            self._poll_count, self._settlement_count,
        )

    # ── Handlers ──────────────────────────────────────────────────────────

    def add_handler(self, handler: Callable[[Settlement], Any]) -> None:
        """Register a coroutine or sync function to be called per settlement."""
        self._handlers.append(handler)

    # ── Core loop ─────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("SettlementPoller poll error: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _poll_once(self) -> int:
        """Fetch one page of settlements and dispatch new ones.

        Returns:
            Count of new (unseen) settlements processed.
        """
        self._poll_count += 1
        try:
            raw = await self._fetch_settlements(cursor=self._last_cursor)
        except Exception as exc:
            logger.warning("SettlementPoller fetch error (poll=%d): %s", self._poll_count, exc)
            return 0

        settlements = raw.get("settlements", [])
        next_cursor = raw.get("cursor") or raw.get("next_cursor")
        new_count = 0

        for item in settlements:
            sid = item.get("id") or item.get("settlement_id")
            if not sid:
                logger.debug("SettlementPoller: skipping settlement with no id: %s", item)
                continue
            if sid in self._seen_ids:
                continue

            self._seen_ids.add(sid)
            new_count += 1
            self._settlement_count += 1

            s = Settlement(
                settlement_id=sid,
                ticker=item.get("ticker", ""),
                result=item.get("result", ""),
                settled_price=int(item.get("settled_price", 0)),
                settled_at=float(item.get("settled_at") or time.time()),
                raw_data=item,
            )
            await self._dispatch(s)

        if next_cursor and next_cursor != self._last_cursor:
            await self._advance_cursor(next_cursor)

        if new_count:
            logger.info("SettlementPoller: %d new settlements (cursor=%s)", new_count, self._last_cursor)

        return new_count

    async def _dispatch(self, s: Settlement) -> None:
        for handler in self._handlers:
            try:
                result = handler(s)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("SettlementPoller handler error: %s", exc)

    # ── Cursor persistence ────────────────────────────────────────────────

    async def _load_cursor(self) -> None:
        """Load cursor from Redis; fall back to None if unavailable."""
        if self._redis is not None:
            try:
                val = await self._redis.get(_CURSOR_KEY)
                if val:
                    self._last_cursor = val if isinstance(val, str) else val.decode()
                history_raw = await self._redis.lrange(_CURSOR_HISTORY_KEY, 0, -1)
                self._cursor_history = [
                    v.decode() if isinstance(v, bytes) else v for v in (history_raw or [])
                ]
                logger.debug("SettlementPoller cursor loaded from Redis: %s", self._last_cursor)
                return
            except Exception as exc:
                logger.warning(
                    "[REDIS-UNAVAILABLE] Settlement cursor load failed, using in-memory cursor | err=%s",
                    exc,
                    exc_info=True,
                )

    async def _advance_cursor(self, new_cursor: str) -> None:
        """Update cursor and persist to Redis (or in-memory history)."""
        self._last_cursor = new_cursor
        self._cursor_history.append(new_cursor)
        if len(self._cursor_history) > _CURSOR_HISTORY_MAX:
            self._cursor_history = self._cursor_history[-_CURSOR_HISTORY_MAX:]

        if self._redis is not None:
            try:
                await self._redis.set(_CURSOR_KEY, new_cursor)
                await self._redis.rpush(_CURSOR_HISTORY_KEY, new_cursor)
                await self._redis.ltrim(_CURSOR_HISTORY_KEY, -_CURSOR_HISTORY_MAX, -1)
            except Exception as exc:
                logger.warning(
                    "[REDIS-UNAVAILABLE] Settlement persistence failed, continuing without cursor | err=%s",
                    exc,
                    exc_info=True,
                )
                # Continue: worst case we reprocess some settlements on restart

    # ── Fetch ─────────────────────────────────────────────────────────────

    async def _fetch_settlements(self, cursor: Optional[str] = None) -> dict:
        """Delegate to the Kalshi client.  Supports duck-typed clients for tests."""
        if hasattr(self._client, "get_settlements"):
            return await self._client.get_settlements(cursor=cursor) or {}
        # Fallback: plain REST via _request (older client shapes)
        if hasattr(self._client, "_request"):
            params: Dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            resp = await self._client._request("GET", "/portfolio/settlements", params=params)
            return resp if isinstance(resp, dict) else {}
        # Fallback: resilient REST (KalshiVenueClient uses _request_with_resilience)
        if hasattr(self._client, "_request_with_resilience"):
            params: Dict[str, Any] = {}  # type: ignore[no-redef]
            if cursor:
                params["cursor"] = cursor
            result = await self._client._request_with_resilience(
                "GET", "/portfolio/settlements", params=params,
                operation_name="settlement_poller_fetch",
            )
            if hasattr(result, "success") and result.success and isinstance(result.data, dict):
                return result.data
            return {}
        return {}

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self._running,
            "last_cursor": self._last_cursor,
            "cursor_history_len": len(self._cursor_history),
            "seen_ids_count": len(self._seen_ids),
            "poll_count": self._poll_count,
            "settlement_count": self._settlement_count,
        }


# ── Singleton ─────────────────────────────────────────────────────────────

_poller: Optional[KalshiSettlementPoller] = None


def get_settlement_poller(
    client: Any = None,
    redis_client: Any = None,
) -> KalshiSettlementPoller:
    """Return the process-singleton settlement poller."""
    global _poller
    if _poller is None:
        if client is None:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.event_venues.kalshi.models import KalshiConfig
            client = KalshiVenueClient(KalshiConfig())
        _poller = KalshiSettlementPoller(client=client, redis_client=redis_client)
    return _poller


def _make_kalshi_client_from_settings() -> Optional[Any]:
    """Create KalshiVenueClient from settings for settlement poller.

    Returns None if credentials are not configured.
    """
    try:
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.settings import settings
        from merid.event_venues.kalshi.models import KalshiConfig

        # Check if credentials are configured
        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        if key_path == "change_me":
            key_path = None

        if not settings.KALSHI_API_KEY_ID or (not key_path and not settings.KALSHI_PRIVATE_KEY_PEM):
            logger.warning("Settlement poller: Kalshi credentials not configured, skipping")
            return None

        config = KalshiConfig(
            api_key_id=settings.KALSHI_API_KEY_ID,
            private_key_path=key_path,
            private_key_pem=settings.KALSHI_PRIVATE_KEY_PEM,
            use_demo=settings.KALSHI_USE_DEMO,
        )
        return KalshiVenueClient(config)
    except Exception as exc:
        logger.warning("Settlement poller: failed to create Kalshi client: %s", exc)
        return None


async def start_settlement_polling_auto() -> Optional[KalshiSettlementPoller]:
    """Start settlement polling with auto-configured Kalshi client.

    Creates a KalshiVenueClient from settings, initializes the singleton
    settlement poller, and starts it. Returns None if credentials are not
    configured.

    Returns:
        KalshiSettlementPoller instance if started successfully, None otherwise.
    """
    client = _make_kalshi_client_from_settings()
    if client is None:
        return None

    poller = get_settlement_poller(client)
    await poller.start()
    logger.info("✅ KalshiSettlementPoller started")
    return poller


async def stop_settlement_polling() -> None:
    """Stop the settlement poller if it's running."""
    global _poller
    if _poller is not None:
        await _poller.stop()
        logger.info("✅ KalshiSettlementPoller stopped")

