"""Risk-core onboarding funnel and routing regression tests."""

from __future__ import annotations

import pytest

from analytics.onboarding_metrics import (
    OnboardingRiskExceeded,
    RoutingSnapshot,
    compute_routing_metrics,
    compute_step_dropoff_metrics,
    enforce_funnel_monotonicity,
    estimate_step_arr_recovery,
)


pytestmark = pytest.mark.risk_core


@pytest.fixture
def funnel_steps():
    return [
        {"step": "signup", "start": 400, "complete": 360},
        {"step": "kyc", "start": 360, "complete": 200},
        {"step": "integration", "start": 200, "complete": 120},
        {"step": "first_trade", "start": 120, "complete": 90},
    ]


def test_activation_cliff_surfaces_highest_arr_risk(funnel_steps):
    metrics = compute_step_dropoff_metrics(funnel_steps, arr_per_client=150_000)
    worst_step = max(metrics, key=lambda m: m.revenue_at_risk)
    assert worst_step.step == "kyc"
    assert worst_step.dropoff_ratio == pytest.approx((360 - 200) / 360)
    assert worst_step.revenue_at_risk == pytest.approx(160 * 150_000)


def test_reactivation_campaign_recovers_arr(funnel_steps):
    baseline = compute_step_dropoff_metrics(funnel_steps, arr_per_client=150_000)
    improved_steps = [
        {**step, "complete": step["start"] - max(10, (step["start"] - step["complete"]) // 2)}
        for step in funnel_steps
    ]
    improved = compute_step_dropoff_metrics(improved_steps, arr_per_client=150_000)
    recovered = estimate_step_arr_recovery(
        start=funnel_steps[1]["start"],
        old_dropoff=baseline[1].dropoff_ratio,
        new_dropoff=improved[1].dropoff_ratio,
        arr_per_client=150_000,
    )
    assert recovered > 0
    assert improved[1].revenue_at_risk < baseline[1].revenue_at_risk


def test_monotonicity_guard_blocks_silent_data_corruption():
    steps = [
        {"step": "signup", "start": 100, "complete": 90},
        {"step": "kyc", "start": 102, "complete": 95},  # unexpected increase
    ]
    with pytest.raises(OnboardingRiskExceeded):
        enforce_funnel_monotonicity(steps, tolerance=0.01)


def test_routing_snapshot_spike_flags_incident():
    snapshots = [
        RoutingSnapshot(
            name="venueA",
            total_orders=100,
            mismatches=2,
            avg_slippage_bps=2.0,
            p95_route_latency_ms=180,
        ),
        RoutingSnapshot(
            name="venueB",
            total_orders=80,
            mismatches=25,
            avg_slippage_bps=12.0,
            p95_route_latency_ms=600,
        ),
    ]
    with pytest.raises(OnboardingRiskExceeded):
        compute_routing_metrics(
            snapshots,
            mismatch_threshold=0.15,
            slippage_threshold_bps=5.0,
        )
