"""
Tests for error_taxonomy.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from merid.validation.error_taxonomy import (
    ErrorTaxonomy,
    TradeSkipReason,
    InvariantViolationReason,
    TradeSkipEvent,
    InvariantViolationEvent,
    get_error_taxonomy,
    log_trade_skip,
    log_invariant_violation,
    log_edge_too_small,
    log_vol_too_high,
    log_config_mismatch,
    log_volume_illiquid,
    log_spread_too_wide,
    log_velocity_extreme,
)


class TestErrorTaxonomy:
    """Test suite for error taxonomy."""
    
    @pytest.fixture
    def taxonomy(self):
        """Fixture for ErrorTaxonomy."""
        return ErrorTaxonomy()
    
    @pytest.fixture
    def mock_logger(self):
        """Mock logger for testing."""
        with patch('merid.validation.error_taxonomy.logger') as mock_logger:
            yield mock_logger
    
    def test_log_trade_skip(self, taxonomy, mock_logger):
        """Test logging a trade skip event."""
        event = taxonomy.log_trade_skip(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
            edge=0.005,
            volatility=0.02,
            volume=50,
            spread_cents=5,
            velocity=0.0005,
            context={"test": "value"},
        )
        
        assert event.asset == "BTC"
        assert event.ticker == "KXBTC15M-26JUL211730-30"
        assert event.reason == TradeSkipReason.EDGE_TOO_SMALL
        assert event.edge == 0.005
        assert len(taxonomy.trade_skips) == 1
        assert taxonomy._skip_counts[TradeSkipReason.EDGE_TOO_SMALL] == 1
    
    def test_log_invariant_violation(self, taxonomy, mock_logger):
        """Test logging an invariant violation event."""
        event = taxonomy.log_invariant_violation(
            invariant_name="Edge Probability Consistency",
            reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
            severity="HIGH",
            message="Edge sign mismatch detected",
            context={"test": "value"},
        )
        
        assert event.invariant_name == "Edge Probability Consistency"
        assert event.reason == InvariantViolationReason.EDGE_SIGN_MISMATCH
        assert event.severity == "HIGH"
        assert len(taxonomy.invariant_violations) == 1
        assert taxonomy._violation_counts[InvariantViolationReason.EDGE_SIGN_MISMATCH] == 1
    
    def test_get_skip_statistics(self, taxonomy):
        """Test getting skip statistics."""
        taxonomy.log_trade_skip(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
        )
        
        taxonomy.log_trade_skip(
            asset="ETH",
            ticker="KXETH15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
        )
        
        taxonomy.log_trade_skip(
            asset="SOL",
            ticker="KXSOL15M-26JUL211730-30",
            reason=TradeSkipReason.VOL_TOO_HIGH,
        )
        
        stats = taxonomy.get_skip_statistics()
        assert stats["EDGE_TOO_SMALL"] == 2
        assert stats["VOL_TOO_HIGH"] == 1
    
    def test_get_violation_statistics(self, taxonomy):
        """Test getting violation statistics."""
        taxonomy.log_invariant_violation(
            invariant_name="Test",
            reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
            severity="HIGH",
            message="Test",
        )
        
        taxonomy.log_invariant_violation(
            invariant_name="Test",
            reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
            severity="HIGH",
            message="Test",
        )
        
        taxonomy.log_invariant_violation(
            invariant_name="Test",
            reason=InvariantViolationReason.SIDE_PROBABILITY_MISMATCH,
            severity="HIGH",
            message="Test",
        )
        
        stats = taxonomy.get_violation_statistics()
        assert stats["EDGE_SIGN_MISMATCH"] == 2
        assert stats["SIDE_PROBABILITY_MISMATCH"] == 1
    
    def test_get_recent_skips(self, taxonomy):
        """Test getting recent skips."""
        for i in range(10):
            taxonomy.log_trade_skip(
                asset="BTC",
                ticker=f"KXBTC15M-26JUL211730-{i}",
                reason=TradeSkipReason.EDGE_TOO_SMALL,
            )
        
        recent_skips = taxonomy.get_recent_skips(limit=5)
        assert len(recent_skips) == 5
        
        recent_skips_filtered = taxonomy.get_recent_skips(
            limit=5,
            reason_filter=TradeSkipReason.EDGE_TOO_SMALL,
        )
        assert len(recent_skips_filtered) == 5
    
    def test_get_recent_violations(self, taxonomy):
        """Test getting recent violations."""
        for i in range(10):
            taxonomy.log_invariant_violation(
                invariant_name="Test",
                reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
                severity="HIGH",
                message=f"Test {i}",
            )
        
        recent_violations = taxonomy.get_recent_violations(limit=5)
        assert len(recent_violations) == 5
    
    def test_clear_old_events(self, taxonomy):
        """Test clearing old events."""
        # Add some events
        taxonomy.log_trade_skip(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
        )
        
        assert len(taxonomy.trade_skips) == 1
        
        # Clear old events (all events are recent, so should not clear)
        taxonomy.clear_old_events(hours=24)
        assert len(taxonomy.trade_skips) == 1


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    @pytest.fixture
    def mock_logger(self):
        """Mock logger for testing."""
        with patch('merid.validation.error_taxonomy.logger') as mock_logger:
            yield mock_logger
    
    def test_log_edge_too_small(self, mock_logger):
        """Test convenience function for edge too small."""
        event = log_edge_too_small(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            edge=0.005,
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.EDGE_TOO_SMALL
        assert event.edge == 0.005
    
    def test_log_vol_too_high(self, mock_logger):
        """Test convenience function for volatility too high."""
        event = log_vol_too_high(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            volatility=0.06,
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.VOL_TOO_HIGH
        assert event.volatility == 0.06
    
    def test_log_config_mismatch(self, mock_logger):
        """Test convenience function for config mismatch."""
        event = log_config_mismatch(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.CONFIG_MISMATCH
    
    def test_log_volume_illiquid(self, mock_logger):
        """Test convenience function for volume illiquid."""
        event = log_volume_illiquid(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            volume=5,
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.VOLUME_ILLIQUID
        assert event.volume == 5
    
    def test_log_spread_too_wide(self, mock_logger):
        """Test convenience function for spread too wide."""
        event = log_spread_too_wide(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            spread_cents=35,
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.SPREAD_TOO_WIDE
        assert event.spread_cents == 35
    
    def test_log_velocity_extreme(self, mock_logger):
        """Test convenience function for velocity extreme."""
        event = log_velocity_extreme(
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            velocity=0.003,
            context={"test": "value"},
        )
        
        assert event.reason == TradeSkipReason.VELOCITY_EXTREME
        assert event.velocity == 0.003


class TestTradeSkipEvent:
    """Test TradeSkipEvent dataclass."""
    
    def test_trade_skip_event_creation(self):
        """Test TradeSkipEvent creation."""
        event = TradeSkipEvent(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
            edge=0.005,
        )
        
        assert event.asset == "BTC"
        assert event.reason == TradeSkipReason.EDGE_TOO_SMALL
        assert event.edge == 0.005
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        event = TradeSkipEvent(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            asset="BTC",
            ticker="KXBTC15M-26JUL211730-30",
            reason=TradeSkipReason.EDGE_TOO_SMALL,
            edge=0.005,
        )
        
        event_dict = event.to_dict()
        assert event_dict["asset"] == "BTC"
        assert event_dict["reason"] == "EDGE_TOO_SMALL"
        assert event_dict["edge"] == 0.005


class TestInvariantViolationEvent:
    """Test InvariantViolationEvent dataclass."""
    
    def test_invariant_violation_event_creation(self):
        """Test InvariantViolationEvent creation."""
        event = InvariantViolationEvent(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            invariant_name="Test",
            reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
            severity="HIGH",
            message="Test violation",
        )
        
        assert event.invariant_name == "Test"
        assert event.reason == InvariantViolationReason.EDGE_SIGN_MISMATCH
        assert event.severity == "HIGH"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        event = InvariantViolationEvent(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            invariant_name="Test",
            reason=InvariantViolationReason.EDGE_SIGN_MISMATCH,
            severity="HIGH",
            message="Test violation",
        )
        
        event_dict = event.to_dict()
        assert event_dict["invariant_name"] == "Test"
        assert event_dict["reason"] == "EDGE_SIGN_MISMATCH"
        assert event_dict["severity"] == "HIGH"


class TestSingleton:
    """Test singleton instance."""
    
    def test_get_error_taxonomy_singleton(self):
        """Test that get_error_taxonomy returns singleton."""
        taxonomy1 = get_error_taxonomy()
        taxonomy2 = get_error_taxonomy()
        
        assert taxonomy1 is taxonomy2


class TestEnums:
    """Test enum values."""
    
    def test_trade_skip_reason_enum(self):
        """Test TradeSkipReason enum values."""
        assert TradeSkipReason.EDGE_TOO_SMALL.value == "EDGE_TOO_SMALL"
        assert TradeSkipReason.VOL_TOO_HIGH.value == "VOL_TOO_HIGH"
        assert TradeSkipReason.CONFIG_MISMATCH.value == "CONFIG_MISMATCH"
        assert TradeSkipReason.VOLUME_ILLIQUID.value == "VOLUME_ILLIQUID"
        assert TradeSkipReason.SPREAD_TOO_WIDE.value == "SPREAD_TOO_WIDE"
        assert TradeSkipReason.VELOCITY_EXTREME.value == "VELOCITY_EXTREME"
        assert TradeSkipReason.POSITION_LIMIT_REACHED.value == "POSITION_LIMIT_REACHED"
        assert TradeSkipReason.RISK_CAP_EXCEEDED.value == "RISK_CAP_EXCEEDED"
        assert TradeSkipReason.MARKET_CLOSED.value == "MARKET_CLOSED"
        assert TradeSkipReason.INFRASTRUCTURE_HALT.value == "INFRASTRUCTURE_HALT"
        assert TradeSkipReason.UNKNOWN.value == "UNKNOWN"
    
    def test_invariant_violation_reason_enum(self):
        """Test InvariantViolationReason enum values."""
        assert InvariantViolationReason.EDGE_SIGN_MISMATCH.value == "EDGE_SIGN_MISMATCH"
        assert InvariantViolationReason.SIDE_PROBABILITY_MISMATCH.value == "SIDE_PROBABILITY_MISMATCH"
        assert InvariantViolationReason.CONFIDENCE_NOT_MONOTONIC.value == "CONFIDENCE_NOT_MONOTONIC"
        assert InvariantViolationReason.VOLATILITY_HALT_TRADE.value == "VOLATILITY_HALT_TRADE"
        assert InvariantViolationReason.VOLUME_ILLIQUID_TRADE.value == "VOLUME_ILLIQUID_TRADE"
        assert InvariantViolationReason.ILLEGAL_SEMANTIC_COMBINATION.value == "ILLEGAL_SEMANTIC_COMBINATION"
        assert InvariantViolationReason.NEGATIVE_BALANCE.value == "NEGATIVE_BALANCE"
        assert InvariantViolationReason.LEVERAGE_EXCEEDED.value == "LEVERAGE_EXCEEDED"
