import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

import monitoring.metrics as _real_metrics_mod
from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode
from monitoring import kalshi_metrics


class _StubMetricValue:
    def __init__(self, value: float, labels: dict | None = None) -> None:
        self.value = value
        self.labels = labels or {}


class _StubCounter:
    def __init__(self, *_: object, **__: object) -> None:
        self.samples: dict = {}

    def inc(self, amount: float = 1, labels: dict | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        self.samples[key] = self.samples.get(key, 0) + amount

    def get(self, labels: dict) -> float:
        key = tuple(sorted(labels.items()))
        return self.samples.get(key, 0)

    def collect(self) -> list:
        return []


class _StubGauge:
    def __init__(self, *_: object, **__: object) -> None:
        self.values: dict = {}

    def set(self, value: float, labels: dict | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        self.values[key] = value

    def collect(self) -> list:
        return []


class _StubHistogram:
    def __init__(self, *_: object, **__: object) -> None:
        self.observations: list = []

    def observe(self, value: float, labels: dict | None = None) -> None:
        self.observations.append(value)

    def collect(self) -> list:
        return []


def _fake_to_prometheus(self: kalshi_metrics.KalshiMetricsCollector) -> str:
    lines: list[str] = []
    counter = self.orders_rejected
    for sample, value in counter.samples.items():
        labels = ",".join([f'{k}="{v}"' for k, v in sample])
        lines.append(f"kalshi_orders_rejected_total{{{labels}}} {value}")
    return "\n".join(lines)


@pytest.fixture(autouse=True)
def patch_metrics_with_stubs():
    """Patch monitoring.metrics with stubs for the duration of each test, restore after."""
    # Save originals
    orig_counter = _real_metrics_mod.Counter
    orig_gauge = _real_metrics_mod.Gauge
    orig_histogram = _real_metrics_mod.Histogram
    orig_metric_value = _real_metrics_mod.MetricValue
    orig_km_counter = kalshi_metrics.Counter
    orig_km_gauge = kalshi_metrics.Gauge
    orig_km_histogram = kalshi_metrics.Histogram
    orig_to_prometheus = kalshi_metrics.KalshiMetricsCollector.to_prometheus_format

    # Install stubs
    _real_metrics_mod.Counter = _StubCounter  # type: ignore[attr-defined]
    _real_metrics_mod.Gauge = _StubGauge  # type: ignore[attr-defined]
    _real_metrics_mod.Histogram = _StubHistogram  # type: ignore[attr-defined]
    _real_metrics_mod.MetricValue = _StubMetricValue  # type: ignore[attr-defined]
    kalshi_metrics.Counter = _StubCounter  # type: ignore[attr-defined]
    kalshi_metrics.Gauge = _StubGauge  # type: ignore[attr-defined]
    kalshi_metrics.Histogram = _StubHistogram  # type: ignore[attr-defined]
    kalshi_metrics.KalshiMetricsCollector.to_prometheus_format = _fake_to_prometheus
    kalshi_metrics._collector = None  # type: ignore[attr-defined]

    yield

    # Restore originals
    _real_metrics_mod.Counter = orig_counter  # type: ignore[attr-defined]
    _real_metrics_mod.Gauge = orig_gauge  # type: ignore[attr-defined]
    _real_metrics_mod.Histogram = orig_histogram  # type: ignore[attr-defined]
    _real_metrics_mod.MetricValue = orig_metric_value  # type: ignore[attr-defined]
    kalshi_metrics.Counter = orig_km_counter  # type: ignore[attr-defined]
    kalshi_metrics.Gauge = orig_km_gauge  # type: ignore[attr-defined]
    kalshi_metrics.Histogram = orig_km_histogram  # type: ignore[attr-defined]
    kalshi_metrics.KalshiMetricsCollector.to_prometheus_format = orig_to_prometheus  # type: ignore[attr-defined]
    kalshi_metrics._collector = None  # type: ignore[attr-defined]


class TestKalshiMetrics:
    def test_rejected_order_labels(self):
        collector = kalshi_metrics.get_kalshi_metrics_collector()
        kalshi_metrics.record_kalshi_order(
            mode="live",
            status="rejected",
            count=1,
            latency_ms=50,
            error_code=KalshiOrderErrorCode.KILL_SWITCH.value,
        )

        severity = KalshiOrderErrorCode.KILL_SWITCH.severity
        category = KalshiOrderErrorCode.KILL_SWITCH.category

        assert collector.orders_rejected.get({
            "error_code": KalshiOrderErrorCode.KILL_SWITCH.value,
            "severity": severity,
            "category": category,
        }) == 1

    def test_prometheus_output_contains_labels(self):
        collector = kalshi_metrics.get_kalshi_metrics_collector()
        kalshi_metrics.record_kalshi_order(
            mode="paper",
            status="rejected",
            count=2,
            error_code=KalshiOrderErrorCode.DAILY_LOSS_LIMIT.value,
        )

        output = collector.to_prometheus_format()
        first_line = output.splitlines()[0]
        assert first_line.startswith("kalshi_orders_rejected_total{")
        labels_str = first_line.split("{", 1)[1].split("}", 1)[0]
        label_pairs = [label.split("=", 1) for label in labels_str.split(",")]
        labels = {key: value.strip('"') for key, value in label_pairs}
        expected = {
            "error_code": "daily_loss_limit",
            "severity": "critical",
            "category": "risk",
        }
        assert labels == expected

    def test_cb_trigger_counter_records_labels(self):
        collector = kalshi_metrics.get_kalshi_metrics_collector()
        kalshi_metrics.record_kalshi_cb_trigger(KalshiOrderErrorCode.CIRCUIT_BREAKER)

        expected_labels = {
            "error_code": "circuit_breaker",
            "category": "risk",
        }
        assert collector.cb_triggers.get(expected_labels) == 1
