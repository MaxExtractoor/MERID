"""
SLO Monitor Tests
Tests for Service Level Objective monitoring and compliance tracking.
"""

import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from core.slo_monitor import (
    SLOMonitor, SLOMetric, SLOStatus, SLOResult,
    get_slo_monitor, track_slo
)


class TestSLOMonitor:
    """Test SLO monitoring functionality."""
    
    def setup_method(self):
        """Setup fresh SLO monitor for each test."""
        self.monitor = SLOMonitor()
    
    def test_initialization(self):
        """Test SLO monitor initialization with default metrics."""
        assert len(self.monitor.slos) == 7  # Should have 7 default SLOs
        
        # Check essential SLOs exist
        essential_slos = [
            "api_availability", "order_success_rate", 
            "market_data_freshness", "system_health"
        ]
        for slo_name in essential_slos:
            assert slo_name in self.monitor.slos
            assert self.monitor.slos[slo_name].target_percent > 0
    
    def test_record_metric(self):
        """Test recording metrics for SLO tracking."""
        # Record a successful metric
        self.monitor.record_metric("api_availability", True, 150.0, {
            "endpoint": "/api/v1/kalshi/markets"
        })
        
        # Verify metric was recorded
        assert "api_availability" in self.monitor.metrics_buffer
        assert len(self.monitor.metrics_buffer["api_availability"]) == 1
        
        metric = self.monitor.metrics_buffer["api_availability"][0]
        assert metric["success"] is True
        assert metric["latency_ms"] == 150.0
        assert metric["metadata"]["endpoint"] == "/api/v1/kalshi/markets"
    
    def test_record_metric_failure(self):
        """Test recording failed metrics."""
        self.monitor.record_metric("order_success_rate", False, 2500.0, {
            "ticker": "KXBTCD-25JUN-T100000",
            "reason": "kill_switch"
        })
        
        metrics = self.monitor.metrics_buffer["order_success_rate"]
        assert len(metrics) == 1
        assert metrics[0]["success"] is False
        assert metrics[0]["latency_ms"] == 2500.0
    
    def test_evaluate_slo_compliant(self):
        """Test SLO evaluation when compliant."""
        # Record metrics with 100% success rate
        for i in range(10):
            self.monitor.record_metric("api_availability", True, 100.0)
        
        result = self.monitor.evaluate_slo("api_availability")
        
        assert result.slo_name == "api_availability"
        assert result.status == SLOStatus.COMPLIANT
        assert result.success_rate == 100.0
        assert result.success_count == 10
        assert result.total_count == 10
    
    def test_evaluate_slo_warning(self):
        """Test SLO evaluation when in warning range."""
        # Record metrics with 95% success rate (target 99.9%)
        for i in range(20):
            success = i < 19  # 19/20 = 95%
            self.monitor.record_metric("api_availability", success, 100.0)
        
        result = self.monitor.evaluate_slo("api_availability")
        
        assert result.status == SLOStatus.WARNING
        assert result.success_rate == 95.0
    
    def test_evaluate_slo_violating(self):
        """Test SLO evaluation when violating."""
        # Record metrics with 85% success rate
        for i in range(20):
            success = i < 17  # 17/20 = 85%
            self.monitor.record_metric("order_success_rate", success, 200.0)
        
        result = self.monitor.evaluate_slo("order_success_rate")
        
        assert result.status == SLOStatus.VIOLATING
        assert result.success_rate == 85.0
        assert len(result.violations) == 3  # 3 failures
    
    def test_evaluate_slo_no_metrics(self):
        """Test SLO evaluation with no recorded metrics."""
        result = self.monitor.evaluate_slo("api_availability")
        
        assert result.status == SLOStatus.UNKNOWN
        assert result.success_rate == 0.0
        assert result.success_count == 0
        assert result.total_count == 0
    
    def test_evaluate_all_slos(self):
        """Test evaluating all SLOs at once."""
        # Record some metrics
        self.monitor.record_metric("api_availability", True, 100.0)
        self.monitor.record_metric("order_success_rate", False, 500.0)
        self.monitor.record_metric("system_health", True, 50.0)
        
        results = self.monitor.evaluate_all_slos()
        
        assert len(results) == len(self.monitor.slos)
        assert "api_availability" in results
        assert "order_success_rate" in results
        assert "system_health" in results
    
    def test_get_overall_status_compliant(self):
        """Test overall status when all SLOs compliant."""
        # Record successful metrics for all SLOs
        for slo_name in self.monitor.slos:
            for i in range(5):
                self.monitor.record_metric(slo_name, True, 100.0)
        
        status = self.monitor.get_overall_status()
        assert status == SLOStatus.COMPLIANT
    
    def test_get_overall_status_violating(self):
        """Test overall status when any SLO violating."""
        # Make one SLO violate
        for i in range(10):
            success = i < 5  # 50% success rate
            self.monitor.record_metric("api_availability", success, 100.0)
        
        status = self.monitor.get_overall_status()
        assert status == SLOStatus.VIOLATING
    
    def test_get_slo_summary(self):
        """Test comprehensive SLO summary."""
        # Record some metrics
        self.monitor.record_metric("api_availability", True, 100.0)
        self.monitor.record_metric("order_success_rate", False, 500.0, {
            "ticker": "KXBTCD-25JUN-T100000"
        })
        
        summary = self.monitor.get_slo_summary()
        
        assert "overall_status" in summary
        assert "evaluation_time" in summary
        assert "slos" in summary
        assert "recent_violations" in summary
        
        # Check SLO details
        assert "api_availability" in summary["slos"]
        api_slo = summary["slos"]["api_availability"]
        assert "status" in api_slo
        assert "success_rate" in api_slo
        assert "target" in api_slo
    
    def test_unknown_slo_error(self):
        """Test error handling for unknown SLO names."""
        with pytest.raises(ValueError, match="Unknown SLO"):
            self.monitor.evaluate_slo("unknown_slo")
    
    def test_metrics_buffer_cleanup(self):
        """Test that metrics buffer doesn't grow indefinitely."""
        # Record more than the buffer limit
        for i in range(1050):
            self.monitor.record_metric("api_availability", True, 100.0)
        
        # Buffer should be trimmed to 1000 entries
        assert len(self.monitor.metrics_buffer["api_availability"]) == 1000


class TestSLODecorators:
    """Test SLO tracking decorators."""
    
    def test_track_slo_decorator_success(self):
        """Test SLO tracking decorator for successful function."""
        @track_slo("test_function", True)
        def successful_function():
            return "success"
        
        result = successful_function()
        
        assert result == "success"
        
        # Check metric was recorded
        monitor = get_slo_monitor()
        assert "test_function" in monitor.metrics_buffer
        metrics = monitor.metrics_buffer["test_function"]
        assert len(metrics) == 1
        assert metrics[0]["success"] is True
        assert "latency_ms" in metrics[0]
    
    def test_track_slo_decorator_failure(self):
        """Test SLO tracking decorator for failed function."""
        @track_slo("test_function", True)
        def failing_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError, match="Test error"):
            failing_function()
        
        # Check metric was recorded as failure
        monitor = get_slo_monitor()
        assert "test_function" in monitor.metrics_buffer
        metrics = monitor.metrics_buffer["test_function"]
        assert len(metrics) == 1
        assert metrics[0]["success"] is False
        assert metrics[0]["metadata"]["error"] == "Test error"


class TestSLOIntegration:
    """Test SLO monitor integration scenarios."""
    
    def test_order_router_scenario(self):
        """Test SLO tracking for order router scenario."""
        monitor = SLOMonitor()
        
        # Simulate successful order
        monitor.record_metric("order_success_rate", True, 1200.0, {
            "ticker": "KXBTCD-25JUN-T100000",
            "status": "filled_live",
            "mode": "live"
        })
        
        # Simulate rejected order
        monitor.record_metric("order_success_rate", False, 800.0, {
            "ticker": "KXBTCD-25JUN-T100000",
            "reason": "kill_switch",
            "mode": "live"
        })
        
        result = monitor.evaluate_slo("order_success_rate")
        
        assert result.success_rate == 50.0  # 1 success, 1 failure
        assert result.status == SLOStatus.VIOLATING  # Below 99.5% target
        assert len(result.violations) == 1
    
    def test_api_latency_scenario(self):
        """Test API latency SLO tracking."""
        monitor = SLOMonitor()
        
        # Record various latencies
        latencies = [50, 100, 150, 200, 300, 450, 600, 800]  # ms
        
        for latency in latencies:
            # P99 latency SLO: < 500ms for 95% of requests
            success = latency < 500
            monitor.record_metric("api_latency_p99", success, latency, {
                "endpoint": "/api/v1/kalshi/markets"
            })
        
        result = monitor.evaluate_slo("api_latency_p99")
        
        # 6/8 = 75% < 500ms, which is below 95% target
        assert result.success_rate == 75.0
        assert result.status == SLOStatus.VIOLATING
        assert len(result.violations) == 2  # 2 requests > 500ms
    
    def test_market_data_freshness_scenario(self):
        """Test market data freshness SLO."""
        monitor = SLOMonitor()
        
        # Simulate data freshness checks
        freshness_times = [2.1, 3.5, 4.8, 5.2, 6.1, 7.5]  # seconds
        
        for freshness_time in freshness_times:
            # Freshness SLO: < 5s for 98% of checks
            success = freshness_time < 5.0
            monitor.record_metric("market_data_freshness", success, 
                                freshness_time * 1000,  # Convert to ms
                                {"symbol": "KXBTCD-25JUN-T100000"})
        
        result = monitor.evaluate_slo("market_data_freshness")
        
        # 3/6 = 50% < 5s, violating 98% target
        assert result.success_rate == 50.0
        assert result.status == SLOStatus.VIOLATING
        assert len(result.violations) == 3


class TestGlobalSLOMonitor:
    """Test global SLO monitor instance."""
    
    def test_get_slo_monitor_singleton(self):
        """Test that get_slo_monitor returns the same instance."""
        monitor1 = get_slo_monitor()
        monitor2 = get_slo_monitor()
        
        assert monitor1 is monitor2
        assert isinstance(monitor1, SLOMonitor)
    
    def test_global_monitor_persistence(self):
        """Test that global monitor persists metrics across calls."""
        monitor = get_slo_monitor()
        
        # Record a metric
        monitor.record_metric("test_persistence", True, 100.0)
        
        # Get monitor again and verify metric persists
        monitor2 = get_slo_monitor()
        assert "test_persistence" in monitor2.metrics_buffer
        assert len(monitor2.metrics_buffer["test_persistence"]) == 1


if __name__ == "__main__":
    pytest.main([__file__])
