"""Risk-core health score and churn risk tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from analytics.health_score import (
    ChurnRisk,
    FinancialSignal,
    HealthScoreWeights,
    InteractionFeaturesMissing,
    RiskIncident,
    SentimentSignal,
    UsageSignal,
    compute_churn_risk,
    compute_health_score,
)


pytestmark = pytest.mark.risk_core


@pytest.fixture
def baseline_signals():
    return (
        UsageSignal(active_features=8, total_features=12, weekly_actions=400),
        SentimentSignal(nps=10, csat=4.5),
        FinancialSignal(arr_commit_usd=500_000, payment_status="current"),
    )


@pytest.fixture
def weights():
    return HealthScoreWeights(usage=0.4, sentiment=0.3, financial=0.3)


def test_health_score_blend_reflects_sentiment_drop(baseline_signals, weights):
    usage, sentiment, financial = baseline_signals
    initial = compute_health_score(usage, sentiment, financial, weights=weights)
    degraded_sentiment = replace(sentiment, nps=-30)
    degraded = compute_health_score(usage, degraded_sentiment, financial, weights=weights)
    assert degraded < initial
    assert 0 <= degraded <= 1


def test_health_score_bounds_when_usage_extreme(baseline_signals, weights):
    usage, sentiment, financial = baseline_signals
    high_usage = replace(usage, weekly_actions=2_000)
    score = compute_health_score(high_usage, sentiment, financial, weights=weights)
    assert 0.0 <= score <= 1.0
    low_usage = replace(usage, weekly_actions=0)
    score_low = compute_health_score(low_usage, sentiment, financial, weights=weights)
    assert 0.0 <= score_low <= 1.0


def test_churn_risk_incident_on_multi_signal_collapse(baseline_signals, weights):
    usage, sentiment, financial = baseline_signals
    degraded_usage = replace(usage, weekly_actions=60)
    degraded_sentiment = replace(sentiment, csat=2.5, nps=-40)
    delinquent_financial = replace(financial, payment_status="delinquent")

    risk = compute_churn_risk(
        degraded_usage,
        degraded_sentiment,
        delinquent_financial,
        interaction_features=True,
        weights=weights,
    )
    assert isinstance(risk, ChurnRisk)
    assert risk.probability > 0.7
    assert isinstance(risk.incident, RiskIncident)
    assert risk.incident.flagged is True
    assert "payment" in risk.incident.reason


def test_churn_probability_clipped_at_one(baseline_signals, weights):
    usage, sentiment, financial = baseline_signals
    collapse_usage = replace(usage, weekly_actions=0)
    collapse_sentiment = replace(sentiment, nps=-100, csat=1.0)
    unpaid_financial = replace(financial, payment_status="unpaid")
    risk = compute_churn_risk(
        collapse_usage,
        collapse_sentiment,
        unpaid_financial,
        interaction_features=True,
        weights=weights,
    )
    assert risk.probability == 1.0


def test_interaction_features_missing_guard(baseline_signals, weights):
    usage, sentiment, financial = baseline_signals
    with pytest.raises(InteractionFeaturesMissing):
        compute_churn_risk(usage, sentiment, financial, interaction_features=False, weights=weights)
