import os
import sys
from types import ModuleType
from typing import Dict, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

monitoring_pkg = ModuleType("monitoring")
monitoring_pkg.__path__ = [os.path.join(ROOT, "monitoring")]
metrics_mod = ModuleType("monitoring.metrics")
metrics_collector_mod = ModuleType("monitoring.metrics_collector")
news_feeds_mod = ModuleType("monitoring.news_feeds")


class _DummyAggregatedNewsFeed:
    def __init__(self, *args, **kwargs):
        self._items = []

    async def start(self):  # pragma: no cover - stub
        return None

    async def stop(self):  # pragma: no cover - stub
        return None

    async def poll(self):  # pragma: no cover - stub
        return []


class _StubMetricValue:
    def __init__(self, *, value: float, labels: Optional[Dict[str, str]] = None, name: str = "", metric_type: str = "", help_text: str = ""):
        self.value = value
        self.labels = labels or {}
        self.name = name
        self.metric_type = metric_type
        self.help_text = help_text


class _StubCounter:
    def __init__(self, *_: tuple[str, ...], **__: object):
        self.samples: Dict[tuple, float] = {}

    def inc(self, amount: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        self.samples[key] = self.samples.get(key, 0.0) + amount

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = tuple(sorted((labels or {}).items()))
        return self.samples.get(key, 0.0)

    def collect(self) -> list[_StubMetricValue]:
        return []


class _StubGauge:
    def __init__(self, *_: tuple[str, ...], **__: object):
        self.values: Dict[tuple, float] = {}

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        self.values[key] = value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = tuple(sorted((labels or {}).items()))
        return self.values.get(key, 0.0)

    def collect(self) -> list[_StubMetricValue]:
        return []


class _StubHistogram:
    def __init__(self, *_: tuple[str, ...], **__: object):
        self.observations: list[float] = []

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.observations.append(value)

    def collect(self) -> list[_StubMetricValue]:
        return []


def _dummy_get_metrics_collector() -> object:
    from monitoring.kalshi_metrics import get_kalshi_metrics_collector

    return get_kalshi_metrics_collector()


def install_monitoring_stubs() -> None:
    if getattr(monitoring_pkg, "_stubs_installed", False):
        return

    metrics_mod.Counter = _StubCounter
    metrics_mod.Gauge = _StubGauge
    metrics_mod.Histogram = _StubHistogram
    metrics_mod.MetricValue = _StubMetricValue

    metrics_collector_mod.get_metrics_collector = _dummy_get_metrics_collector

    news_feeds_mod.AggregatedNewsFeed = _DummyAggregatedNewsFeed

    setattr(monitoring_pkg, "metrics", metrics_mod)
    setattr(monitoring_pkg, "metrics_collector", metrics_collector_mod)
    setattr(monitoring_pkg, "news_feeds", news_feeds_mod)

    sys.modules["monitoring"] = monitoring_pkg
    sys.modules["monitoring.metrics"] = metrics_mod
    sys.modules["monitoring.metrics_collector"] = metrics_collector_mod
    sys.modules["monitoring.news_feeds"] = news_feeds_mod

    monitoring_pkg._stubs_installed = True
