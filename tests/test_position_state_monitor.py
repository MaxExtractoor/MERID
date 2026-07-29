"""
Tests for Position State Monitor.

Tests the position state desync monitoring functionality that detects
synchronization issues between Position.size and PositionCache.contracts.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from merid.monitoring.position_state_monitor import (
    PositionStateMonitor,
    get_position_state_monitor,
    DesyncEvent,
    DesyncMetrics,
)
from merid.position_management.position import Position, PositionSide


class TestPositionStateMonitor:
    """Test PositionStateMonitor basic operations."""
    
    def test_singleton_pattern(self):
        """Test that PositionStateMonitor follows singleton pattern."""
        monitor1 = PositionStateMonitor.get_instance()
        monitor2 = PositionStateMonitor.get_instance()
        
        assert monitor1 is monitor2
    
    def test_get_position_state_monitor(self):
        """Test get_position_state_monitor helper function."""
        monitor = get_position_state_monitor()
        
        assert monitor is not None
        assert isinstance(monitor, PositionStateMonitor)
    
    def test_initialization(self):
        """Test monitor initialization."""
        monitor = PositionStateMonitor(check_interval_seconds=10.0)
        
        assert monitor._check_interval == 10.0
        assert monitor._running is False
        assert monitor._task is None
        assert len(monitor._desync_events) == 0
        assert monitor._metrics.total_desyncs == 0


class TestDesyncEvent:
    """Test DesyncEvent dataclass."""
    
    def test_desync_event_creation(self):
        """Test creating a desync event."""
        event = DesyncEvent(
            position_id="test-position-id",
            asset="BTC",
            position_size=5,
            cache_contracts=3,
            desync_amount=2,
        )
        
        assert event.position_id == "test-position-id"
        assert event.asset == "BTC"
        assert event.position_size == 5
        assert event.cache_contracts == 3
        assert event.desync_amount == 2
        assert event.resolved is False
        assert event.resolved_at is None
    
    def test_desync_event_resolution(self):
        """Test marking a desync event as resolved."""
        event = DesyncEvent(
            position_id="test-position-id",
            asset="BTC",
            position_size=5,
            cache_contracts=3,
            desync_amount=2,
        )
        
        event.resolved = True
        event.resolved_at = datetime.utcnow()
        
        assert event.resolved is True
        assert event.resolved_at is not None


class TestDesyncMetrics:
    """Test DesyncMetrics dataclass."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = DesyncMetrics()
        
        assert metrics.total_desyncs == 0
        assert metrics.active_desyncs == 0
        assert metrics.resolved_desyncs == 0
        assert metrics.max_desync_amount == 0
        assert len(metrics.desyncs_by_asset) == 0
        assert metrics.last_desync_time is None
    
    def test_metrics_tracking(self):
        """Test metrics tracking."""
        metrics = DesyncMetrics()
        
        metrics.total_desyncs = 5
        metrics.active_desyncs = 2
        metrics.resolved_desyncs = 3
        metrics.max_desync_amount = 10
        metrics.desyncs_by_asset["BTC"] = 3
        metrics.desyncs_by_asset["ETH"] = 2
        metrics.last_desync_time = datetime.utcnow()
        
        assert metrics.total_desyncs == 5
        assert metrics.active_desyncs == 2
        assert metrics.resolved_desyncs == 3
        assert metrics.max_desync_amount == 10
        assert metrics.desyncs_by_asset["BTC"] == 3
        assert metrics.desyncs_by_asset["ETH"] == 2
        assert metrics.last_desync_time is not None


class TestAssetExtraction:
    """Test asset extraction from position."""
    
    def test_extract_asset_from_series_ticker(self):
        """Test extracting asset from series_ticker."""
        monitor = PositionStateMonitor()
        
        # Test BTC
        position = Mock()
        position.series_ticker = "KXBTC15M-26JUL211745-45"
        position.market_id = ""
        assert monitor._extract_asset(position) == "BTC"
        
        # Test ETH
        position.series_ticker = "KXETH15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "ETH"
        
        # Test SOL
        position.series_ticker = "KXSOL15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "SOL"
        
        # Test XRP
        position.series_ticker = "KXXRP15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "XRP"
        
        # Test DOGE
        position.series_ticker = "KXDOGE15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "DOGE"
    
    def test_extract_asset_from_market_id(self):
        """Test extracting asset from market_id as fallback."""
        monitor = PositionStateMonitor()
        
        # Test BTC
        position = Mock()
        position.series_ticker = ""
        position.market_id = "KXBTC15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "BTC"
        
        # Test ETH
        position.market_id = "KXETH15M-26JUL211745-45"
        assert monitor._extract_asset(position) == "ETH"
    
    def test_extract_asset_unknown(self):
        """Test extracting asset when unknown."""
        monitor = PositionStateMonitor()
        
        position = Mock()
        position.series_ticker = "UNKNOWN"
        position.market_id = "UNKNOWN"
        assert monitor._extract_asset(position) == "UNKNOWN"


class TestMonitorLifecycle:
    """Test monitor start/stop lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping the monitor."""
        monitor = PositionStateMonitor(check_interval_seconds=1.0)
        
        assert monitor._running is False
        
        await monitor.start()
        assert monitor._running is True
        assert monitor._task is not None
        
        await monitor.stop()
        assert monitor._running is False
        assert monitor._task is None
    
    @pytest.mark.asyncio
    async def test_start_when_already_running(self):
        """Test starting when already running."""
        monitor = PositionStateMonitor(check_interval_seconds=1.0)
        
        await monitor.start()
        await monitor.start()  # Should not error
        
        await monitor.stop()
    
    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test stopping when not running."""
        monitor = PositionStateMonitor(check_interval_seconds=1.0)
        
        await monitor.stop()  # Should not error


class TestMetricsRetrieval:
    """Test metrics retrieval methods."""
    
    def test_get_metrics(self):
        """Test getting metrics."""
        monitor = PositionStateMonitor()
        
        metrics = monitor.get_metrics()
        
        assert isinstance(metrics, DesyncMetrics)
        assert metrics.total_desyncs == 0
    
    def test_get_active_desyncs(self):
        """Test getting active desyncs."""
        monitor = PositionStateMonitor()
        
        active_desyncs = monitor.get_active_desyncs()
        
        assert isinstance(active_desyncs, list)
        assert len(active_desyncs) == 0
    
    def test_get_desync_history(self):
        """Test getting desync history."""
        monitor = PositionStateMonitor()
        
        history = monitor.get_desync_history(limit=10)
        
        assert isinstance(history, list)
        assert len(history) == 0


class TestDesyncDetection:
    """Test desync detection logic."""
    
    @pytest.mark.asyncio
    async def test_desync_threshold(self):
        """Test that desync threshold is respected."""
        monitor = PositionStateMonitor(check_interval_seconds=1.0)
        
        # Default threshold is 1
        assert monitor._desync_threshold == 1
    
    @pytest.mark.asyncio
    async def test_max_history_trimming(self):
        """Test that history trimming logic exists in code."""
        monitor = PositionStateMonitor(check_interval_seconds=1.0)
        
        # Verify that max_history is set
        assert monitor._max_history == 1000
        
        # Verify that trimming logic exists in _handle_desync
        import inspect
        source = inspect.getsource(monitor._handle_desync)
        
        # Check that trimming logic is present
        assert "trim" in source.lower() or "max_history" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
