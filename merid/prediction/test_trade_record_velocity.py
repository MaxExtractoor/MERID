"""Tests for TradeRecord velocity field and side accuracy analysis.

Tests the new velocity field in TradeRecord and its integration with
the side accuracy analyzer.
"""

import time
import pytest
from decimal import Decimal

from merid.prediction.agent_performance_tracker import (
    AgentPerformanceTracker,
    TradeRecord,
)


class TestTradeRecordVelocity:
    """Test TradeRecord velocity field."""
    
    def test_trade_record_with_velocity(self):
        """Test TradeRecord can be created with velocity field."""
        record = TradeRecord(
            agent_id="BTC_15M",
            market_id="KXBTC15M-12345",
            side="yes",
            entry_price_cents=50,
            contracts=3,
            entry_ts=time.time(),
            predicted_edge=0.05,
            confidence=0.7,
            velocity=0.0001,
        )
        
        assert record.velocity == 0.0001
        assert record.side == "yes"
        assert record.agent_id == "BTC_15M"
    
    def test_trade_record_without_velocity(self):
        """Test TradeRecord can be created without velocity (backward compatibility)."""
        record = TradeRecord(
            agent_id="BTC_15M",
            market_id="KXBTC15M-12345",
            side="yes",
            entry_price_cents=50,
            contracts=3,
            entry_ts=time.time(),
            predicted_edge=0.05,
            confidence=0.7,
        )
        
        assert record.velocity is None
        assert record.side == "yes"
    
    def test_trade_record_negative_velocity(self):
        """Test TradeRecord with negative velocity."""
        record = TradeRecord(
            agent_id="ETH_15M",
            market_id="KXETH15M-12345",
            side="no",
            entry_price_cents=40,
            contracts=2,
            entry_ts=time.time(),
            predicted_edge=0.03,
            confidence=0.6,
            velocity=-0.00015,
        )
        
        assert record.velocity == -0.00015
        assert record.side == "no"
    
    def test_trade_record_zero_velocity(self):
        """Test TradeRecord with zero velocity (no conviction)."""
        record = TradeRecord(
            agent_id="SOL_15M",
            market_id="KXSOL15M-12345",
            side="yes",
            entry_price_cents=30,
            contracts=1,
            entry_ts=time.time(),
            predicted_edge=0.02,
            confidence=0.5,
            velocity=0.0,
        )
        
        assert record.velocity == 0.0


class TestAgentPerformanceTrackerVelocity:
    """Test AgentPerformanceTracker with velocity field."""
    
    def test_record_fill_with_velocity(self):
        """Test record_fill accepts velocity parameter."""
        tracker = AgentPerformanceTracker()
        
        tracker.record_fill(
            agent_id="BTC_15M",
            market_id="KXBTC15M-12345",
            side="yes",
            price_cents=50,
            contracts=3,
            predicted_edge=0.05,
            confidence=0.7,
            velocity=0.0001,
        )
        
        # Check the trade was recorded with velocity
        trade_key = "BTC_15M:KXBTC15M-12345"
        assert trade_key in tracker._open_trades
        record = tracker._open_trades[trade_key]
        assert record.velocity == 0.0001
        assert record.side == "yes"
    
    def test_record_fill_without_velocity(self):
        """Test record_fill works without velocity (backward compatibility)."""
        tracker = AgentPerformanceTracker()
        
        tracker.record_fill(
            agent_id="ETH_15M",
            market_id="KXETH15M-12345",
            side="no",
            price_cents=40,
            contracts=2,
            predicted_edge=0.03,
            confidence=0.6,
        )
        
        # Check the trade was recorded without velocity
        trade_key = "ETH_15M:KXETH15M-12345"
        assert trade_key in tracker._open_trades
        record = tracker._open_trades[trade_key]
        assert record.velocity is None
        assert record.side == "no"
    
    def test_record_close_preserves_velocity(self):
        """Test record_close preserves velocity in closed trade record."""
        tracker = AgentPerformanceTracker()
        
        # Record fill with velocity
        tracker.record_fill(
            agent_id="BTC_15M",
            market_id="KXBTC15M-12345",
            side="yes",
            price_cents=50,
            contracts=3,
            predicted_edge=0.05,
            confidence=0.7,
            velocity=0.0001,
        )
        
        # Record close
        tracker.record_close(
            agent_id="BTC_15M",
            market_id="KXBTC15M-12345",
            exit_price_cents=60,
            profit_usd=Decimal("10.00"),
        )
        
        # Check velocity is preserved in closed trades
        assert len(tracker._closed_trades) == 1
        record = tracker._closed_trades[0]
        assert record.velocity == 0.0001
        assert record.exit_price_cents == 60
    
    def test_multiple_trades_with_velocities(self):
        """Test recording multiple trades with different velocities."""
        tracker = AgentPerformanceTracker()
        
        # Record multiple trades
        trades_data = [
            ("BTC_15M", "KXBTC15M-1", "yes", 50, 3, 0.0001),
            ("ETH_15M", "KXETH15M-2", "no", 40, 2, -0.00015),
            ("SOL_15M", "KXSOL15M-3", "yes", 30, 1, 0.0002),
        ]
        
        for agent_id, market_id, side, price, contracts, velocity in trades_data:
            tracker.record_fill(
                agent_id=agent_id,
                market_id=market_id,
                side=side,
                price_cents=price,
                contracts=contracts,
                predicted_edge=0.05,
                confidence=0.7,
                velocity=velocity,
            )
        
        # Verify all trades recorded with correct velocities
        assert len(tracker._open_trades) == 3
        assert tracker._open_trades["BTC_15M:KXBTC15M-1"].velocity == 0.0001
        assert tracker._open_trades["ETH_15M:KXETH15M-2"].velocity == -0.00015
        assert tracker._open_trades["SOL_15M:KXSOL15M-3"].velocity == 0.0002


class TestSideAccuracyWithVelocity:
    """Test side accuracy analyzer with actual velocity data."""
    
    def test_velocity_to_side_mapping_positive_velocity_yes(self):
        """Test positive velocity correctly maps to YES side."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with positive velocity and YES side (correct)
        trade = TradeRecord(
            agent_id="BTC_15M",
            market_id="KXBTC15M-1",
            side="yes",
            entry_price_cents=50,
            contracts=3,
            entry_ts=time.time(),
            predicted_edge=0.05,
            confidence=0.7,
            velocity=0.0001,  # Positive velocity
            exit_price_cents=60,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("10.00"),
            realized_edge=0.05,
            outcome="win",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should count as positive_velocity_yes (correct)
        assert metrics.positive_velocity_yes == 1
        assert metrics.positive_velocity_no == 0
        assert metrics.negative_velocity_yes == 0
        assert metrics.negative_velocity_no == 0
    
    def test_velocity_to_side_mapping_positive_velocity_no(self):
        """Test positive velocity with NO side (incorrect mapping)."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with positive velocity but NO side (incorrect)
        trade = TradeRecord(
            agent_id="BTC_15M",
            market_id="KXBTC15M-1",
            side="no",
            entry_price_cents=50,
            contracts=3,
            entry_ts=time.time(),
            predicted_edge=0.05,
            confidence=0.7,
            velocity=0.0001,  # Positive velocity but NO side
            exit_price_cents=40,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("-10.00"),
            realized_edge=-0.05,
            outcome="loss",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should count as positive_velocity_no (incorrect)
        assert metrics.positive_velocity_yes == 0
        assert metrics.positive_velocity_no == 1
        assert metrics.negative_velocity_yes == 0
        assert metrics.negative_velocity_no == 0
    
    def test_velocity_to_side_mapping_negative_velocity_no(self):
        """Test negative velocity correctly maps to NO side."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with negative velocity and NO side (correct)
        trade = TradeRecord(
            agent_id="ETH_15M",
            market_id="KXETH15M-1",
            side="no",
            entry_price_cents=40,
            contracts=2,
            entry_ts=time.time(),
            predicted_edge=0.03,
            confidence=0.6,
            velocity=-0.00015,  # Negative velocity
            exit_price_cents=30,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("5.00"),
            realized_edge=0.03,
            outcome="win",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should count as negative_velocity_no (correct)
        assert metrics.positive_velocity_yes == 0
        assert metrics.positive_velocity_no == 0
        assert metrics.negative_velocity_yes == 0
        assert metrics.negative_velocity_no == 1
    
    def test_velocity_to_side_mapping_negative_velocity_yes(self):
        """Test negative velocity with YES side (incorrect mapping)."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with negative velocity but YES side (incorrect)
        trade = TradeRecord(
            agent_id="ETH_15M",
            market_id="KXETH15M-1",
            side="yes",
            entry_price_cents=40,
            contracts=2,
            entry_ts=time.time(),
            predicted_edge=0.03,
            confidence=0.6,
            velocity=-0.00015,  # Negative velocity but YES side
            exit_price_cents=50,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("-5.00"),
            realized_edge=-0.03,
            outcome="loss",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should count as negative_velocity_yes (incorrect)
        assert metrics.positive_velocity_yes == 0
        assert metrics.positive_velocity_no == 0
        assert metrics.negative_velocity_yes == 1
        assert metrics.negative_velocity_no == 0
    
    def test_velocity_none_ignored(self):
        """Test trades with None velocity are ignored in velocity mapping."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with None velocity
        trade = TradeRecord(
            agent_id="SOL_15M",
            market_id="KXSOL15M-1",
            side="yes",
            entry_price_cents=30,
            contracts=1,
            entry_ts=time.time(),
            predicted_edge=0.02,
            confidence=0.5,
            velocity=None,  # No velocity data
            exit_price_cents=40,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("5.00"),
            realized_edge=0.02,
            outcome="win",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should not count in velocity mapping
        assert metrics.positive_velocity_yes == 0
        assert metrics.positive_velocity_no == 0
        assert metrics.negative_velocity_yes == 0
        assert metrics.negative_velocity_no == 0
        # But should still count in total trades
        assert metrics.total_trades == 1
    
    def test_velocity_zero_ignored(self):
        """Test trades with zero velocity are ignored in velocity mapping."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyAnalyzer, SideAccuracyMetrics
        
        # Create analyzer
        tracker = AgentPerformanceTracker()
        analyzer = SideAccuracyAnalyzer(tracker)
        
        # Create trade with zero velocity
        trade = TradeRecord(
            agent_id="XRP_15M",
            market_id="KXXRP15M-1",
            side="yes",
            entry_price_cents=25,
            contracts=1,
            entry_ts=time.time(),
            predicted_edge=0.02,
            confidence=0.5,
            velocity=0.0,  # Zero velocity (no conviction)
            exit_price_cents=35,
            exit_ts=time.time() + 300,
            profit_usd=Decimal("5.00"),
            realized_edge=0.02,
            outcome="win",
        )
        
        tracker._closed_trades.append(trade)
        
        # Update metrics
        metrics = SideAccuracyMetrics(group_name="test")
        analyzer._update_metrics(metrics, trade)
        
        # Should not count in velocity mapping
        assert metrics.positive_velocity_yes == 0
        assert metrics.positive_velocity_no == 0
        assert metrics.negative_velocity_yes == 0
        assert metrics.negative_velocity_no == 0
        # But should still count in total trades
        assert metrics.total_trades == 1
    
    def test_velocity_accuracy_calculation(self):
        """Test velocity-to-side accuracy calculation."""
        from merid.prediction.analyze_side_accuracy import SideAccuracyMetrics
        
        metrics = SideAccuracyMetrics(group_name="test")
        
        # Simulate correct mappings
        metrics.positive_velocity_yes = 8  # Correct
        metrics.negative_velocity_no = 7   # Correct
        
        # Simulate incorrect mappings
        metrics.positive_velocity_no = 2   # Incorrect
        metrics.negative_velocity_yes = 3  # Incorrect
        
        # Calculate accuracy
        correct = metrics.positive_velocity_yes + metrics.negative_velocity_no
        total = (metrics.positive_velocity_yes + metrics.positive_velocity_no + 
                 metrics.negative_velocity_yes + metrics.negative_velocity_no)
        
        expected_accuracy = correct / total
        actual_accuracy = metrics.velocity_side_accuracy
        
        assert actual_accuracy == expected_accuracy
        assert actual_accuracy == 0.75  # 15 correct out of 20 total


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
