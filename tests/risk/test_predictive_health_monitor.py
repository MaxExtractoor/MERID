"""Risk-core tests for swarm.predictive_health_monitor."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm.predictive_health_monitor import ForecastedMetric, PredictiveHealthMonitor
pytestmark = pytest.mark.risk_core


def _seed_series(monitor: PredictiveHealthMonitor, metric: str, start: datetime, values: list[float]) -> None:
    monitor._history[metric] = [
        (start + timedelta(minutes=i), value) for i, value in enumerate(values)
    ]


def test_forecast_requires_minimum_history() -> None:
    monitor = PredictiveHealthMonitor()
    _seed_series(monitor, "cpu", datetime.utcnow(), [50.0, 52.0, 54.0, 56.0])

    forecast = monitor.forecast("cpu", threshold=80.0)

    assert forecast is None


def test_forecast_detects_breach_within_horizon() -> None:
    monitor = PredictiveHealthMonitor(horizon_minutes=30)
    _seed_series(monitor, "latency", datetime.utcnow() - timedelta(minutes=10), [400, 410, 420, 430, 440, 450])

    forecast = monitor.forecast("latency", threshold=500.0)

    assert forecast is not None
    assert isinstance(forecast, ForecastedMetric)
    assert forecast.breach_time is not None
    assert forecast.current_value == pytest.approx(450)
    assert forecast.forecast_value > forecast.current_value
    assert forecast.breach_time - datetime.utcnow() < timedelta(minutes=30)
    assert 0.0 <= forecast.confidence <= 1.0


def test_forecast_handles_negative_trend_without_breach() -> None:
    monitor = PredictiveHealthMonitor(horizon_minutes=120)
    _seed_series(monitor, "errors", datetime.utcnow() - timedelta(minutes=10), [15, 14, 13, 12, 11, 10])

    forecast = monitor.forecast("errors", threshold=20.0)

    assert forecast is not None
    assert forecast.breach_time is None
    assert forecast.forecast_value < forecast.current_value
