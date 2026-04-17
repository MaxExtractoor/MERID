"""Background candle poller — fetches OHLCV bars and feeds the state store.

Runs a lightweight async loop that polls ``GET /markets/{ticker}/candlesticks``
for every ticker currently tracked in ``KalshiMarketStateStore`` and stores the
most recent bar via ``store.apply_candle_dict()``.

Design
------
- Polls all tracked tickers once per ``interval_seconds`` (default 60) using
  fixed-rate scheduling that accounts for poll duration.
- Period values are validated against Kalshi's allowed set {1, 60, 1440} minutes
  at initialization to prevent misconfiguration.
- Stores the **last closed candlestick** per market; forming bars are explicitly
  excluded (use orderbook WS for sub-period price moves). Synthetic continuity
  bars from ``include_latest_before_start`` are filtered at the store layer.
- Concurrency is capped at ``max_concurrent`` tasks (default 8) to stay
  well inside Kalshi's rate limits.
- Per-ticker failures (HTTP errors or malformed data) are counted in ``_errors``
  and logged at DEBUG; one bad ticker never stalls the whole loop.
- The poller is started/stopped by the FastAPI lifespan in ``web/main.py``.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Optional

from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

logger = get_logger("merid.event_venues.kalshi.candle_poller")

# Kalshi period_interval is in *minutes* for the REST param.
# We default to 1-minute bars so ``latest_candle`` stays fresh between polls.
_DEFAULT_PERIOD_MINUTES: int = int(os.getenv("MERID_CANDLE_PERIOD_MINUTES", "1"))
_DEFAULT_INTERVAL_SECONDS: float = float(os.getenv("MERID_CANDLE_POLL_INTERVAL_SECS", "60"))
_DEFAULT_MAX_CONCURRENT: int = int(os.getenv("MERID_CANDLE_MAX_CONCURRENT", "8"))

# Kalshi supports only these period_interval values (minutes)
_KALSHI_VALID_PERIODS: set[int] = {1, 60, 1440}


class CandlePoller:
    """Async background service — polls Kalshi candlestick REST endpoint.

    Usage::

        poller = CandlePoller(client, store)
        await poller.start()
        # ... FastAPI runs ...
        await poller.stop()
    """

    def __init__(
        self,
        client: "KalshiVenueClient",
        store: "KalshiMarketStateStore",
        *,
        period_minutes: int = _DEFAULT_PERIOD_MINUTES,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ) -> None:
        if period_minutes not in _KALSHI_VALID_PERIODS:
            raise ValueError(
                f"period_minutes={period_minutes} not in supported values {sorted(_KALSHI_VALID_PERIODS)}"
            )
        self._client = client
        self._store = store
        self._period_minutes = period_minutes
        self._interval_seconds = interval_seconds
        self._max_concurrent = max_concurrent

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._ticks: int = 0
        self._errors: int = 0
        self._last_run_ts: float = 0.0
        self._last_poll_duration_ms: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="candle_poller")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("CandlePoller task crashed: %s", task.exception())
        self._task.add_done_callback(_task_done_cb)
        logger.info(
            "CandlePoller started (period=%dm interval=%.0fs concurrent=%d)",
            self._period_minutes,
            self._interval_seconds,
            self._max_concurrent,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected on clean shutdown
        logger.info("CandlePoller stopped (ticks=%d errors=%d)", self._ticks, self._errors)

    # ── Status ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self._running,
            "ticks": self._ticks,
            "errors": self._errors,
            "last_run_ts": self._last_run_ts,
            "last_run_age_s": round(time.time() - self._last_run_ts, 1) if self._last_run_ts else None,
            "period_minutes": self._period_minutes,
            "interval_seconds": self._interval_seconds,
            "last_poll_duration_ms": round(self._last_poll_duration_ms, 1),
        }

    # ── Loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            loop_start = time.monotonic()
            try:
                await self._poll_all()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("CandlePoller loop error: %s", exc)
                self._errors += 1
            # Fixed-rate scheduling: sleep accounts for poll duration
            elapsed = time.monotonic() - loop_start
            sleep_secs = max(0.0, self._interval_seconds - elapsed)
            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                return

    async def _poll_all(self) -> None:
        tickers = self._store.tickers()
        if not tickers:
            return

        # Single coherent timestamp for entire cycle
        cycle_ts = int(time.time())
        semaphore = asyncio.Semaphore(self._max_concurrent)
        tasks = [
            asyncio.create_task(self._poll_one(ticker, semaphore, cycle_ts))
            for ticker in tickers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._ticks += 1
        self._last_run_ts = cycle_ts

        err_count = sum(1 for r in results if isinstance(r, Exception))
        if err_count:
            self._errors += err_count
            logger.debug("CandlePoller: %d/%d tickers failed this cycle", err_count, len(tickers))

    async def _poll_one(self, ticker: str, sem: asyncio.Semaphore, cycle_ts: int) -> bool:
        """Poll a single ticker. Returns True on success, False on failure."""
        async with sem:
            poll_start = time.monotonic()
            # Request window that guarantees the last closed bar is included.
            # We ask for 3 periods back to ensure we get at least one complete bar
            # plus any forming bar, even with boundary timing issues.
            start_ts = cycle_ts - 3 * 60 * self._period_minutes
            result = await self._client.get_candlesticks(
                ticker,
                period_interval=self._period_minutes,
                start_ts=start_ts,
                end_ts=cycle_ts,
                include_latest_before_start=True,  # Ensures continuity at boundaries
            )
            if not result.success:
                logger.debug(
                    "CandlePoller: %s fetch failed — %s", ticker, result.error
                )
                return False  # Counted as error in _poll_all
            bars = result.data or []
            if not bars:
                logger.debug("CandlePoller: %s no bars returned", ticker)
                return False  # Counted as error in _poll_all

            # Select the last *closed* candle, not the forming one.
            # Bars are returned ordered by open time. The newest bar (bars[-1])
            # may still be forming. We want bars[-2] if available (last completed).
            # If only one bar returned, use it (edge case at market open).
            closed_bar = bars[-2] if len(bars) >= 2 else bars[-1]

            self._store.apply_candle_dict(
                ticker,
                closed_bar,
                period_interval=self._period_minutes * 60,  # store expects seconds
            )
            self._last_poll_duration_ms = (time.monotonic() - poll_start) * 1000
            return True


# ── Singleton ────────────────────────────────────────────────────────────────

_poller: Optional[CandlePoller] = None


def get_candle_poller() -> Optional[CandlePoller]:
    """Return the process-wide ``CandlePoller`` if it has been initialised."""
    return _poller


def init_candle_poller(
    client: "KalshiVenueClient",
    store: "KalshiMarketStateStore",
    **kwargs,
) -> CandlePoller:
    """Create (or replace) the process-wide ``CandlePoller`` singleton."""
    global _poller
    _poller = CandlePoller(client, store, **kwargs)
    return _poller
