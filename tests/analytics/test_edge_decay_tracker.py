"""Tests for Edge Decay Tracker."""

import pytest
from datetime import datetime, timezone, timedelta
from analytics.edge_decay_tracker import (
    EdgeDecayTracker,
    get_edge_decay_tracker,
    EdgeObservation,
    EdgeMetrics,
    EdgeStatus,
    EdgeDecayConfig,
    DecayAlert
)


class TestEdgeDecayTracker:
    """Test suite for EdgeDecayTracker."""
    
    def test_singleton(self):
        """Test that EdgeDecayTracker is a singleton."""
        tracker1 = get_edge_decay_tracker()
        tracker2 = get_edge_decay_tracker()
        assert tracker1 is tracker2
    
    def test_initialization(self):
        """Test tracker initialization."""
        tracker = get_edge_decay_tracker()
        assert tracker is not None
    
    def test_get_config(self):
        """Test configuration retrieval."""
        tracker = get_edge_decay_tracker()
        config = tracker.get_config()
        assert isinstance(config, EdgeDecayConfig)
        assert config.ema_span == 20
    
    def test_record_edge(self):
        """Test edge recording."""
        tracker = get_edge_decay_tracker()
        tracker.record_edge(
            strategy="momentum",
            asset="BTC",
            expected_edge=0.05,
            realized_edge=0.03
        )
        # Should not raise an exception
    
    def test_get_current_edge_insufficient_data(self):
        """Test edge retrieval with insufficient data."""
        tracker = get_edge_decay_tracker()
        edge = tracker.get_current_edge("momentum", "BTC")
        assert edge is None  # Should return None with insufficient data
    
    def test_get_current_edge_with_data(self):
        """Test edge retrieval with sufficient data."""
        tracker = get_edge_decay_tracker()
        # Record multiple observations
        for i in range(20):
            tracker.record_edge(
                strategy="momentum",
                asset="BTC",
                expected_edge=0.05,
                realized_edge=0.03 + (i * 0.001)
            )
        
        edge = tracker.get_current_edge("momentum", "BTC")
        assert edge is not None
        assert isinstance(edge, float)
    
    def test_get_edge_metrics(self):
        """Test edge metrics calculation."""
        tracker = get_edge_decay_tracker()
        # Record observations
        for i in range(20):
            tracker.record_edge(
                strategy="momentum",
                asset="BTC",
                expected_edge=0.05,
                realized_edge=0.03 + (i * 0.001)
            )
        
        metrics = tracker.get_edge_metrics("momentum", "BTC")
        assert metrics is not None
        assert isinstance(metrics, EdgeMetrics)
        assert metrics.strategy == "momentum"
        assert metrics.asset == "BTC"
        assert metrics.observation_count >= 10
    
    def test_check_decay_status(self):
        """Test decay status checking."""
        tracker = get_edge_decay_tracker()
        # Record observations
        for i in range(20):
            tracker.record_edge(
                strategy="momentum",
                asset="BTC",
                expected_edge=0.05,
                realized_edge=0.03 + (i * 0.001)
            )
        
        status = tracker.check_decay_status("momentum", "BTC")
        assert status is not None
        assert isinstance(status, EdgeStatus)
    
    def test_get_recent_alerts(self):
        """Test recent alerts retrieval."""
        tracker = get_edge_decay_tracker()
        alerts = tracker.get_recent_alerts(limit=10)
        assert isinstance(alerts, list)
    
    def test_get_summary(self):
        """Test summary generation."""
        tracker = get_edge_decay_tracker()
        # Record some observations
        for i in range(20):
            tracker.record_edge(
                strategy="momentum",
                asset="BTC",
                expected_edge=0.05,
                realized_edge=0.03 + (i * 0.001)
            )
        
        summary = tracker.get_summary()
        assert "total_observations" in summary
        assert "tracked_pairs" in summary
        assert "pair_summaries" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
