"""Swarm Critic Agent — Sprint H.

Wraps existing staleness and liquidity monitors and publishes typed
``Critique`` messages to the streaming bus. Also provides a dedicated
critic that can down-weight or veto forecaster outputs.

Integration points:
- ``core/feed_staleness_monitor.py`` — stale data detection
- ``merid/event_venues/kalshi/liquidity_monitor.py`` — illiquidity detection
- ``merid/swarm/messages.py`` — typed Critique schema

Usage::

    critic = get_critic_agent()
    critiques = critic.evaluate_market("KXBTC-24FEB21")
    # Or run as periodic background task:
    await critic.start()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.critic_agent")


@dataclass
class CriticConfig:
    """Configuration for the critic agent."""
    staleness_threshold_s: float = 300.0   # 5 min
    critical_staleness_s: float = 600.0    # 10 min
    min_depth: int = 50
    max_spread: float = 0.08               # 8 cents
    check_interval_s: float = 30.0         # How often to sweep


class CriticAgent:
    """Evaluates market conditions and publishes Critique messages.

    Wraps the existing FeedStalenessMonitor and LiquidityMonitor,
    converting their alerts into typed Critique messages on the bus.
    """

    def __init__(self, config: Optional[CriticConfig] = None):
        self._config = config or CriticConfig()
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._critiques: List[Dict[str, Any]] = []
        self._max_history = 200

    async def start(self) -> None:
        """Start periodic critic sweep."""
        self._shutdown.clear()
        self._task = asyncio.create_task(
            self._run_loop(), name="swarm-critic-agent"
        )
        logger.info("Critic agent started")

    async def stop(self) -> None:
        """Stop the critic agent."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Critic agent stopped")

    async def _run_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._sweep()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Critic sweep error: {exc}")
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._config.check_interval_s,
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _sweep(self) -> None:
        """Run all critic checks and publish Critique messages."""
        critiques = []
        critiques.extend(self._check_staleness())
        critiques.extend(self._check_liquidity())

        for critique in critiques:
            self._critiques.append(critique.to_dict())
            if len(self._critiques) > self._max_history:
                self._critiques = self._critiques[-self._max_history:]
            try:
                from merid.swarm.messages import publish_critique
                await publish_critique(critique)
            except Exception:
                pass

    def _check_staleness(self) -> list:
        """Check for stale data feeds and produce Critique messages."""
        from merid.swarm.messages import Critique
        critiques = []
        try:
            from core.feed_staleness_monitor import get_feed_staleness_monitor
            monitor = get_feed_staleness_monitor()
            stale_feeds = monitor.check_all()
            for status in stale_feeds:
                severity = 1.0 if status.critical else 0.6
                critiques.append(Critique(
                    critic_id="staleness_critic",
                    critique_type="stale_data",
                    market_id=status.instrument,
                    severity=severity,
                    reason=f"Feed {status.feed_id} stale for {status.age_seconds:.0f}s "
                           f"(threshold: {self._config.staleness_threshold_s:.0f}s)",
                    recommended_action="down_weight" if not status.critical else "veto",
                    weight_adjustment=0.0 if status.critical else 0.3,
                    data={
                        "feed_id": status.feed_id,
                        "instrument": status.instrument,
                        "age_seconds": status.age_seconds,
                        "critical": status.critical,
                    },
                ))
        except Exception as exc:
            logger.debug(f"Staleness check failed: {exc}")
        return critiques

    def _check_liquidity(self) -> list:
        """Check recent liquidity alerts and produce Critique messages."""
        from merid.swarm.messages import Critique
        critiques = []
        try:
            from merid.event_venues.kalshi.liquidity_monitor import get_liquidity_monitor
            monitor = get_liquidity_monitor()
            recent_alerts = list(monitor._alert_log)[-20:]  # Last 20 alerts
            now = time.time()
            for alert in recent_alerts:
                if now - alert.ts > 60:  # Only recent alerts (< 1 min)
                    continue
                severity = 0.9 if alert.severity == "critical" else 0.5
                critiques.append(Critique(
                    critic_id="liquidity_critic",
                    critique_type="illiquid" if alert.kind in ("thin_book", "depth_drop") else "spread_warning",
                    market_id=alert.market_id,
                    severity=severity,
                    reason=alert.msg,
                    recommended_action="down_weight",
                    weight_adjustment=0.2 if alert.severity == "critical" else 0.5,
                    data=alert.details,
                ))
        except Exception as exc:
            logger.debug(f"Liquidity check failed: {exc}")
        return critiques

    def evaluate_market(self, market_id: str) -> list:
        """Synchronous single-market evaluation."""
        from merid.swarm.messages import Critique
        critiques = []

        # Check staleness for this market
        try:
            from core.feed_staleness_monitor import get_feed_staleness_monitor
            monitor = get_feed_staleness_monitor()
            status = monitor.check_feed("kalshi", market_id)
            if status.stale:
                critiques.append(Critique(
                    critic_id="staleness_critic",
                    critique_type="stale_data",
                    market_id=market_id,
                    severity=1.0 if status.critical else 0.6,
                    reason=f"Stale for {status.age_seconds:.0f}s",
                    recommended_action="veto" if status.critical else "down_weight",
                    weight_adjustment=0.0 if status.critical else 0.3,
                ))
        except Exception:
            pass

        return critiques

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self._critiques.copy()


# ── Singleton ────────────────────────────────────────────────────────────

_critic: Optional[CriticAgent] = None


def get_critic_agent() -> CriticAgent:
    """Get or create the singleton CriticAgent."""
    global _critic
    if _critic is None:
        _critic = CriticAgent()
    return _critic
