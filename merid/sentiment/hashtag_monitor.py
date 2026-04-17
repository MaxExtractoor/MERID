"""HashtagMonitor — Background loop for real-time hashtag + news ingestion.

Runs two async loops:
  1. HashtagAgent.run_cycle()  — every HASHTAG_INTERVAL_S seconds
  2. NewsIngestionAgent.run_cycle() — every NEWS_INTERVAL_S seconds

After each hashtag cycle, generates HashtagSignal objects and pushes
them to SentimentBusV2 and optionally to Telegram.

Never drives orders. All signals flow through SentimentBusV2 → agents
→ risk layer.
"""

from __future__ import annotations

import threading
import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

logger = get_logger("merid.sentiment.hashtag_monitor")

HASHTAG_INTERVAL_S = int(os.getenv("MERID_HASHTAG_INTERVAL_S", "120"))   # 2 min
NEWS_INTERVAL_S = int(os.getenv("MERID_NEWS_INTERVAL_S", "300"))          # 5 min
ASSET_CYCLE_INTERVAL_S = int(os.getenv("MERID_ASSET_CYCLE_INTERVAL_S", "60"))  # 1 min
VOLUME_SPIKE_THRESHOLD = float(os.getenv("MERID_HASHTAG_SPIKE_THRESHOLD", "2.5"))
SCORE_THRESHOLD = float(os.getenv("MERID_HASHTAG_SCORE_THRESHOLD", "0.25"))
TELEGRAM_ALERTS_ENABLED = os.getenv("MERID_HASHTAG_TELEGRAM_ALERTS", "1") == "1"


@dataclass
class MonitorStats:
    hashtag_cycles: int = 0
    news_cycles: int = 0
    asset_cycles: int = 0
    signals_generated: int = 0
    last_hashtag_cycle_ts: Optional[float] = None
    last_news_cycle_ts: Optional[float] = None
    errors: int = 0


class HashtagMonitor:
    """Orchestrates HashtagAgent + NewsIngestionAgent background loops.

    Usage::

        monitor = get_hashtag_monitor()
        await monitor.start()
        # ... runs in background ...
        await monitor.stop()
    """

    def __init__(
        self,
        hashtag_interval: int = HASHTAG_INTERVAL_S,
        news_interval: int = NEWS_INTERVAL_S,
        asset_cycle_interval: int = ASSET_CYCLE_INTERVAL_S,
    ) -> None:
        self._hashtag_interval = hashtag_interval
        self._news_interval = news_interval
        self._asset_interval = asset_cycle_interval
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self.stats = MonitorStats()
        self._last_signals: List[Any] = []

    # ── Lazy accessors ────────────────────────────────────────────────

    def _get_hashtag_agent(self) -> Any:
        from merid.sentiment.hashtag_agent import get_hashtag_agent
        return get_hashtag_agent()

    def _get_news_agent(self) -> Any:
        from merid.sentiment.news_ingestion_agent import get_news_ingestion_agent
        return get_news_ingestion_agent()

    def _get_bus(self) -> Any:
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
        return get_sentiment_bus_v2()

    def _get_fg(self, asset: str) -> Optional[int]:
        try:
            from merid.sentiment.cfgi_client import quick_fg
            return quick_fg(asset)
        except Exception:
            return None

    def _fg_by_canonical_assets(self) -> Dict[str, int]:
        """Fear/greed per active crypto asset (not BTC-only)."""
        out: Dict[str, int] = {}
        for sym in ACTIVE_CRYPTO_ASSETS:
            fg = self._get_fg(sym)
            if fg is not None:
                out[sym] = int(fg)
        return out

    # ── Telegram publishing ───────────────────────────────────────────

    def _publish_signal_telegram(self, signals: List[Any]) -> None:
        """Send strong signals to Telegram (non-blocking, best-effort)."""
        if not TELEGRAM_ALERTS_ENABLED:
            return
        strong = [s for s in signals if s.strength >= 0.5]
        if not strong:
            return
        try:
            from merid.prediction.alerts import (
                get_alert_manager, PredictionAlert, AlertCategory, AlertSeverity,
            )
            mgr = get_alert_manager()
            for sig in strong[:3]:
                emoji = "🟢" if sig.direction == "bullish" else (
                    "🔴" if sig.direction == "bearish" else "🟡"
                )
                msg = (
                    f"{emoji} Hashtag Signal [{sig.category.upper()}]\n"
                    f"Asset/Event: {sig.asset_or_event}\n"
                    f"Direction: {sig.direction} (strength={sig.strength:.2f})\n"
                    f"Reason: {sig.reason}\n"
                    f"Tags: {', '.join(sig.tags[:4])}\n"
                    f"Score: {sig.score:+.3f} | Vol: {sig.volume}"
                )
                mgr.fire(PredictionAlert(
                    category=AlertCategory.MARKET_SELECTION,
                    severity=AlertSeverity.INFO,
                    title=f"Hashtag signal: {sig.asset_or_event}",
                    message=msg,
                    market_id=sig.asset_or_event,
                    data={"direction": sig.direction, "strength": sig.strength},
                ))
        except Exception as exc:
            logger.debug("Telegram signal publish failed: %s", exc)

    # ── Cycle runners ─────────────────────────────────────────────────

    async def _run_hashtag_cycle(self) -> None:
        """Run one hashtag scrape + signal generation cycle."""
        try:
            agent = self._get_hashtag_agent()
            sentiments = await agent.run_cycle()

            fg_map = self._fg_by_canonical_assets()
            signals = agent.generate_signals(
                sentiments,
                fg_by_asset=fg_map,
                volume_spike_threshold=VOLUME_SPIKE_THRESHOLD,
                score_threshold=SCORE_THRESHOLD,
            )

            bus = self._get_bus()
            if signals:
                bus.update_signals(signals)
                self._last_signals = signals
                self.stats.signals_generated += len(signals)
                self._publish_signal_telegram(signals)
                logger.info(
                    "[hashtag-monitor] %d signals generated (top: %s %s %.2f)",
                    len(signals),
                    signals[0].direction,
                    signals[0].asset_or_event,
                    signals[0].strength,
                )

            self.stats.hashtag_cycles += 1
            self.stats.last_hashtag_cycle_ts = time.time()

        except Exception as exc:
            self.stats.errors += 1
            logger.warning("[hashtag-monitor] hashtag cycle error: %s", exc)

    async def _run_asset_cycle(self) -> None:
        """Run asset-only hashtag cycle (faster, no Kalshi event fetch)."""
        try:
            agent = self._get_hashtag_agent()
            sentiments = await agent.run_asset_cycle()

            fg_map = self._fg_by_canonical_assets()
            signals = agent.generate_signals(
                sentiments,
                fg_by_asset=fg_map,
                volume_spike_threshold=VOLUME_SPIKE_THRESHOLD,
                score_threshold=SCORE_THRESHOLD,
            )

            bus = self._get_bus()
            if signals:
                bus.update_signals(signals)
                self.stats.signals_generated += len(signals)

            self.stats.asset_cycles += 1

        except Exception as exc:
            self.stats.errors += 1
            logger.debug("[hashtag-monitor] asset cycle error: %s", exc)

    async def _run_news_cycle(self) -> None:
        """Run one news ingestion cycle across all categories."""
        try:
            agent = self._get_news_agent()
            await agent.run_cycle()
            self.stats.news_cycles += 1
            self.stats.last_news_cycle_ts = time.time()
        except Exception as exc:
            self.stats.errors += 1
            logger.warning("[hashtag-monitor] news cycle error: %s", exc)

    # ── Background loops ──────────────────────────────────────────────

    async def _hashtag_loop(self) -> None:
        """Full hashtag loop (with Kalshi event fetch)."""
        await asyncio.sleep(5)  # brief startup delay
        while self._running:
            await self._run_hashtag_cycle()
            try:
                await asyncio.sleep(self._hashtag_interval)
            except asyncio.CancelledError:
                break

    async def _asset_loop(self) -> None:
        """Fast asset-only loop (no Kalshi event fetch)."""
        await asyncio.sleep(15)  # offset from hashtag loop
        while self._running:
            await self._run_asset_cycle()
            try:
                await asyncio.sleep(self._asset_interval)
            except asyncio.CancelledError:
                break

    async def _news_loop(self) -> None:
        """News ingestion loop."""
        await asyncio.sleep(30)  # offset from hashtag loop
        while self._running:
            await self._run_news_cycle()
            try:
                await asyncio.sleep(self._news_interval)
            except asyncio.CancelledError:
                break

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all background loops."""
        if self._running:
            logger.warning("HashtagMonitor already running")
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._hashtag_loop(), name="hashtag-monitor-full"),
            asyncio.create_task(self._asset_loop(), name="hashtag-monitor-asset"),
            asyncio.create_task(self._news_loop(), name="hashtag-monitor-news"),
        ]
        logger.info(
            "HashtagMonitor started (hashtag=%ds, asset=%ds, news=%ds)",
            self._hashtag_interval, self._asset_interval, self._news_interval,
        )

    async def stop(self) -> None:
        """Stop all background loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info(
            "HashtagMonitor stopped — cycles: hashtag=%d news=%d asset=%d signals=%d errors=%d",
            self.stats.hashtag_cycles,
            self.stats.news_cycles,
            self.stats.asset_cycles,
            self.stats.signals_generated,
            self.stats.errors,
        )

    # ── Manual triggers ───────────────────────────────────────────────

    async def force_hashtag_cycle(self) -> List[Any]:
        """Trigger an immediate hashtag cycle (for testing/operator use)."""
        await self._run_hashtag_cycle()
        return self._last_signals

    async def force_news_cycle(self) -> None:
        """Trigger an immediate news cycle."""
        await self._run_news_cycle()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "hashtag_cycles": self.stats.hashtag_cycles,
            "news_cycles": self.stats.news_cycles,
            "asset_cycles": self.stats.asset_cycles,
            "signals_generated": self.stats.signals_generated,
            "errors": self.stats.errors,
            "last_hashtag_ts": self.stats.last_hashtag_cycle_ts,
            "last_news_ts": self.stats.last_news_cycle_ts,
            "running": self._running,
        }

    def get_latest_signals(self) -> List[Any]:
        return list(self._last_signals)


# ── Singleton ─────────────────────────────────────────────────────────────

_monitor: Optional[HashtagMonitor] = None
_monitor_lock = threading.Lock()


def get_hashtag_monitor() -> HashtagMonitor:
    """Return the singleton HashtagMonitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = HashtagMonitor()
    return _monitor
