"""Tests for observability.observability_stack helpers."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

# Stub out db.neo4j to avoid real Neo4j connections during import.
if "db.neo4j" not in sys.modules:
    dummy_db = types.ModuleType("db.neo4j")

    class _DummyNeo4jMemory:
        def __init__(self, *args, **kwargs):
            pass

    dummy_db.Neo4jMemory = _DummyNeo4jMemory
    dummy_db.memory = _DummyNeo4jMemory()
    sys.modules["db.neo4j"] = dummy_db

if "governance.multi_agent_risk_controls" not in sys.modules:
    dummy_risk = types.ModuleType("governance.multi_agent_risk_controls")

    def _dummy_controls():
        class DummyControls:
            def validate_social_constraints(self, *args, **kwargs):
                return True, []

            def register_social_trade(self, *args, **kwargs):
                return None

        return DummyControls()

    dummy_risk.get_multi_agent_risk_controls = _dummy_controls
    sys.modules["governance.multi_agent_risk_controls"] = dummy_risk

if "social.social_aware_quant" not in sys.modules:
    dummy_social = types.ModuleType("social.social_aware_quant")

    class _DummySocialEngine:
        def get_social_risk_status(self):
            return {"kill_switch_active": False, "total_social_exposure": 0}

        def get_top_asset_exposure(self):
            return []

    dummy_engine = _DummySocialEngine()

    def _get_social_engine():
        return dummy_engine

    def _get_bot_health_monitor():
        return SimpleNamespace(
            get_health_summary=lambda: {"bot_health": {}}
        )

    dummy_social.get_social_aware_quant_engine = _get_social_engine
    dummy_social.get_social_bot_health_monitor = _get_bot_health_monitor
    sys.modules["social.social_aware_quant"] = dummy_social

import observability.observability_stack as obs_mod


class DummyTelemetry:
    """Minimal telemetry stub for ObservabilityStack tests."""

    def __init__(self):
        self.metrics = []

    def log_structured(self, *args, **kwargs):
        return None

    def record_metric(self, namespace, name, value, tags, unit=None):
        self.metrics.append((namespace, name, value, unit))

    def start_trace_span(self, *args, **kwargs):
        return SimpleNamespace(span_id="span", trace_id="trace")

    def add_span_log(self, *args, **kwargs):
        return None

    def end_trace_span(self, *args, **kwargs):
        return None

    def get_telemetry_stats(self):
        return {"streams": 1}

    def get_metrics(self, **_filters):
        return list(self.metrics)


@pytest.fixture
def observability_stack(monkeypatch):
    telemetry = DummyTelemetry()

    monkeypatch.setattr(obs_mod, "get_telemetry_manager", lambda: telemetry)
    monkeypatch.setattr(
        obs_mod,
        "get_info_theory_metrics",
        lambda: SimpleNamespace(get_drift_summary=lambda: {"summary": "ok"}),
    )
    monkeypatch.setattr(
        obs_mod,
        "get_clock_sync_monitor",
        lambda: SimpleNamespace(get_sync_status=lambda: {"max_drift_ms": 42}),
    )
    monkeypatch.setattr(
        obs_mod,
        "get_feed_parity_checker",
        lambda: SimpleNamespace(get_parity_status=lambda: {"recent_violations_1h": 2}),
    )
    monkeypatch.setattr(
        obs_mod,
        "get_lag_metrics_collector",
        lambda: SimpleNamespace(
            get_lag_summary=lambda: {"recent_alerts_1h": 1},
            record_lag=lambda *args, **kwargs: None,
        ),
    )

    stack = obs_mod.ObservabilityStack()
    return stack, telemetry


def test_record_system_metrics_with_optional_fields(observability_stack):
    stack, telemetry = observability_stack

    stack.record_system_metrics(
        service_name="svc",
        latency_p50_ms=10,
        latency_p95_ms=20,
        latency_p99_ms=25,
        error_rate=0.01,
        throughput_rps=100,
        queue_depth=5,
        cpu_usage_pct=50,
        memory_usage_mb=256,
        clock_sync_ms=5.5,
        feed_parity_pct=0.4,
        lag_p95_ms=900,
    )

    metric_names = [name for _, name, _, _ in telemetry.metrics]
    assert "svc.clock_sync_drift" in metric_names
    assert "svc.feed_parity" in metric_names
    assert "svc.pipeline_lag_p95" in metric_names


def test_observability_dashboards_surface_monitors(observability_stack):
    stack, _ = observability_stack

    dashboards = stack.get_observability_dashboards()

    assert dashboards["clock_sync"]["max_drift_ms"] == 42
    assert dashboards["feed_parity"]["recent_violations_1h"] == 2
    assert dashboards["lag_metrics"]["recent_alerts_1h"] == 1
