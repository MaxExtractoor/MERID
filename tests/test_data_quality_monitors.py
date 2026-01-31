"""
Tests for Phase 21 Data Quality & Latency Observability monitors.

Validates clock sync, feed parity, and lag metrics collection.
"""

import pytest
import time
from datetime import datetime, timedelta

from observability.clock_sync_monitor import (
    ClockSyncMonitor,
    get_clock_sync_monitor,
)
from observability.feed_parity_checker import (
    FeedParityChecker,
    FeedSnapshot,
    get_feed_parity_checker,
)
from observability.lag_metrics import (
    LagMetricsCollector,
    get_lag_metrics_collector,
)


pytestmark = pytest.mark.safety_critical


class TestClockSyncMonitor:
    """Test clock synchronization monitoring."""
    
    def test_measure_drift_within_threshold(self):
        """Test drift measurement within acceptable threshold."""
        monitor = ClockSyncMonitor(drift_threshold_ms=100.0)
        
        now = time.time()
        measurement = monitor.measure_drift(
            source="test_exchange",
            source_timestamp=now - 0.05,  # 50ms drift
            local_timestamp=now,
        )
        
        assert measurement.drift_ms == pytest.approx(50.0, abs=1.0)
        assert len(monitor.get_recent_alerts()) == 0
    
    def test_measure_drift_exceeds_threshold(self):
        """Test drift measurement exceeding threshold triggers alert."""
        monitor = ClockSyncMonitor(drift_threshold_ms=100.0)
        
        now = time.time()
        measurement = monitor.measure_drift(
            source="slow_exchange",
            source_timestamp=now - 0.2,  # 200ms drift
            local_timestamp=now,
        )
        
        assert measurement.drift_ms == pytest.approx(200.0, abs=1.0)
        alerts = monitor.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0].source == "slow_exchange"
        assert alerts[0].severity in ["medium", "high"]
    
    def test_validate_timestamp_valid(self):
        """Test timestamp validation for valid timestamp."""
        monitor = ClockSyncMonitor()
        
        now = time.time()
        assert monitor.validate_timestamp(now - 10.0) is True
        assert monitor.validate_timestamp(now) is True
    
    def test_validate_timestamp_too_old(self):
        """Test timestamp validation rejects old timestamps."""
        monitor = ClockSyncMonitor()
        
        old_timestamp = time.time() - 120.0  # 2 minutes old
        assert monitor.validate_timestamp(old_timestamp, max_age_seconds=60.0) is False
    
    def test_validate_timestamp_future(self):
        """Test timestamp validation rejects future timestamps."""
        monitor = ClockSyncMonitor()
        
        future_timestamp = time.time() + 10.0
        assert monitor.validate_timestamp(future_timestamp, max_future_seconds=5.0) is False
    
    def test_get_sync_status(self):
        """Test sync status reporting."""
        monitor = ClockSyncMonitor()
        
        now = time.time()
        monitor.measure_drift("exchange_a", now - 0.03, now)
        monitor.measure_drift("exchange_b", now - 0.07, now)
        
        status = monitor.get_sync_status()
        assert status["sources_tracked"] == 2
        assert status["avg_drift_ms"] > 0
        assert status["total_measurements"] == 2


class TestFeedParityChecker:
    """Test feed parity checking across venues."""
    
    def test_ingest_snapshot(self):
        """Test ingesting market data snapshots."""
        checker = FeedParityChecker()
        
        snapshot = FeedSnapshot(
            venue="binance",
            symbol="BTC/USDT",
            price=50000.0,
            volume=100.0,
            timestamp=time.time(),
        )
        
        checker.ingest_snapshot(snapshot)
        assert "BTC/USDT" in checker._snapshots
        assert "binance" in checker._snapshots["BTC/USDT"]
    
    def test_check_parity_within_threshold(self):
        """Test parity check with prices within threshold."""
        checker = FeedParityChecker(divergence_threshold_pct=0.5)
        
        now = time.time()
        checker.ingest_snapshot(FeedSnapshot("binance", "BTC/USDT", 50000.0, 100.0, now))
        checker.ingest_snapshot(FeedSnapshot("coinbase", "BTC/USDT", 50100.0, 100.0, now))
        
        violation = checker.check_parity("BTC/USDT")
        assert violation is None  # 0.2% divergence is within 0.5% threshold
    
    def test_check_parity_exceeds_threshold(self):
        """Test parity check with prices exceeding threshold."""
        checker = FeedParityChecker(divergence_threshold_pct=0.5)
        
        now = time.time()
        checker.ingest_snapshot(FeedSnapshot("binance", "BTC/USDT", 50000.0, 100.0, now))
        checker.ingest_snapshot(FeedSnapshot("coinbase", "BTC/USDT", 50500.0, 100.0, now))
        
        violation = checker.check_parity("BTC/USDT")
        assert violation is not None
        assert violation.price_divergence_pct == pytest.approx(1.0, abs=0.1)
        assert violation.severity in ["medium", "high"]
    
    def test_check_missing_symbols(self):
        """Test detection of symbols missing from some venues."""
        checker = FeedParityChecker()
        
        now = time.time()
        checker.ingest_snapshot(FeedSnapshot("binance", "BTC/USDT", 50000.0, 100.0, now))
        checker.ingest_snapshot(FeedSnapshot("binance", "ETH/USDT", 3000.0, 100.0, now))
        checker.ingest_snapshot(FeedSnapshot("coinbase", "BTC/USDT", 50000.0, 100.0, now))
        
        missing = checker.check_missing_symbols()
        assert "coinbase" in missing
        assert "ETH/USDT" in missing["coinbase"]
    
    def test_check_stale_data(self):
        """Test detection of stale data."""
        checker = FeedParityChecker()
        
        old_timestamp = time.time() - 120.0  # 2 minutes old
        checker.ingest_snapshot(FeedSnapshot("binance", "BTC/USDT", 50000.0, 100.0, old_timestamp))
        
        stale = checker.check_stale_data(max_age_seconds=60.0)
        assert "binance" in stale
        assert any("BTC/USDT" in item for item in stale["binance"])
    
    def test_get_parity_status(self):
        """Test parity status reporting."""
        checker = FeedParityChecker()
        
        now = time.time()
        checker.ingest_snapshot(FeedSnapshot("binance", "BTC/USDT", 50000.0, 100.0, now))
        checker.ingest_snapshot(FeedSnapshot("coinbase", "BTC/USDT", 50000.0, 100.0, now))
        
        status = checker.get_parity_status()
        assert status["symbols_tracked"] == 1
        assert status["venues_tracked"] == 2


class TestLagMetricsCollector:
    """Test lag metrics collection."""
    
    def test_record_lag_within_threshold(self):
        """Test recording lag within threshold."""
        collector = LagMetricsCollector()
        
        start = time.time()
        time.sleep(0.01)  # 10ms
        
        measurement = collector.record_lag(
            stage="market_data_ingestion",
            operation="fetch_orderbook",
            start_time=start,
        )
        
        assert measurement.lag_ms >= 10.0
        assert len(collector.get_recent_alerts()) == 0
    
    def test_record_lag_exceeds_threshold(self):
        """Lag >= threshold (in µs) deterministically triggers alert."""
        collector = LagMetricsCollector()
        collector.set_threshold("test_stage", 50.0)
        
        start = time.time() - 0.1  # Simulate 100ms lag using float subtraction
        
        measurement = collector.record_lag(
            stage="test_stage",
            operation="slow_operation",
            start_time=start,
        )
        
        assert measurement.lag_ms >= 100.0
        alerts = collector.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0].stage == "test_stage"
    
    def test_get_stage_stats(self):
        """Test stage statistics calculation."""
        collector = LagMetricsCollector()
        
        start = time.time()
        for i in range(10):
            collector.record_lag(
                stage="test_stage",
                operation="test_op",
                start_time=start - (0.01 * i),
            )
        
        stats = collector.get_stage_stats("test_stage")
        assert stats["count"] == 10
        assert stats["avg_ms"] > 0
        assert stats["p50_ms"] > 0
    
    def test_set_threshold(self):
        """Test setting custom threshold."""
        collector = LagMetricsCollector()
        
        collector.set_threshold("custom_stage", 200.0)
        assert collector._stage_thresholds["custom_stage"] == 200.0
    
    def test_get_lag_summary(self):
        """Test lag summary reporting."""
        collector = LagMetricsCollector()
        
        start = time.time()
        collector.record_lag("market_data_ingestion", "test", start - 0.05)
        
        summary = collector.get_lag_summary()
        assert summary["total_measurements"] > 0
        assert "stage_thresholds" in summary
        assert "stage_stats" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
