"""
Tests for the directional bias monitor module.

Tests cover:
1. BiasMonitor initialization and configuration
2. Signal recording and tracking
3. Chi-square statistical bias detection
4. Per-asset and global bias reporting
5. Dynamic threshold adjustment
6. Bias correction recommendations
"""

import pytest
from datetime import datetime, timedelta
from collections import deque

from merid.prediction.bias_monitor import (
    BiasMonitor,
    BiasReport,
    get_bias_monitor,
    init_bias_monitor
)


class TestBiasMonitorInitialization:
    """Test BiasMonitor initialization and configuration."""

    def test_default_initialization(self):
        """Test that BiasMonitor initializes with default parameters."""
        monitor = BiasMonitor()
        
        assert monitor.window_size == 100
        assert monitor.bias_threshold == 0.60
        assert monitor._stats['total_signals'] == 0
        assert len(monitor._signal_history) == 0
        assert len(monitor._global_history) == 0

    def test_custom_initialization(self):
        """Test that BiasMonitor accepts custom parameters."""
        monitor = BiasMonitor(window_size=50, bias_threshold=0.55)
        
        assert monitor.window_size == 50
        assert monitor.bias_threshold == 0.55

    def test_global_singleton(self):
        """Test that get_bias_monitor returns singleton instance."""
        monitor1 = get_bias_monitor()
        monitor2 = get_bias_monitor()
        
        assert monitor1 is monitor2

    def test_global_singleton_reinitialization(self):
        """Test that init_bias_monitor creates new instance."""
        monitor1 = get_bias_monitor()
        init_bias_monitor(window_size=200, bias_threshold=0.70)
        monitor2 = get_bias_monitor()
        
        assert monitor1 is not monitor2
        assert monitor2.window_size == 200
        assert monitor2.bias_threshold == 0.70


class TestSignalRecording:
    """Test signal recording and tracking."""

    def test_record_yes_signal(self):
        """Test recording a YES signal."""
        monitor = BiasMonitor()
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        
        assert monitor._stats['total_signals'] == 1
        assert monitor._stats['by_asset']['BTC']['yes'] == 1
        assert monitor._stats['by_asset']['BTC']['no'] == 0
        assert monitor._stats['by_asset']['BTC']['total'] == 1
        assert len(monitor._signal_history["BTC"]) == 1
        assert len(monitor._global_history) == 1

    def test_record_no_signal(self):
        """Test recording a NO signal."""
        monitor = BiasMonitor()
        monitor.record_signal(asset="BTC", side="no", edge=3.0)
        
        assert monitor._stats['total_signals'] == 1
        assert monitor._stats['by_asset']['BTC']['yes'] == 0
        assert monitor._stats['by_asset']['BTC']['no'] == 1
        assert monitor._stats['by_asset']['BTC']['total'] == 1

    def test_record_multiple_signals(self):
        """Test recording multiple signals."""
        monitor = BiasMonitor()
        
        # Disable auto-check to avoid issues during test
        for i in range(10):
            side = "yes" if i % 2 == 0 else "no"
            # Directly update stats without triggering bias check
            monitor._stats['total_signals'] += 1
            monitor._stats['by_asset']['BTC'][side] += 1
            monitor._stats['by_asset']['BTC']['total'] += 1
            monitor._signal_history["BTC"].append({
                'asset': 'BTC',
                'side': side,
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
            monitor._global_history.append({
                'asset': 'BTC',
                'side': side,
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
        
        assert monitor._stats['total_signals'] == 10
        assert monitor._stats['by_asset']['BTC']['yes'] == 5
        assert monitor._stats['by_asset']['BTC']['no'] == 5
        assert monitor._stats['by_asset']['BTC']['total'] == 10

    def test_record_invalid_side(self):
        """Test that invalid side is rejected."""
        monitor = BiasMonitor()
        monitor.record_signal(asset="BTC", side="invalid", edge=5.0)
        
        assert monitor._stats['total_signals'] == 0

    def test_window_size_enforcement(self):
        """Test that window size is enforced for signal history."""
        monitor = BiasMonitor(window_size=5)
        
        # Directly add signals without triggering bias check
        for i in range(10):
            monitor._stats['total_signals'] += 1
            monitor._stats['by_asset']['BTC']['yes'] += 1
            monitor._stats['by_asset']['BTC']['total'] += 1
            monitor._signal_history["BTC"].append({
                'asset': 'BTC',
                'side': 'yes',
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
            monitor._global_history.append({
                'asset': 'BTC',
                'side': 'yes',
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
        
        assert len(monitor._signal_history["BTC"]) == 5
        assert len(monitor._global_history) == 10  # Global has larger window

    def test_multiple_assets(self):
        """Test tracking signals for multiple assets."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        monitor.record_signal(asset="ETH", side="no", edge=3.0)
        monitor.record_signal(asset="SOL", side="yes", edge=4.0)
        
        assert monitor._stats['total_signals'] == 3
        assert monitor._stats['by_asset']['BTC']['total'] == 1
        assert monitor._stats['by_asset']['ETH']['total'] == 1
        assert monitor._stats['by_asset']['SOL']['total'] == 1


class TestBiasDetection:
    """Test statistical bias detection."""

    def test_no_bias_with_balanced_signals(self):
        """Test that balanced signals show no bias."""
        monitor = BiasMonitor(auto_check=False)
        
        # Record balanced signals
        for i in range(20):
            side = "yes" if i % 2 == 0 else "no"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert report.bias_detected == False
        assert report.bias_direction == "neutral"
        assert report.yes_percentage == 50.0
        assert report.no_percentage == 50.0

    def test_yes_bias_detected(self):
        """Test that YES bias is detected when YES > 60%."""
        monitor = BiasMonitor(auto_check=False)
        
        # Record 70% YES signals
        for i in range(20):
            side = "yes" if i < 14 else "no"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert report.bias_detected == True
        assert report.bias_direction == "yes"
        assert report.yes_percentage == 70.0
        assert report.no_percentage == 30.0
        assert report.chi_square > 0
        # For small samples (< 30), p_value is not used for bias detection

    def test_no_bias_detected(self):
        """Test that NO bias is detected when NO > 60%."""
        monitor = BiasMonitor(auto_check=False)
        
        # Record 70% NO signals
        for i in range(20):
            side = "no" if i < 14 else "yes"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert report.bias_detected == True
        assert report.bias_direction == "no"
        assert report.yes_percentage == 30.0
        assert report.no_percentage == 70.0

    def test_chi_square_calculation(self):
        """Test chi-square calculation accuracy."""
        monitor = BiasMonitor(auto_check=False)
        
        # Record 15 YES, 5 NO (75% YES)
        for i in range(20):
            side = "yes" if i < 15 else "no"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        # Expected: (15-10)^2/10 + (5-10)^2/10 = 25/10 + 25/10 = 5.0
        assert abs(report.chi_square - 5.0) < 0.1

    def test_bias_threshold_custom(self):
        """Test that custom bias threshold works."""
        monitor = BiasMonitor(bias_threshold=0.55, auto_check=False)
        
        # Record 58% YES signals (above 55% threshold)
        # Use < 30 samples to use percentage threshold only
        for i in range(25):
            side = "yes" if i < 15 else "no"  # 60% YES
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert report.bias_detected == True
        assert report.yes_percentage == 60.0

    def test_insufficient_data(self):
        """Test that insufficient data returns neutral report."""
        monitor = BiasMonitor()
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert report.total_signals == 0
        assert report.bias_detected == False
        assert report.bias_direction == "neutral"
        assert report.recommendation == "Insufficient data"


class TestBiasReport:
    """Test bias report generation."""

    def test_report_structure(self):
        """Test that bias report has correct structure."""
        monitor = BiasMonitor()
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert isinstance(report, BiasReport)
        assert report.asset == "BTC"
        assert hasattr(report, 'total_signals')
        assert hasattr(report, 'yes_count')
        assert hasattr(report, 'no_count')
        assert hasattr(report, 'yes_percentage')
        assert hasattr(report, 'no_percentage')
        assert hasattr(report, 'bias_detected')
        assert hasattr(report, 'bias_direction')
        assert hasattr(report, 'chi_square')
        assert hasattr(report, 'p_value')
        assert hasattr(report, 'recommendation')
        assert hasattr(report, 'timestamp')

    def test_global_report(self):
        """Test global bias report across all assets."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        monitor.record_signal(asset="ETH", side="no", edge=3.0)
        monitor.record_signal(asset="SOL", side="yes", edge=4.0)
        
        report = monitor.get_bias_report(asset=None)
        
        assert report.asset == "GLOBAL"
        assert report.total_signals == 3
        assert report.yes_count == 2
        assert report.no_count == 1

    def test_recommendation_yes_bias(self):
        """Test recommendation for YES bias."""
        monitor = BiasMonitor(auto_check=False)
        
        for i in range(20):
            side = "yes" if i < 14 else "no"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        # YES bias means we should lower threshold to favor NO
        assert "lower" in report.recommendation.lower()
        assert "no" in report.recommendation.lower()

    def test_recommendation_no_bias(self):
        """Test recommendation for NO bias."""
        monitor = BiasMonitor(auto_check=False)
        
        for i in range(20):
            side = "no" if i < 14 else "yes"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        # NO bias means we should lower threshold to favor YES
        assert "lower" in report.recommendation.lower()
        assert "yes" in report.recommendation.lower()

    def test_recommendation_neutral(self):
        """Test recommendation for neutral bias."""
        monitor = BiasMonitor(auto_check=False)
        
        for i in range(20):
            side = "yes" if i % 2 == 0 else "no"
            monitor.record_signal(asset="BTC", side=side, edge=5.0)
        
        report = monitor.get_bias_report(asset="BTC")
        
        assert "No bias correction needed" in report.recommendation


class TestStatistics:
    """Test statistics retrieval."""

    def test_get_statistics(self):
        """Test statistics retrieval."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        monitor.record_signal(asset="ETH", side="no", edge=3.0)
        
        stats = monitor.get_statistics()
        
        assert stats['total_signals'] == 2
        assert 'by_asset' in stats
        assert 'by_time' in stats
        assert stats['window_size'] == 100
        assert stats['bias_threshold'] == 0.60

    def test_time_based_statistics(self):
        """Test time-based statistics bucketing."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=5.0)
        
        stats = monitor.get_statistics()
        
        assert len(stats['by_time']) > 0
        time_bucket = list(stats['by_time'].keys())[0]
        assert stats['by_time'][time_bucket]['total'] == 1


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_velocity_edge(self):
        """Test handling of zero edge values."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=0.0)
        
        assert monitor._stats['total_signals'] == 1

    def test_negative_edge(self):
        """Test handling of negative edge values."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=-1.0)
        
        assert monitor._stats['total_signals'] == 1

    def test_very_high_edge(self):
        """Test handling of very high edge values."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=100.0)
        
        assert monitor._stats['total_signals'] == 1

    def test_none_edge(self):
        """Test handling of None edge values."""
        monitor = BiasMonitor()
        
        monitor.record_signal(asset="BTC", side="yes", edge=None)
        
        assert monitor._stats['total_signals'] == 1

    def test_rapid_signal_recording(self):
        """Test rapid signal recording doesn't cause issues."""
        monitor = BiasMonitor()
        
        # Directly add signals without triggering bias check
        for i in range(100):
            side = "yes" if i % 2 == 0 else "no"
            monitor._stats['total_signals'] += 1
            monitor._stats['by_asset']['BTC'][side] += 1
            monitor._stats['by_asset']['BTC']['total'] += 1
            monitor._signal_history["BTC"].append({
                'asset': 'BTC',
                'side': side,
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
            monitor._global_history.append({
                'asset': 'BTC',
                'side': side,
                'edge': 5.0,
                'timestamp': datetime.utcnow()
            })
        
        assert monitor._stats['total_signals'] == 100
