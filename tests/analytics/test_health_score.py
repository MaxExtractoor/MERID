"""Tests for analytics/health_score.py."""
import pytest
from analytics.health_score import (
    UsageSignal, SentimentSignal, FinancialSignal, HealthScoreWeights,
    RiskIncident, ChurnRisk, InteractionFeaturesMissing,
    _bounded, _usage_score, _sentiment_score, _financial_score,
    compute_health_score, compute_churn_risk
)


class TestBounded:
    """Test _bounded function."""

    def test_value_within_bounds(self):
        """Test value within bounds returns unchanged."""
        assert _bounded(0.5) == 0.5

    def test_value_below_lower(self):
        """Test value below lower bound clamps to lower."""
        assert _bounded(-0.5) == 0.0

    def test_value_above_upper(self):
        """Test value above upper bound clamps to upper."""
        assert _bounded(1.5) == 1.0

    def test_custom_bounds(self):
        """Test custom bounds."""
        assert _bounded(-10, lower=-5, upper=5) == -5
        assert _bounded(10, lower=-5, upper=5) == 5


class TestUsageScore:
    """Test _usage_score function."""

    def test_full_usage(self):
        """Test usage score with full feature adoption."""
        signal = UsageSignal(active_features=10, total_features=10, weekly_actions=500)
        score = _usage_score(signal)
        assert score == 1.0

    def test_no_usage(self):
        """Test usage score with no usage."""
        signal = UsageSignal(active_features=0, total_features=10, weekly_actions=0)
        score = _usage_score(signal)
        assert score == 0.0

    def test_partial_usage(self):
        """Test usage score with partial usage."""
        signal = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        score = _usage_score(signal)
        # 0.6 * 0.5 + 0.4 * 0.5 = 0.5
        assert 0.4 < score < 0.6


class TestSentimentScore:
    """Test _sentiment_score function."""

    def test_maximum_sentiment(self):
        """Test sentiment score with maximum values."""
        signal = SentimentSignal(nps=100, csat=5)
        score = _sentiment_score(signal)
        assert score == 1.0

    def test_minimum_sentiment(self):
        """Test sentiment score with minimum values."""
        signal = SentimentSignal(nps=-100, csat=1)
        score = _sentiment_score(signal)
        assert score == 0.0

    def test_neutral_sentiment(self):
        """Test sentiment score with neutral values."""
        signal = SentimentSignal(nps=0, csat=3)
        score = _sentiment_score(signal)
        # NPS: (0+100)/200 = 0.5, CSAT: (3-1)/4 = 0.5, Average = 0.5
        assert 0.45 < score < 0.55


class TestFinancialScore:
    """Test _financial_score function."""

    def test_current_payment_high_arr(self):
        """Test financial score with current payment and high ARR."""
        signal = FinancialSignal(arr_commit_usd=2_000_000, payment_status="current")
        score = _financial_score(signal)
        assert score == 1.0

    def test_unpaid_payment(self):
        """Test financial score with unpaid status."""
        signal = FinancialSignal(arr_commit_usd=1_000_000, payment_status="unpaid")
        score = _financial_score(signal)
        # 1.0 * 0.1 = 0.1
        assert 0.09 < score < 0.11

    def test_delinquent_payment(self):
        """Test financial score with delinquent status."""
        signal = FinancialSignal(arr_commit_usd=1_000_000, payment_status="delinquent")
        score = _financial_score(signal)
        # 1.0 * 0.5 = 0.5
        assert 0.49 < score < 0.51


class TestComputeHealthScore:
    """Test compute_health_score function."""

    def test_equal_weights(self):
        """Test health score with equal weights."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        score = compute_health_score(usage, sentiment, financial, weights=weights)
        assert 0.0 <= score <= 1.0

    def test_usage_heavy(self):
        """Test health score with usage-heavy weights."""
        usage = UsageSignal(active_features=10, total_features=10, weekly_actions=500)
        sentiment = SentimentSignal(nps=-100, csat=1)
        financial = FinancialSignal(arr_commit_usd=0, payment_status="unpaid")
        weights = HealthScoreWeights(usage=1.0, sentiment=0.0, financial=0.0)
        
        score = compute_health_score(usage, sentiment, financial, weights=weights)
        # Should be close to 1.0 since usage is maxed and weights are all on usage
        assert score > 0.9

    def test_zero_weights_error(self):
        """Test health score with zero weights raises error."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.0, sentiment=0.0, financial=0.0)
        
        with pytest.raises(ValueError, match="Weights must be positive"):
            compute_health_score(usage, sentiment, financial, weights=weights)

    def test_negative_weights_error(self):
        """Test health score with negative weights raises error."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=-0.5, sentiment=0.3, financial=0.2)
        
        with pytest.raises(ValueError, match="Weights must be positive"):
            compute_health_score(usage, sentiment, financial, weights=weights)


class TestComputeChurnRisk:
    """Test compute_churn_risk function."""

    def test_missing_interaction_features(self):
        """Test churn risk calculation without interaction features."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        with pytest.raises(InteractionFeaturesMissing):
            compute_churn_risk(usage, sentiment, financial, interaction_features=False, weights=weights)

    def test_low_risk_customer(self):
        """Test churn risk for healthy customer."""
        usage = UsageSignal(active_features=10, total_features=10, weekly_actions=500)
        sentiment = SentimentSignal(nps=80, csat=5)
        financial = FinancialSignal(arr_commit_usd=2_000_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        risk = compute_churn_risk(usage, sentiment, financial, interaction_features=True, weights=weights)
        
        assert risk.probability < 0.3
        assert not risk.incident.flagged

    def test_high_risk_customer(self):
        """Test churn risk for at-risk customer."""
        usage = UsageSignal(active_features=1, total_features=10, weekly_actions=50)
        sentiment = SentimentSignal(nps=-50, csat=2)
        financial = FinancialSignal(arr_commit_usd=100_000, payment_status="delinquent")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        risk = compute_churn_risk(usage, sentiment, financial, interaction_features=True, weights=weights)
        
        assert risk.probability > 0.6
        assert risk.incident.flagged
        assert "payment" in risk.incident.reason or "usage" in risk.incident.reason or "sentiment" in risk.incident.reason

    def test_payment_penalty(self):
        """Test payment status affects churn risk."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial_unpaid = FinancialSignal(arr_commit_usd=500_000, payment_status="unpaid")
        financial_current = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        risk_unpaid = compute_churn_risk(usage, sentiment, financial_unpaid, interaction_features=True, weights=weights)
        risk_current = compute_churn_risk(usage, sentiment, financial_current, interaction_features=True, weights=weights)
        
        assert risk_unpaid.probability > risk_current.probability

    def test_low_usage_penalty(self):
        """Test low usage affects churn risk."""
        usage_low = UsageSignal(active_features=2, total_features=10, weekly_actions=50)
        usage_high = UsageSignal(active_features=8, total_features=10, weekly_actions=400)
        sentiment = SentimentSignal(nps=0, csat=3)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        risk_low = compute_churn_risk(usage_low, sentiment, financial, interaction_features=True, weights=weights)
        risk_high = compute_churn_risk(usage_high, sentiment, financial, interaction_features=True, weights=weights)
        
        assert risk_low.probability > risk_high.probability

    def test_low_sentiment_penalty(self):
        """Test low sentiment affects churn risk."""
        usage = UsageSignal(active_features=5, total_features=10, weekly_actions=250)
        sentiment_low = SentimentSignal(nps=-30, csat=2)
        sentiment_high = SentimentSignal(nps=30, csat=4)
        financial = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        weights = HealthScoreWeights(usage=0.33, sentiment=0.33, financial=0.34)
        
        risk_low = compute_churn_risk(usage, sentiment_low, financial, interaction_features=True, weights=weights)
        risk_high = compute_churn_risk(usage, sentiment_high, financial, interaction_features=True, weights=weights)
        
        assert risk_low.probability > risk_high.probability


class TestDataclasses:
    """Test dataclass immutability."""

    def test_usage_signal_immutable(self):
        """Test UsageSignal is immutable."""
        signal = UsageSignal(active_features=5, total_features=10, weekly_actions=100)
        with pytest.raises(AttributeError):
            signal.active_features = 10

    def test_sentiment_signal_immutable(self):
        """Test SentimentSignal is immutable."""
        signal = SentimentSignal(nps=50, csat=4)
        with pytest.raises(AttributeError):
            signal.nps = 80

    def test_financial_signal_immutable(self):
        """Test FinancialSignal is immutable."""
        signal = FinancialSignal(arr_commit_usd=500_000, payment_status="current")
        with pytest.raises(AttributeError):
            signal.arr_commit_usd = 1_000_000
