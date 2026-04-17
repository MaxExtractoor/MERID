"""
Per-feed staleness monitor with auto-pause for stale instruments.

Tracks last-update timestamps per feed/instrument and triggers trading
pauses when data exceeds configurable max_age thresholds.

Readiness Impact: S8-03 (1→2) — safe degradation on bad data.

Usage:
    from core.feed_staleness_monitor import get_feed_staleness_monitor
    monitor = get_feed_staleness_monitor()
    monitor.record_update("binance", "BTC/USDT")
    stale = monitor.check_all()  # returns list of stale feeds
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from prometheus_client import Gauge

    feed_staleness_seconds = Gauge(
        'merid_feed_staleness_seconds',
        'Age in seconds since last update for a data feed',
        ['feed', 'instrument']
    )
    feeds_stale_total = Gauge(
        'merid_feeds_stale_total',
        'Number of currently stale data feeds'
    )
    instruments_paused_total = Gauge(
        'merid_instruments_paused_total',
        'Number of instruments paused due to stale data'
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("core.feed_staleness_monitor")


@dataclass
class FeedConfig:
    """Configuration for a single data feed."""
    feed_id: str
    max_age_seconds: float = 60.0
    critical_age_seconds: float = 300.0
    instruments: List[str] = field(default_factory=list)


@dataclass
class FeedStatus:
    """Current status of a data feed."""
    feed_id: str
    instrument: str
    last_update: float
    age_seconds: float
    stale: bool
    critical: bool
    paused: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "instrument": self.instrument,
            "last_update": self.last_update,
            "age_seconds": round(self.age_seconds, 1),
            "stale": self.stale,
            "critical": self.critical,
            "paused": self.paused,
        }


class FeedStalenessMonitor:
    """Monitors data feed freshness and auto-pauses trading for stale instruments.

    Each feed+instrument pair has a last-update timestamp.  When the age
    exceeds ``max_age_seconds`` the pair is marked **stale** and trading
    for that instrument is paused.  When it exceeds ``critical_age_seconds``
    a critical alert callback fires.

    Callbacks:
        on_stale(feed_id, instrument, age_seconds)
        on_critical(feed_id, instrument, age_seconds)
        on_recovered(feed_id, instrument)
    """

    def __init__(
        self,
        default_max_age: float = 60.0,
        default_critical_age: float = 300.0,
    ):
        self.default_max_age = default_max_age
        self.default_critical_age = default_critical_age

        self._last_updates: Dict[str, float] = {}
        self._feed_configs: Dict[str, FeedConfig] = {}
        self._paused_instruments: Dict[str, str] = {}
        self._stale_set: set = set()

        self._on_stale_callbacks: List[Callable] = []
        self._on_critical_callbacks: List[Callable] = []
        self._on_recovered_callbacks: List[Callable] = []

        logger.info(
            f"FeedStalenessMonitor initialised: "
            f"default_max_age={default_max_age}s, "
            f"default_critical_age={default_critical_age}s"
        )

    def register_feed(self, config: FeedConfig) -> None:
        """Register a feed with custom staleness thresholds."""
        self._feed_configs[config.feed_id] = config
        for inst in config.instruments:
            key = f"{config.feed_id}:{inst}"
            if key not in self._last_updates:
                self._last_updates[key] = 0.0
        logger.info(
            f"Feed registered: {config.feed_id} "
            f"(max_age={config.max_age_seconds}s, "
            f"instruments={len(config.instruments)})"
        )

    def on_stale(self, callback: Callable) -> None:
        self._on_stale_callbacks.append(callback)

    def on_critical(self, callback: Callable) -> None:
        self._on_critical_callbacks.append(callback)

    def on_recovered(self, callback: Callable) -> None:
        self._on_recovered_callbacks.append(callback)

    def record_update(self, feed_id: str, instrument: str, ts: Optional[float] = None) -> None:
        """Record that *feed_id* delivered fresh data for *instrument*."""
        key = f"{feed_id}:{instrument}"
        self._last_updates[key] = ts or time.time()

        if key in self._stale_set:
            self._stale_set.discard(key)
            self._paused_instruments.pop(instrument, None)
            logger.info(f"Feed recovered: {key}")
            for cb in self._on_recovered_callbacks:
                try:
                    cb(feed_id, instrument)
                except Exception as exc:
                    logger.error(f"on_recovered callback error: {exc}")

    def _get_thresholds(self, feed_id: str):
        cfg = self._feed_configs.get(feed_id)
        if cfg:
            return cfg.max_age_seconds, cfg.critical_age_seconds
        return self.default_max_age, self.default_critical_age

    def check_feed(self, feed_id: str, instrument: str) -> FeedStatus:
        """Check staleness for a single feed+instrument pair."""
        key = f"{feed_id}:{instrument}"
        last = self._last_updates.get(key, 0.0)
        now = time.time()
        age = now - last if last > 0 else float("inf")
        max_age, critical_age = self._get_thresholds(feed_id)

        is_stale = age >= max_age
        is_critical = age >= critical_age
        is_paused = instrument in self._paused_instruments

        if is_stale and key not in self._stale_set:
            self._stale_set.add(key)
            self._paused_instruments[instrument] = feed_id
            logger.warning(f"Feed stale: {key} (age={age:.1f}s, max={max_age}s)")
            for cb in self._on_stale_callbacks:
                try:
                    cb(feed_id, instrument, age)
                except Exception as exc:
                    logger.error(f"on_stale callback error: {exc}")

        if is_critical:
            for cb in self._on_critical_callbacks:
                try:
                    cb(feed_id, instrument, age)
                except Exception as exc:
                    logger.error(f"on_critical callback error: {exc}")

        # Update Prometheus gauges
        if _PROMETHEUS_AVAILABLE:
            feed_staleness_seconds.labels(feed=feed_id, instrument=instrument).set(
                age if age != float("inf") else -1
            )

        return FeedStatus(
            feed_id=feed_id,
            instrument=instrument,
            last_update=last,
            age_seconds=age,
            stale=is_stale,
            critical=is_critical,
            paused=is_paused or is_stale,
        )

    def check_all(self) -> List[FeedStatus]:
        """Check all registered feeds and return stale ones."""
        stale_feeds = []
        for key, last in self._last_updates.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            feed_id, instrument = parts
            status = self.check_feed(feed_id, instrument)
            if status.stale:
                stale_feeds.append(status)

        # Update aggregate Prometheus gauges
        if _PROMETHEUS_AVAILABLE:
            feeds_stale_total.set(len(self._stale_set))
            instruments_paused_total.set(len(self._paused_instruments))

        return stale_feeds

    def is_instrument_paused(self, instrument: str) -> bool:
        """Check if trading for *instrument* is paused due to stale data."""
        return instrument in self._paused_instruments

    def get_paused_instruments(self) -> Dict[str, str]:
        """Return {instrument: feed_id} for all paused instruments."""
        return dict(self._paused_instruments)

    def get_summary(self) -> Dict[str, Any]:
        """Return a JSON-serialisable summary for dashboards."""
        all_statuses = []
        for key in self._last_updates:
            parts = key.split(":", 1)
            if len(parts) == 2:
                all_statuses.append(self.check_feed(parts[0], parts[1]).to_dict())

        all_statuses.sort(key=lambda s: s["age_seconds"], reverse=True)

        return {
            "total_feeds": len(self._last_updates),
            "stale_count": len(self._stale_set),
            "paused_instruments": dict(self._paused_instruments),
            "feeds": all_statuses,
        }


_monitor: Optional[FeedStalenessMonitor] = None
_monitor_lock = threading.Lock()


def get_feed_staleness_monitor() -> FeedStalenessMonitor:
    """Return the module-level FeedStalenessMonitor singleton."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = FeedStalenessMonitor()
    return _monitor
