"""Tests for monitoring/metrics.py."""
import pytest
from unittest.mock import Mock, patch
from monitoring.metrics import (
    MetricType, MetricValue, Counter, Gauge, Histogram, MetricsRegistry,
    get_metrics_registry, record_agent_observation, record_agent_vote,
    record_agent_processing_time, update_agent_trust, record_consensus_round,
    record_stream_event, record_order, update_portfolio_metrics
)


class TestMetricType:
    """Test MetricType enum."""

    def test_metric_type_values(self):
        """Test metric type enum values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"
        assert MetricType.SUMMARY.value == "summary"


class TestMetricValue:
    """Test MetricValue dataclass."""

    def test_creation(self):
        """Test MetricValue creation."""
        value = MetricValue(
            name="test_metric",
            metric_type=MetricType.COUNTER,
            value=100.0,
            labels={"label1": "value1"},
            help_text="A test metric"
        )
        assert value.name == "test_metric"
        assert value.metric_type == MetricType.COUNTER
        assert value.value == 100.0
        assert value.labels["label1"] == "value1"


class TestCounter:
    """Test Counter class."""

    def test_initialization(self):
        """Test counter initialization."""
        counter = Counter("test_counter", "Test counter", ["label1"])
        assert counter.name == "test_counter"
        assert counter.help_text == "Test counter"
        assert counter.label_names == ["label1"]

    def test_inc(self):
        """Test increment counter."""
        counter = Counter("test_counter")
        counter.inc(5.0)
        assert counter.get() == 5.0

    def test_inc_default(self):
        """Test increment counter with default value."""
        counter = Counter("test_counter")
        counter.inc()
        assert counter.get() == 1.0

    def test_inc_negative_raises(self):
        """Test that negative increment raises error."""
        counter = Counter("test_counter")
        with pytest.raises(ValueError, match="Counter can only be incremented"):
            counter.inc(-1.0)

    def test_inc_with_labels(self):
        """Test increment with labels."""
        counter = Counter("test_counter", labels=["agent_id"])
        counter.inc(1.0, {"agent_id": "agent_1"})
        counter.inc(2.0, {"agent_id": "agent_1"})
        counter.inc(3.0, {"agent_id": "agent_2"})
        
        assert counter.get({"agent_id": "agent_1"}) == 3.0
        assert counter.get({"agent_id": "agent_2"}) == 3.0

    def test_collect(self):
        """Test collect method."""
        counter = Counter("test_counter", "Test counter", ["agent_id"])
        counter.inc(1.0, {"agent_id": "agent_1"})
        
        values = counter.collect()
        assert len(values) == 1
        assert values[0].name == "test_counter"
        assert values[0].value == 1.0
        assert values[0].metric_type == MetricType.COUNTER


class TestGauge:
    """Test Gauge class."""

    def test_initialization(self):
        """Test gauge initialization."""
        gauge = Gauge("test_gauge", "Test gauge", ["label1"])
        assert gauge.name == "test_gauge"
        assert gauge.help_text == "Test gauge"

    def test_set(self):
        """Test set gauge value."""
        gauge = Gauge("test_gauge")
        gauge.set(50.0)
        assert gauge.get() == 50.0

    def test_inc(self):
        """Test increment gauge."""
        gauge = Gauge("test_gauge")
        gauge.set(10.0)
        gauge.inc(5.0)
        assert gauge.get() == 15.0

    def test_dec(self):
        """Test decrement gauge."""
        gauge = Gauge("test_gauge")
        gauge.set(10.0)
        gauge.dec(3.0)
        assert gauge.get() == 7.0

    def test_collect(self):
        """Test collect method."""
        gauge = Gauge("test_gauge", "Test gauge", ["agent_id"])
        gauge.set(42.0, {"agent_id": "agent_1"})
        
        values = gauge.collect()
        assert len(values) == 1
        assert values[0].name == "test_gauge"
        assert values[0].value == 42.0
        assert values[0].metric_type == MetricType.GAUGE


class TestHistogram:
    """Test Histogram class."""

    def test_initialization(self):
        """Test histogram initialization."""
        hist = Histogram("test_hist", "Test histogram", ["label1"])
        assert hist.name == "test_hist"
        assert len(hist.buckets) == 11  # Default buckets

    def test_observe(self):
        """Test observe value."""
        hist = Histogram("test_hist", buckets=(0.1, 0.5, 1.0, 2.0))
        hist.observe(0.3)
        hist.observe(0.8)
        hist.observe(1.5)
        
        # Check counts are tracked
        assert hist._counts[()] == 3

    def test_observe_with_labels(self):
        """Test observe with labels."""
        hist = Histogram("test_hist", labels=["agent_id"], buckets=(0.1, 0.5, 1.0))
        hist.observe(0.3, {"agent_id": "agent_1"})
        hist.observe(0.8, {"agent_id": "agent_1"})
        
        assert hist._counts[("agent_1",)] == 2

    def test_collect(self):
        """Test collect method."""
        hist = Histogram("test_hist", "Test histogram", buckets=(0.1, 0.5, 1.0))
        hist.observe(0.3)
        
        values = hist.collect()
        # Should have bucket values + sum + count
        assert len(values) > 0


class TestMetricsRegistry:
    """Test MetricsRegistry class."""

    def test_initialization(self):
        """Test registry initialization."""
        registry = MetricsRegistry()
        assert len(registry._metrics) == 0
        assert len(registry._collectors) == 0

    def test_counter_creation(self):
        """Test counter creation."""
        registry = MetricsRegistry()
        counter = registry.counter("my_counter", "My counter")
        
        assert counter.name == "my_counter"
        assert "my_counter" in registry._metrics

    def test_counter_reuse(self):
        """Test counter reuse."""
        registry = MetricsRegistry()
        counter1 = registry.counter("my_counter")
        counter2 = registry.counter("my_counter")
        
        assert counter1 is counter2

    def test_gauge_creation(self):
        """Test gauge creation."""
        registry = MetricsRegistry()
        gauge = registry.gauge("my_gauge", "My gauge")
        
        assert gauge.name == "my_gauge"
        assert "my_gauge" in registry._metrics

    def test_histogram_creation(self):
        """Test histogram creation."""
        registry = MetricsRegistry()
        hist = registry.histogram("my_hist", "My histogram")
        
        assert hist.name == "my_hist"
        assert "my_hist" in registry._metrics

    def test_register_collector(self):
        """Test custom collector registration."""
        registry = MetricsRegistry()
        
        def custom_collector():
            return [MetricValue("custom", MetricType.GAUGE, 1.0)]
        
        registry.register_collector(custom_collector)
        assert len(registry._collectors) == 1

    def test_collect_all(self):
        """Test collect_all method."""
        registry = MetricsRegistry()
        counter = registry.counter("test_counter")
        counter.inc(5.0)
        
        values = registry.collect_all()
        assert len(values) == 1
        assert values[0].value == 5.0

    def test_collect_all_with_collector(self):
        """Test collect_all with custom collector."""
        registry = MetricsRegistry()
        
        def custom_collector():
            return [MetricValue("custom", MetricType.GAUGE, 42.0)]
        
        registry.register_collector(custom_collector)
        values = registry.collect_all()
        
        assert len(values) == 1
        assert values[0].name == "custom"

    def test_export_prometheus(self):
        """Test Prometheus export."""
        registry = MetricsRegistry()
        counter = registry.counter("test_counter", "Test counter")
        counter.inc(5.0)
        
        output = registry.export_prometheus()
        assert "# HELP test_counter Test counter" in output
        assert "# TYPE test_counter counter" in output
        assert "test_counter 5.0" in output


class TestGetMetricsRegistry:
    """Test get_metrics_registry function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import monitoring.metrics as mm
        mm._metrics_registry = None

    def test_singleton(self):
        """Test get_metrics_registry returns singleton."""
        registry1 = get_metrics_registry()
        registry2 = get_metrics_registry()
        assert registry1 is registry2

    def test_initializes_default_metrics(self):
        """Test that default metrics are initialized."""
        registry = get_metrics_registry()
        
        assert "merid_agent_observations_total" in registry._metrics
        assert "merid_agent_votes_total" in registry._metrics
        assert "merid_consensus_rounds_total" in registry._metrics


class TestHelperFunctions:
    """Test metric helper functions."""

    def test_record_agent_observation(self):
        """Test record_agent_observation."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_agent_observation("agent_1")
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_agent_observations_total")
        assert counter.get({"agent_id": "agent_1"}) == 1.0

    def test_record_agent_vote(self):
        """Test record_agent_vote."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_agent_vote("agent_1", "approve")
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_agent_votes_total")
        assert counter.get({"agent_id": "agent_1", "decision": "approve"}) == 1.0

    def test_record_agent_processing_time(self):
        """Test record_agent_processing_time."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_agent_processing_time("agent_1", 0.5)
        registry = get_metrics_registry()
        hist = registry._metrics.get("merid_agent_processing_seconds")
        assert hist._counts[("agent_1",)] == 1

    def test_update_agent_trust(self):
        """Test update_agent_trust."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        update_agent_trust("agent_1", 0.95)
        registry = get_metrics_registry()
        gauge = registry._metrics.get("merid_agent_trust_score")
        assert gauge.get({"agent_id": "agent_1"}) == 0.95

    def test_record_consensus_round(self):
        """Test record_consensus_round."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_consensus_round("approved", 1.5)
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_consensus_rounds_total")
        assert counter.get({"state": "approved"}) == 1.0

    def test_record_stream_event(self):
        """Test record_stream_event."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_stream_event("stream_1", "tick")
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_stream_events_total")
        assert counter.get({"stream_id": "stream_1", "event_type": "tick"}) == 1.0

    def test_record_order(self):
        """Test record_order."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        record_order("buy", "filled")
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_orders_total")
        assert counter.get({"side": "buy", "status": "filled"}) == 1.0

    def test_update_portfolio_metrics(self):
        """Test update_portfolio_metrics."""
        import monitoring.metrics as mm
        mm._metrics_registry = None
        
        update_portfolio_metrics(100000.0, 5000.0, 5)
        registry = get_metrics_registry()
        
        equity = registry._metrics.get("merid_portfolio_equity")
        pnl = registry._metrics.get("merid_portfolio_unrealized_pnl")
        positions = registry._metrics.get("merid_positions_count")
        
        assert equity.get() == 100000.0
        assert pnl.get() == 5000.0
        assert positions.get() == 5
