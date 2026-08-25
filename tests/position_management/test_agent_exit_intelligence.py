"""
Tests for Agent Exit Intelligence
"""

import pytest
from merid.position_management.agent_exit_intelligence import (
    ExitSignal,
    ExitIntelligenceAggregator,
    ExitAction,
)


class TestExitSignal:
    """Tests for ExitSignal dataclass."""
    
    def test_exit_signal_creation(self):
        """Test creating an exit signal."""
        signal = ExitSignal(
            action=ExitAction.EXIT_MARKET,
            confidence=0.8,
            reasoning="Edge decay detected",
            suggested_price_cents=45,
            urgency=0.9,
            agent_id="BTC_15M",
        )
        
        assert signal.action == ExitAction.EXIT_MARKET
        assert signal.confidence == 0.8
        assert signal.reasoning == "Edge decay detected"
        assert signal.suggested_price_cents == 45
        assert signal.urgency == 0.9
        assert signal.agent_id == "BTC_15M"
    
    def test_exit_signal_defaults(self):
        """Test exit signal with defaults."""
        signal = ExitSignal(
            action=ExitAction.HOLD,
            confidence=0.6,
            reasoning="No exit signal",
        )
        
        assert signal.suggested_price_cents is None
        assert signal.urgency == 0.5
        assert signal.agent_id == ""


class TestExitIntelligenceAggregator:
    """Tests for ExitIntelligenceAggregator."""
    
    @pytest.fixture
    def aggregator(self):
        """Create an aggregator with default threshold."""
        return ExitIntelligenceAggregator(consensus_threshold=0.6)
    
    def test_aggregate_signals_no_signals(self, aggregator):
        """Test with no agent signals."""
        result = aggregator.aggregate_signals(
            agent_signals=[],
            rule_based_exit=ExitAction.HOLD,
        )
        
        assert result == ExitAction.HOLD
    
    def test_aggregate_signals_all_exit_high_confidence(self, aggregator):
        """Test all agents recommend exit with high confidence."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.8, reasoning="Exit 1", urgency=0.7),
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.9, reasoning="Exit 2", urgency=0.8),
        ]
        
        result = aggregator.aggregate_signals(
            agent_signals=signals,
            rule_based_exit=ExitAction.HOLD,
        )
        
        assert result == ExitAction.EXIT_MARKET
    
    def test_aggregate_signals_all_exit_low_confidence(self, aggregator):
        """Test all agents recommend exit with low confidence."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.4, reasoning="Exit 1", urgency=0.5),
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.5, reasoning="Exit 2", urgency=0.5),
        ]
        
        result = aggregator.aggregate_signals(
            agent_signals=signals,
            rule_based_exit=ExitAction.HOLD,
        )
        
        # Low confidence, defer to rules
        assert result == ExitAction.HOLD
    
    def test_aggregate_signals_all_hold(self, aggregator):
        """Test all agents recommend hold."""
        signals = [
            ExitSignal(action=ExitAction.HOLD, confidence=0.8, reasoning="Hold 1", urgency=0.0),
            ExitSignal(action=ExitAction.HOLD, confidence=0.7, reasoning="Hold 2", urgency=0.0),
        ]
        
        result = aggregator.aggregate_signals(
            agent_signals=signals,
            rule_based_exit=ExitAction.EXIT_MARKET,
        )
        
        assert result == ExitAction.HOLD
    
    def test_aggregate_signals_mixed_exit_wins(self, aggregator):
        """Test mixed signals where exit wins by weight."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.9, reasoning="Exit", urgency=0.9),
            ExitSignal(action=ExitAction.HOLD, confidence=0.5, reasoning="Hold", urgency=0.0),
        ]
        
        result = aggregator.aggregate_signals(
            agent_signals=signals,
            rule_based_exit=ExitAction.HOLD,
        )
        
        assert result == ExitAction.EXIT_MARKET
    
    def test_aggregate_signals_mixed_hold_wins(self, aggregator):
        """Test mixed signals where hold wins by weight."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.5, reasoning="Exit", urgency=0.4),
            ExitSignal(action=ExitAction.HOLD, confidence=0.9, reasoning="Hold", urgency=0.0),
        ]
        
        result = aggregator.aggregate_signals(
            agent_signals=signals,
            rule_based_exit=ExitAction.EXIT_MARKET,
        )
        
        assert result == ExitAction.EXIT_MARKET  # Defer to rules
    
    def test_get_aggregated_signal_all_exit(self, aggregator):
        """Test aggregation when all agents recommend exit."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.8, reasoning="Exit 1", urgency=0.7),
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.9, reasoning="Exit 2", urgency=0.8),
        ]
        
        result = aggregator.get_aggregated_signal(signals)
        
        assert result is not None
        assert result.action == ExitAction.EXIT_MARKET
        assert result.confidence == pytest.approx(0.85)  # Average
        assert result.urgency == pytest.approx(0.75)  # Average
    
    def test_get_aggregated_signal_all_hold(self, aggregator):
        """Test aggregation when all agents recommend hold."""
        signals = [
            ExitSignal(action=ExitAction.HOLD, confidence=0.7, reasoning="Hold 1", urgency=0.0),
            ExitSignal(action=ExitAction.HOLD, confidence=0.8, reasoning="Hold 2", urgency=0.0),
        ]
        
        result = aggregator.get_aggregated_signal(signals)
        
        assert result is not None
        assert result.action == ExitAction.HOLD
        assert result.confidence == 0.75  # Average
        assert result.urgency == 0.0
    
    def test_get_aggregated_signal_mixed(self, aggregator):
        """Test aggregation with mixed signals."""
        signals = [
            ExitSignal(action=ExitAction.EXIT_MARKET, confidence=0.9, reasoning="Exit", urgency=0.8),
            ExitSignal(action=ExitAction.HOLD, confidence=0.5, reasoning="Hold", urgency=0.0),
        ]
        
        result = aggregator.get_aggregated_signal(signals)
        
        assert result is not None
        # Should return highest confidence signal
        assert result.action == ExitAction.EXIT_MARKET
        assert result.confidence == 0.9
    
    def test_get_aggregated_signal_empty(self, aggregator):
        """Test aggregation with empty list."""
        result = aggregator.get_aggregated_signal([])
        
        assert result is None
    
    def test_get_aggregated_signal_adjust_signals(self, aggregator):
        """Test aggregation with adjust signals."""
        signals = [
            ExitSignal(action=ExitAction.ADJUST_TP, confidence=0.8, reasoning="Adjust TP", urgency=0.5),
            ExitSignal(action=ExitAction.ADJUST_SL, confidence=0.7, reasoning="Adjust SL", urgency=0.5),
        ]
        
        result = aggregator.get_aggregated_signal(signals)
        
        assert result is not None
        # Should return highest confidence signal
        assert result.action == ExitAction.ADJUST_TP
