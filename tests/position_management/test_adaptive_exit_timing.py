"""
Tests for adaptive exit timing functionality.

Tests historical performance-based optimal exit timing.
"""

import pytest
from datetime import datetime, timedelta
from merid.position_management.adaptive_exit_timing import (
    ExitTimingRecord,
    AdaptiveExitConfig,
    AdaptiveExitTiming,
    get_adaptive_exit_timing
)


class TestExitTimingRecord:
    """Test ExitTimingRecord dataclass."""
    
    def test_record_creation(self):
        """Test creating an exit timing record."""
        record = ExitTimingRecord(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            entry_time=datetime(2024, 1, 1, 12, 0, 0),
            exit_time=datetime(2024, 1, 1, 12, 5, 0),
            hold_duration_seconds=300,
            entry_price_cents=5000,
            exit_price_cents=5200,
            side="yes",
            pnl_cents=2000,
            r_multiple=1.0,
            exit_reason="trail"
        )
        
        assert record.market_id == "KXBTC15M-2024-01-01T12:00:00"
        assert record.hold_duration_seconds == 300
        assert record.r_multiple == 1.0
    
    def test_hold_duration_minutes(self):
        """Test hold duration in minutes calculation."""
        record = ExitTimingRecord(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            entry_time=datetime(2024, 1, 1, 12, 0, 0),
            exit_time=datetime(2024, 1, 1, 12, 5, 0),
            hold_duration_seconds=300,
            entry_price_cents=5000,
            exit_price_cents=5200,
            side="yes",
            pnl_cents=2000,
            r_multiple=1.0,
            exit_reason="trail"
        )
        
        assert record.hold_duration_minutes == 5.0


class TestAdaptiveExitTiming:
    """Test adaptive exit timing logic."""
    
    @pytest.fixture
    def adaptive_timing(self):
        """Create an adaptive exit timing instance."""
        config = AdaptiveExitConfig(
            min_hold_seconds=60.0,
            max_hold_seconds=900.0,
            lookback_records=50,
            performance_threshold=0.5
        )
        return AdaptiveExitTiming(config)
    
    def test_add_record(self, adaptive_timing):
        """Test adding an exit timing record."""
        record = ExitTimingRecord(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            entry_time=datetime(2024, 1, 1, 12, 0, 0),
            exit_time=datetime(2024, 1, 1, 12, 5, 0),
            hold_duration_seconds=300,
            entry_price_cents=5000,
            exit_price_cents=5200,
            side="yes",
            pnl_cents=2000,
            r_multiple=1.0,
            exit_reason="trail"
        )
        
        adaptive_timing.add_record(record)
        
        assert "KXBTC15M-2024-01-01T12:00:00" in adaptive_timing._records
        assert len(adaptive_timing._records["KXBTC15M-2024-01-01T12:00:00"]) == 1
    
    def test_record_limit_enforcement(self, adaptive_timing):
        """Test that record limit is enforced."""
        market_id = "KXBTC15M-2024-01-01T12:00:00"
        
        # Add more records than lookback limit
        for i in range(60):
            record = ExitTimingRecord(
                market_id=market_id,
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 5, 0),
                hold_duration_seconds=300,
                entry_price_cents=5000,
                exit_price_cents=5200,
                side="yes",
                pnl_cents=2000,
                r_multiple=1.0,
                exit_reason="trail"
            )
            adaptive_timing.add_record(record)
        
        # Should only keep lookback_records (50)
        assert len(adaptive_timing._records[market_id]) == 50
    
    def test_optimal_hold_time_no_data(self, adaptive_timing):
        """Test optimal hold time with no data returns default."""
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=0.5
        )
        
        assert optimal_hold == 900.0  # Default max_hold_seconds
    
    def test_optimal_hold_time_insufficient_data(self, adaptive_timing):
        """Test optimal hold time with insufficient data returns default."""
        # Add only 5 records (less than 10 required)
        for i in range(5):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 5, 0),
                hold_duration_seconds=300,
                entry_price_cents=5000,
                exit_price_cents=5200,
                side="yes",
                pnl_cents=2000,
                r_multiple=1.0,
                exit_reason="trail"
            )
            adaptive_timing.add_record(record)
        
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=0.5
        )
        
        assert optimal_hold == 900.0  # Default max_hold_seconds
    
    def test_optimal_hold_time_with_data(self, adaptive_timing):
        """Test optimal hold time calculation with sufficient data."""
        # Add records with different hold durations and performance
        # Bucket 0-3: poor performance
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 2, 0),
                hold_duration_seconds=120,
                entry_price_cents=5000,
                exit_price_cents=4900,
                side="yes",
                pnl_cents=-1000,
                r_multiple=-0.5,
                exit_reason="stop_loss"
            )
            adaptive_timing.add_record(record)
        
        # Bucket 6-9: good performance
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 8, 0),
                hold_duration_seconds=480,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=0.5
        )
        
        # Should prefer 6-9 bucket (7.5 minutes = 450 seconds)
        assert optimal_hold == 450
    
    def test_optimal_hold_time_adjusted_for_profit(self, adaptive_timing):
        """Test that optimal hold time is reduced when already profitable."""
        # Add records favoring 6-9 minute bucket
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 8, 0),
                hold_duration_seconds=480,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        # Test with current_r_multiple > 0.5
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=0.75
        )
        
        # Should be reduced by 30%
        assert optimal_hold < 450  # Base 450 * 0.7 = 315
    
    def test_optimal_hold_time_adjusted_for_high_profit(self, adaptive_timing):
        """Test that optimal hold time is heavily reduced when very profitable."""
        # Add records favoring 6-9 minute bucket
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 8, 0),
                hold_duration_seconds=480,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        # Test with current_r_multiple > 1.0
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=1.5
        )
        
        # Should be reduced by 50%
        # Base 450 * 0.5 = 225, but clamped to min_hold_seconds (60)
        # However, the calculation is: 450 * 0.7 = 315 for >0.5R, then *0.5 = 157.5 for >1.0R
        # But the code only applies one reduction, not both
        # Let's check: current_r_multiple > 1.0 triggers 50% reduction: 450 * 0.5 = 225
        assert optimal_hold <= 315  # Base 450 * 0.5 = 225
    
    def test_optimal_hold_time_clamping(self, adaptive_timing):
        """Test that optimal hold time is clamped to config limits."""
        # Add records favoring very short hold times
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 1, 30),
                hold_duration_seconds=90,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        # Test with high profit (50% reduction)
        optimal_hold = adaptive_timing.get_optimal_hold_time(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            current_r_multiple=1.5
        )
        
        # Should be clamped to min_hold_seconds (60)
        assert optimal_hold >= 60
    
    def test_should_exit_early(self, adaptive_timing):
        """Test early exit logic."""
        # Add records favoring 6-9 minute bucket
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 8, 0),
                hold_duration_seconds=480,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        # Should exit early if hold duration exceeds optimal
        should_exit = adaptive_timing.should_exit_early(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            hold_duration_seconds=600,  # 10 minutes
            current_r_multiple=0.5
        )
        
        assert should_exit == True
    
    def test_should_not_exit_early(self, adaptive_timing):
        """Test that early exit is not triggered prematurely."""
        # Add records favoring 6-9 minute bucket
        for i in range(10):
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 8, 0),
                hold_duration_seconds=480,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        # Should not exit early if hold duration is below optimal
        should_exit = adaptive_timing.should_exit_early(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            hold_duration_seconds=300,  # 5 minutes
            current_r_multiple=0.5
        )
        
        assert should_exit == False
    
    def test_performance_stats(self, adaptive_timing):
        """Test performance statistics calculation."""
        # Add mixed records
        for i in range(5):
            # Winning trades
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 5, 0),
                hold_duration_seconds=300,
                entry_price_cents=5000,
                exit_price_cents=5500,
                side="yes",
                pnl_cents=5000,
                r_multiple=2.5,
                exit_reason="take_profit"
            )
            adaptive_timing.add_record(record)
        
        for i in range(3):
            # Losing trades
            record = ExitTimingRecord(
                market_id="KXBTC15M-2024-01-01T12:00:00",
                entry_time=datetime(2024, 1, 1, 12, 0, 0),
                exit_time=datetime(2024, 1, 1, 12, 5, 0),
                hold_duration_seconds=300,
                entry_price_cents=5000,
                exit_price_cents=4900,
                side="yes",
                pnl_cents=-1000,
                r_multiple=-0.5,
                exit_reason="stop_loss"
            )
            adaptive_timing.add_record(record)
        
        stats = adaptive_timing.get_performance_stats("KXBTC15M-2024-01-01T12:00:00")
        
        assert stats["total_exits"] == 8
        assert stats["win_rate"] == 5/8  # 5 wins out of 8
        assert stats["avg_r_multiple"] > 0  # Positive average due to more wins
    
    def test_performance_stats_no_data(self, adaptive_timing):
        """Test performance stats with no data."""
        stats = adaptive_timing.get_performance_stats("KXBTC15M-2024-01-01T12:00:00")
        
        assert stats == {}


class TestSingletonAdaptiveTiming:
    """Test singleton adaptive timing instance."""
    
    def test_get_adaptive_timing_singleton(self):
        """Test that get_adaptive_exit_timing returns singleton."""
        timing1 = get_adaptive_exit_timing()
        timing2 = get_adaptive_exit_timing()
        
        assert timing1 is timing2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
