"""Tests for Prometheus metrics collection."""

import pytest
from unittest.mock import patch, MagicMock

from merid.resilience.metrics import (
    MetricSample,
    MetricFamily,
    MetricsCollector,
    get_metrics_text,
    get_metrics_json,
    get_collector,
)


class TestMetricSample:
    """Tests for MetricSample dataclass."""
    
    def test_to_prometheus_no_labels(self):
        """Sample without labels formats correctly."""
        sample = MetricSample(name="test_metric", value=42.5)
        assert sample.to_prometheus() == "test_metric 42.5"
    
    def test_to_prometheus_with_labels(self):
        """Sample with labels formats correctly."""
        sample = MetricSample(
            name="test_metric",
            value=100,
            labels={"venue": "kalshi", "type": "order"},
        )
        result = sample.to_prometheus()
        assert "test_metric{" in result
        assert 'venue="kalshi"' in result
        assert 'type="order"' in result
        assert "} 100" in result


class TestMetricFamily:
    """Tests for MetricFamily dataclass."""
    
    def test_to_prometheus_format(self):
        """Family formats with HELP and TYPE."""
        family = MetricFamily(
            name="test_counter",
            help_text="A test counter",
            metric_type="counter",
            samples=[
                MetricSample(name="test_counter", value=10, labels={"a": "1"}),
                MetricSample(name="test_counter", value=20, labels={"a": "2"}),
            ],
        )
        
        result = family.to_prometheus()
        
        assert "# HELP test_counter A test counter" in result
        assert "# TYPE test_counter counter" in result
        assert 'test_counter{a="1"} 10' in result
        assert 'test_counter{a="2"} 20' in result


class TestMetricsCollector:
    """Tests for MetricsCollector class."""
    
    @pytest.fixture
    def collector(self):
        return MetricsCollector()
    
    def test_collect_returns_list(self, collector):
        """Collect returns list of metric families."""
        families = collector.collect()
        assert isinstance(families, list)
    
    def test_collect_circuit_breaker_metrics(self, collector):
        """Circuit breaker metrics are collected."""
        # Create a circuit breaker first
        from merid.resilience import get_circuit_breaker, reset_all_breakers
        reset_all_breakers()
        
        cb = get_circuit_breaker("test_venue")
        
        families = collector._collect_circuit_breaker_metrics()
        
        assert len(families) > 0
        names = [f.name for f in families]
        assert "merid_circuit_breaker_state" in names
        assert "merid_circuit_breaker_failures_total" in names
        
        reset_all_breakers()
    
    def test_collect_bulkhead_metrics(self, collector):
        """Bulkhead metrics are collected."""
        from merid.resilience import get_bulkhead, reset_all_bulkheads
        reset_all_bulkheads()
        
        bh = get_bulkhead("test_bulkhead")
        
        families = collector._collect_bulkhead_metrics()
        
        assert len(families) > 0
        names = [f.name for f in families]
        assert "merid_bulkhead_active" in names
        assert "merid_bulkhead_queued" in names
        
        reset_all_bulkheads()
    
    def test_collect_risk_metrics(self, collector):
        """Risk metrics are collected."""
        families = collector._collect_risk_metrics()
        
        # Should have risk metrics
        names = [f.name for f in families]
        assert "merid_risk_kill_switch_state" in names
        assert "merid_risk_daily_pnl_usd" in names


class TestGetMetricsText:
    """Tests for get_metrics_text function."""
    
    def test_returns_string(self):
        """get_metrics_text returns a string."""
        text = get_metrics_text()
        assert isinstance(text, str)
    
    def test_contains_help_lines(self):
        """Output contains HELP directives."""
        # Ensure we have some metrics
        from merid.resilience import get_circuit_breaker, reset_all_breakers
        reset_all_breakers()
        get_circuit_breaker("metrics_test")
        
        text = get_metrics_text()
        assert "# HELP" in text
        assert "# TYPE" in text
        
        reset_all_breakers()
    
    def test_prometheus_format(self):
        """Output is valid Prometheus format."""
        from merid.resilience import get_circuit_breaker, reset_all_breakers
        reset_all_breakers()
        get_circuit_breaker("format_test")
        
        text = get_metrics_text()
        
        # Check basic format rules
        lines = text.split("\n")
        for line in lines:
            if line.startswith("#"):
                # Comment lines
                assert line.startswith("# HELP") or line.startswith("# TYPE")
            elif line.strip():
                # Metric lines should have name and value
                parts = line.split()
                assert len(parts) >= 1
        
        reset_all_breakers()


class TestGetMetricsJson:
    """Tests for get_metrics_json function."""
    
    def test_returns_dict(self):
        """get_metrics_json returns a dict."""
        result = get_metrics_json()
        assert isinstance(result, dict)
    
    def test_contains_metric_info(self):
        """JSON contains metric metadata."""
        from merid.resilience import get_circuit_breaker, reset_all_breakers
        reset_all_breakers()
        get_circuit_breaker("json_test")
        
        result = get_metrics_json()
        
        # Check structure
        for name, data in result.items():
            assert "help" in data
            assert "type" in data
            assert "samples" in data
            assert isinstance(data["samples"], list)
        
        reset_all_breakers()


class TestGetCollector:
    """Tests for get_collector singleton."""
    
    def test_returns_same_instance(self):
        """get_collector returns the same instance."""
        c1 = get_collector()
        c2 = get_collector()
        assert c1 is c2
    
    def test_returns_metrics_collector(self):
        """get_collector returns MetricsCollector."""
        c = get_collector()
        assert isinstance(c, MetricsCollector)


class TestMetricsIntegration:
    """Integration tests for metrics with real components."""
    
    @pytest.fixture(autouse=True)
    def reset_components(self):
        """Reset all components between tests."""
        from merid.resilience import reset_all_breakers, reset_all_bulkheads
        reset_all_breakers()
        reset_all_bulkheads()
        yield
        reset_all_breakers()
        reset_all_bulkheads()
    
    @pytest.mark.asyncio
    async def test_metrics_after_circuit_breaker_trip(self):
        """Metrics reflect tripped circuit breaker."""
        from merid.resilience import get_circuit_breaker
        
        cb = get_circuit_breaker("trip_test", failure_threshold=2)
        
        # Trip the breaker
        await cb.record_failure(Exception("fail1"))
        await cb.record_failure(Exception("fail2"))
        
        # Check metrics
        result = get_metrics_json()
        
        state_samples = result.get("merid_circuit_breaker_state", {}).get("samples", [])
        trip_sample = next(
            (s for s in state_samples if s["labels"].get("venue") == "trip_test"),
            None
        )
        
        assert trip_sample is not None
        assert trip_sample["value"] == 2  # 2 = open
    
    @pytest.mark.asyncio
    async def test_metrics_after_bulkhead_usage(self):
        """Metrics reflect bulkhead usage."""
        from merid.resilience import get_bulkhead
        
        bh = get_bulkhead("usage_test")
        
        # Use bulkhead
        async with bh:
            pass
        
        # Check metrics
        result = get_metrics_json()
        
        accepted_samples = result.get("merid_bulkhead_accepted_total", {}).get("samples", [])
        usage_sample = next(
            (s for s in accepted_samples if s["labels"].get("bulkhead") == "usage_test"),
            None
        )
        
        assert usage_sample is not None
        assert usage_sample["value"] >= 1
