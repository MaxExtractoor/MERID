"""
Tests for Agent Exit Recommendations
"""

import pytest
from merid.position_management.agent_exit_recommendations import (
    ExitRecommendation,
    ExitRecommendationAggregator,
    ExitAction,
)


class TestExitRecommendation:
    """Tests for ExitRecommendation dataclass."""
    
    def test_exit_recommendation_creation(self):
        """Test creating an exit recommendation."""
        rec = ExitRecommendation(
            should_exit=True,
            urgency=0.8,
            reason="Edge decay detected",
            suggested_price_cents=45,
            confidence=0.9,
            agent_id="BTC_15M",
        )
        
        assert rec.should_exit is True
        assert rec.urgency == 0.8
        assert rec.reason == "Edge decay detected"
        assert rec.suggested_price_cents == 45
        assert rec.confidence == 0.9
        assert rec.agent_id == "BTC_15M"
    
    def test_exit_recommendation_defaults(self):
        """Test exit recommendation with defaults."""
        rec = ExitRecommendation(
            should_exit=False,
            urgency=0.3,
            reason="No exit signal",
        )
        
        assert rec.should_exit is False
        assert rec.suggested_price_cents is None
        assert rec.confidence == 0.0
        assert rec.agent_id == ""


class TestExitRecommendationAggregator:
    """Tests for ExitRecommendationAggregator."""
    
    @pytest.fixture
    def aggregator(self):
        """Create an aggregator with default threshold."""
        return ExitRecommendationAggregator(urgency_threshold=0.7)
    
    def test_evaluate_exit_no_recommendations(self, aggregator):
        """Test with no agent recommendations."""
        result = aggregator.evaluate_exit(
            rule_based_exit=ExitAction.HOLD,
            agent_recommendations=[],
        )
        
        assert result == ExitAction.HOLD
    
    def test_evaluate_exit_urgent_override(self, aggregator):
        """Test urgent agent recommendation overrides rules."""
        rec = ExitRecommendation(
            should_exit=True,
            urgency=0.9,  # Above threshold
            reason="Urgent exit",
            confidence=0.8,
        )
        
        result = aggregator.evaluate_exit(
            rule_based_exit=ExitAction.HOLD,
            agent_recommendations=[rec],
        )
        
        assert result == ExitAction.EXIT_MARKET
    
    def test_evaluate_exit_non_urgent_no_override(self, aggregator):
        """Test non-urgent recommendation does not override rules."""
        rec = ExitRecommendation(
            should_exit=True,
            urgency=0.5,  # Below threshold
            reason="Non-urgent exit",
            confidence=0.6,
        )
        
        result = aggregator.evaluate_exit(
            rule_based_exit=ExitAction.HOLD,
            agent_recommendations=[rec],
        )
        
        assert result == ExitAction.HOLD
    
    def test_evaluate_exit_multi_agent_consensus(self, aggregator):
        """Test multiple agents agreeing overrides rules."""
        rec1 = ExitRecommendation(
            should_exit=True,
            urgency=0.6,
            reason="Agent 1 exit",
            confidence=0.7,
        )
        rec2 = ExitRecommendation(
            should_exit=True,
            urgency=0.6,
            reason="Agent 2 exit",
            confidence=0.7,
        )
        
        result = aggregator.evaluate_exit(
            rule_based_exit=ExitAction.HOLD,
            agent_recommendations=[rec1, rec2],
        )
        
        assert result == ExitAction.EXIT_MARKET
    
    def test_evaluate_exit_mixed_recommendations(self, aggregator):
        """Test mixed recommendations defer to rules."""
        rec1 = ExitRecommendation(
            should_exit=True,
            urgency=0.6,
            reason="Exit",
            confidence=0.7,
        )
        rec2 = ExitRecommendation(
            should_exit=False,
            urgency=0.0,
            reason="Hold",
            confidence=0.6,
        )
        
        result = aggregator.evaluate_exit(
            rule_based_exit=ExitAction.HOLD,
            agent_recommendations=[rec1, rec2],
        )
        
        assert result == ExitAction.HOLD
    
    def test_get_aggregated_recommendation_all_hold(self, aggregator):
        """Test aggregation when all agents recommend hold."""
        recs = [
            ExitRecommendation(should_exit=False, urgency=0.0, reason="Hold 1", confidence=0.8),
            ExitRecommendation(should_exit=False, urgency=0.0, reason="Hold 2", confidence=0.7),
        ]
        
        result = aggregator.get_aggregated_recommendation(recs)
        
        assert result is not None
        assert result.should_exit is False
        assert result.urgency == 0.0
        assert result.confidence == 0.75  # Average of 0.8 and 0.7
    
    def test_get_aggregated_recommendation_all_exit(self, aggregator):
        """Test aggregation when all agents recommend exit."""
        recs = [
            ExitRecommendation(should_exit=True, urgency=0.8, reason="Exit 1", confidence=0.9),
            ExitRecommendation(should_exit=True, urgency=0.7, reason="Exit 2", confidence=0.8),
        ]
        
        result = aggregator.get_aggregated_recommendation(recs)
        
        assert result is not None
        assert result.should_exit is True
        assert result.urgency == 0.75  # Average of 0.8 and 0.7
        assert result.confidence == pytest.approx(0.85)  # Average of 0.9 and 0.8
    
    def test_get_aggregated_recommendation_mixed_exit_wins(self, aggregator):
        """Test mixed recommendations where exit wins by weight."""
        recs = [
            ExitRecommendation(should_exit=True, urgency=0.9, reason="Exit", confidence=0.9),
            ExitRecommendation(should_exit=False, urgency=0.0, reason="Hold", confidence=0.5),
        ]
        
        result = aggregator.get_aggregated_recommendation(recs)
        
        assert result is not None
        assert result.should_exit is True
    
    def test_get_aggregated_recommendation_mixed_hold_wins(self, aggregator):
        """Test mixed recommendations where hold wins by weight."""
        recs = [
            ExitRecommendation(should_exit=True, urgency=0.4, reason="Exit", confidence=0.5),
            ExitRecommendation(should_exit=False, urgency=0.0, reason="Hold", confidence=0.9),
        ]
        
        result = aggregator.get_aggregated_recommendation(recs)
        
        assert result is not None
        assert result.should_exit is False
    
    def test_get_aggregated_recommendation_empty(self, aggregator):
        """Test aggregation with empty list."""
        result = aggregator.get_aggregated_recommendation([])
        
        assert result is None
