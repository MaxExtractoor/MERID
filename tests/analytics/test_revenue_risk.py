"""Risk-core revenue-at-risk analytics tests."""

from __future__ import annotations

import pytest

from analytics.revenue_risk import (
    ContractEvent,
    FxAdjustedARR,
    RevenueRiskIncident,
    compute_revenue_at_risk,
)


pytestmark = pytest.mark.risk_core


def test_arr_at_risk_adjusts_for_fx_moves() -> None:
    fx = [
        FxAdjustedARR(currency="USD", arr_local=1_000_000, fx_rate_to_usd=1.0),
        FxAdjustedARR(currency="EUR", arr_local=900_000, fx_rate_to_usd=1.1),
    ]

    incident = compute_revenue_at_risk(
        fx,
        churn_events=[],
        fx_shock_pct=0.1,
        threshold_usd=150_000,
    )

    assert isinstance(incident, RevenueRiskIncident)
    assert incident.flagged is True
    assert incident.breakdown["fx_shock"] == pytest.approx((1_000_000 + 990_000) * 0.1)
    assert incident.reason == "fx_shock"


def test_contract_downgrade_pipeline_flags_when_threshold_hit() -> None:
    events = [
        ContractEvent(account_id="ent-1", delta_arr_usd=-250_000, reason="downgrade"),
        ContractEvent(account_id="ent-2", delta_arr_usd=-120_000, reason="churn"),
    ]

    incident = compute_revenue_at_risk(
        fx_adjusted=[],
        churn_events=events,
        fx_shock_pct=0.0,
        threshold_usd=300_000,
    )

    assert incident.flagged is True
    assert incident.breakdown["contract_events"] == pytest.approx(370_000)
    assert incident.reason == "contract_events"


def test_combined_fx_and_contract_reason_and_threshold() -> None:
    fx = [FxAdjustedARR(currency="USD", arr_local=500_000, fx_rate_to_usd=1.0)]
    events = [ContractEvent(account_id="ent-9", delta_arr_usd=-80_000, reason="pausing")]

    incident = compute_revenue_at_risk(
        fx_adjusted=fx,
        churn_events=events,
        fx_shock_pct=0.05,
        threshold_usd=150_000,
    )

    assert incident.flagged is False
    assert incident.reason == "fx_shock_and_contract_events"
    assert incident.arr_at_risk_usd == pytest.approx(500_000 * 0.05 + 80_000)
