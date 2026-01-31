"""Unit tests for analytics.onboarding_metrics."""

from __future__ import annotations

import pytest

from analytics.onboarding_metrics import (
    OnboardingRiskExceeded,
    RoutingSnapshot,
    SegmentRecord,
    compute_routing_metrics,
    compute_segment_metrics,
    compute_ttv_churn_delta,
    compute_step_dropoff_metrics,
    estimate_step_arr_recovery,
    estimate_cltv_loss,
)


pytestmark = pytest.mark.risk_core


def test_compute_segment_metrics_basics_and_threshold():
    records = [
        SegmentRecord("enterprise", starts=10, abandoned=2, avg_annual_revenue=1_000_000, expected_years=4),
        SegmentRecord("smb", starts=100, abandoned=5, avg_annual_revenue=50_000, expected_years=3),
    ]

    metrics = compute_segment_metrics(records, abandonment_threshold=0.3)
    enterprise = next(m for m in metrics if m.segment == "enterprise")

    assert pytest.approx(0.2) == enterprise.abandonment_rate
    assert pytest.approx(4_000_000.0) == enterprise.estimated_cltv
    # Lost revenue = abandonment_rate * starts * CLTV
    assert pytest.approx(0.2 * 10 * 4_000_000) == enterprise.estimated_lost_revenue

    # Threshold breach should raise
    with pytest.raises(OnboardingRiskExceeded):
        compute_segment_metrics(records, abandonment_threshold=0.05)


def test_compute_ttv_churn_delta_requires_baseline_and_returns_deltas():
    churn = {
        "lt14": 0.05,
        "14_30": 0.08,
        "30_60": 0.12,
    }

    deltas = compute_ttv_churn_delta(churn, baseline_cohort="lt14")
    assert deltas["lt14"] == pytest.approx(0.0)
    assert deltas["30_60"] == pytest.approx(0.07)

    with pytest.raises(KeyError):
        compute_ttv_churn_delta(churn, baseline_cohort="missing")


def test_estimate_cltv_loss_handles_churn_and_delay():
    loss = estimate_cltv_loss(
        cltv_base=100_000,
        delta_churn=0.1,
        delay_days=30,
        daily_revenue=500,
    )
    # CLTV adjusted: 100k * (1-0.1) - 30*500 = 75k => loss 25k
    assert pytest.approx(25_000) == loss

    # No negative loss even if churn delta is negative
    zero_loss = estimate_cltv_loss(
        cltv_base=50_000,
        delta_churn=-0.05,
        delay_days=0,
        daily_revenue=0,
    )
    assert zero_loss == pytest.approx(0.0)


def test_compute_routing_metrics_returns_rates_and_enforces_thresholds():
    snapshots = [
        RoutingSnapshot(name="venueA", total_orders=100, mismatches=2, avg_slippage_bps=1.5, p95_route_latency_ms=200),
        RoutingSnapshot(name="venueB", total_orders=50, mismatches=1, avg_slippage_bps=5.0, p95_route_latency_ms=500),
    ]

    results = compute_routing_metrics(snapshots, mismatch_threshold=0.1, slippage_threshold_bps=5.0)
    assert len(results) == 2
    # Convert to dict keyed by name for convenience
    as_dict = {name: (mismatch, slippage) for name, mismatch, slippage in results}
    assert pytest.approx(0.02) == as_dict["venueA"][0]
    assert pytest.approx(1.5) == as_dict["venueA"][1]

    # Threshold breach for mismatch
    high_mismatch = [RoutingSnapshot("venueC", total_orders=10, mismatches=5, avg_slippage_bps=1.0, p95_route_latency_ms=100)]
    with pytest.raises(OnboardingRiskExceeded):
        compute_routing_metrics(high_mismatch, mismatch_threshold=0.2)

    # Threshold breach for slippage
    with pytest.raises(OnboardingRiskExceeded):
        compute_routing_metrics(snapshots, slippage_threshold_bps=1.0)


def test_step_dropoff_metrics_and_revenue_at_risk():
    steps = [
        {"step": "signup", "start": 100, "complete": 80},
        {"step": "kyc", "start": 80, "complete": 50},
        {"step": "integration", "start": 50, "complete": 45},
    ]

    results = compute_step_dropoff_metrics(steps, arr_per_client=100_000)
    by_step = {metric.step: metric for metric in results}

    assert by_step["signup"].dropoff_ratio == pytest.approx(0.2)
    assert by_step["signup"].revenue_at_risk == pytest.approx(20 * 100_000)
    assert by_step["kyc"].dropoff_ratio == pytest.approx(0.375)
    assert by_step["kyc"].revenue_at_risk == pytest.approx(30 * 100_000)
    assert by_step["integration"].dropoff_ratio == pytest.approx(0.1)

    # KYC step should carry the highest ARR risk
    worst_step = max(results, key=lambda m: m.revenue_at_risk)
    assert worst_step.step == "kyc"


def test_estimate_step_arr_recovery():
    recovered = estimate_step_arr_recovery(
        start=80,
        old_dropoff=0.375,
        new_dropoff=0.25,
        arr_per_client=100_000,
    )

    assert recovered == pytest.approx(10 * 100_000)


def test_step_dropoff_handles_zero_and_full_drop():
    steps = [
        {"step": "signup", "start": 0, "complete": 0},
        {"step": "kyc", "start": 40, "complete": 0},
    ]

    results = compute_step_dropoff_metrics(steps, arr_per_client=50_000)
    signup = next(m for m in results if m.step == "signup")
    kyc = next(m for m in results if m.step == "kyc")

    assert signup.dropoff_ratio == pytest.approx(0.0)
    assert signup.revenue_at_risk == pytest.approx(0.0)
    assert kyc.dropoff_ratio == pytest.approx(1.0)
    assert kyc.revenue_at_risk == pytest.approx(40 * 50_000)


def test_estimate_step_arr_recovery_rejects_negative_starts():
    with pytest.raises(ValueError):
        estimate_step_arr_recovery(start=-1, old_dropoff=0.2, new_dropoff=0.1, arr_per_client=10_000)
