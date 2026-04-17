"""Async CFB RTI feed loop — single ingress into CryptoRTIMonitor."""
from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.data.rti_feed_service")

_ASSETS_DEFAULT = ("BTC", "ETH", "SOL", "XRP", "DOGE")


@dataclass
class RTIFeedMetrics:
    up: bool = False
    last_tick_ts: float = 0.0
    gap_seconds: float = 0.0
    ticks_ingested: int = 0
    last_error: str = ""


class RTIFeedService:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.metrics = RTIFeedMetrics()
        self._stale_threshold = float(os.environ.get("MERID_RTI_STALE_SECONDS", "5.0"))
        self._divergence_kill = float(os.environ.get("MERID_RTI_MAX_DIVERGENCE", "0.05"))
        # Periodically reset the max-divergence watermark so a single early spike
        # does not permanently trigger the kill switch after it clears.
        self._divergence_reset_interval = int(
            os.environ.get("MERID_RTI_DIVERGENCE_RESET_INTERVAL", "300")
        )

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()

        # RTI feed is only needed when live CFB adapter is configured.
        # When quarantine is active, crypto RTI markets are already excluded
        # from order flow — skip the loop and validation entirely.
        from merid.event_venues.kalshi.cfb_quarantine import should_quarantine_rti_markets

        if should_quarantine_rti_markets():
            logger.info(
                "RTIFeedService: quarantine active (adapter=%r) — RTI feed loop not started",
                os.environ.get("MERID_CFB_RTI_ADAPTER", "null"),
            )
            return

        from merid.signals.cfb_rti_adapter import (
            LiveCFBRTIAdapter,
            get_cfb_rti_adapter,
            require_cfb_for_live_trading,
        )

        try:
            require_cfb_for_live_trading()
        except Exception as exc:
            logger.error("RTIFeedService: CFB validation failed: %s", exc)
            if os.environ.get("KALSHI_ENV", "").strip().lower() == "live":
                raise

        mode = os.environ.get("MERID_CFB_RTI_ADAPTER", "null").strip().lower()
        if mode == "live":
            live = LiveCFBRTIAdapter()
            live.validate_or_raise()

        self._task = asyncio.create_task(self._run_loop(), name="rti-feed-service")
        logger.info("RTIFeedService started (adapter=%s)", mode)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RTIFeedService stopped")

    async def _run_loop(self) -> None:
        import httpx

        from merid.data.rti_reconciler import get_rti_reconciler
        from merid.data.settlement_rti_buffer import get_settlement_buffer_registry
        from merid.risk.crypto_rti_monitor import get_global_crypto_rti_monitor
        from merid.signals.cfb_rti_adapter import LiveCFBRTIAdapter, NormalizedRTITick, get_cfb_rti_adapter

        mode = os.environ.get("MERID_CFB_RTI_ADAPTER", "null").strip().lower()
        sim = os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1" or mode == "simulation"
        adapter = get_cfb_rti_adapter()
        live = LiveCFBRTIAdapter() if isinstance(adapter, LiveCFBRTIAdapter) else None
        base_phase = 0.0
        _cycles_since_div_reset = 0

        async with httpx.AsyncClient() as client:
            while not self._stop.is_set():
                t0 = time.time()
                ticks: List[NormalizedRTITick] = []
                try:
                    if sim:
                        # If simulation points at a file:// URL, prefer file-backed ticks.
                        if mode == "simulation" and live and live.poll_url.lower().startswith("file://"):
                            ticks = await live.poll_once(client)
                        else:
                            base_phase += 0.05
                            for a in _ASSETS_DEFAULT:
                                px = 50_000.0 * (1.0 + 0.001 * math.sin(base_phase + ord(a[0])))
                                ticks.append(
                                    NormalizedRTITick(
                                        asset=a,
                                        index_id=f"SIM-{a}",
                                        price=px,
                                        ts_utc=time.time(),
                                    )
                                )
                    elif mode == "live" and live and live.poll_url:
                        ticks = await live.poll_once(client)
                    elif mode == "stub":
                        for a in _ASSETS_DEFAULT:
                            ticks.append(
                                NormalizedRTITick(asset=a, index_id="STUB", price=1.0, ts_utc=time.time())
                            )
                    _mon = get_global_crypto_rti_monitor()
                    _settlement_reg = get_settlement_buffer_registry()
                    for tick in ticks:
                        await _mon.on_rti_tick(tick.asset, tick.price, tick.ts_utc)
                        get_rti_reconciler().record_internal(tick.asset, tick.price, tick.ts_utc)
                        _settlement_reg.ingest_tick(tick.asset, tick.ts_utc, tick.price)
                        self.metrics.ticks_ingested += 1
                        self.metrics.last_tick_ts = time.time()

                    self.metrics.up = True
                    self.metrics.gap_seconds = 0.0
                    self.metrics.last_error = ""

                    if (
                        self.metrics.ticks_ingested > 0
                        and self.metrics.last_tick_ts
                        and (time.time() - self.metrics.last_tick_ts) > self._stale_threshold
                    ):
                        self._maybe_rti_kill("stale_feed")
                    _cycles_since_div_reset += 1
                    if os.environ.get("MERID_RTI_DIVERGENCE_KILL", "").strip() in ("1", "true", "yes"):
                        div = get_rti_reconciler().max_relative_divergence()
                        if div > self._divergence_kill:
                            self._maybe_rti_kill(f"divergence>{div:.4f}")
                    # Reset divergence watermark periodically so a single early spike
                    # does not permanently keep the metric elevated.
                    if _cycles_since_div_reset >= self._divergence_reset_interval:
                        get_rti_reconciler().reset_max_divergence()
                        _cycles_since_div_reset = 0
                        logger.debug("RTIFeedService: divergence watermark reset")

                except Exception as exc:
                    self.metrics.up = False
                    self.metrics.last_error = str(exc)
                    logger.warning("RTIFeedService cycle error: %s", exc)

                if sim or mode == "stub":
                    interval = 1.0
                elif live:
                    interval = max(0.5, live.interval)
                else:
                    interval = 2.0

                elapsed = time.time() - t0
                sleep_for = max(0.05, interval - elapsed)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
                except asyncio.TimeoutError:
                    pass

                if self.metrics.last_tick_ts:
                    self.metrics.gap_seconds = max(0.0, time.time() - self.metrics.last_tick_ts)

    def _maybe_rti_kill(self, reason: str) -> None:
        if os.environ.get("MERID_RTI_AUTO_KILL", "1").strip() not in ("1", "true", "yes"):
            return
        try:
            from merid.risk.kill_switches import risk_controller

            risk_controller.trigger_rti_feed_stale(reason)
        except Exception as exc:
            logger.debug("RTI kill trigger failed: %s", exc)


_service: Optional[RTIFeedService] = None


def get_rti_feed_service() -> RTIFeedService:
    global _service
    if _service is None:
        _service = RTIFeedService()
    return _service
