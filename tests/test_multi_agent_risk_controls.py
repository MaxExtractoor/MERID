"""High-risk tests for governance.multi_agent_risk_controls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from governance.multi_agent_risk_controls import (
    KillSwitchLevel,
    MultiAgentRiskControls,
)


def _make_social_strategy(name: str = "social-alpha") -> SimpleNamespace:
    return SimpleNamespace(is_social_strategy=True, social_assets=[f"{name}-asset"])


def test_cross_strategy_exposure_caps():
    controls = MultiAgentRiskControls()
    cap = controls.register_exposure_cap(
        cap_id="firmwide_btc",
        dimension="asset",
        entity="BTC",
        max_notional=150_000.0,
        max_leverage=5.0,
        max_concentration_pct=0.50,
    )

    controls._agent_positions["alpha"]["BTC"] = 90_000.0
    controls._agent_positions["beta"]["BTC"] = 40_000.0

    approved, violations = controls.check_exposure_caps(
        agent_id="gamma",
        proposed_position={"BTC": 50_000.0},
    )

    assert approved is False
    assert any(cap.cap_id in v for v in violations)

    breach_events = controls.get_risk_events(event_type="exposure_cap_breach")
    assert breach_events, "Exposure breach should be logged for auditability"
    assert breach_events[-1].action_taken == "rejected_position"


@pytest.mark.parametrize("strategy_name", ["social-alpha", "social-beta"])
def test_social_kill_switch_blocks_trades(strategy_name):
    controls = MultiAgentRiskControls()
    controls.register_kill_switch(
        switch_id="social_global",
        level=KillSwitchLevel.FIRM_WIDE,
        target="social",
    )
    controls.activate_kill_switch(
        switch_id="social_global",
        activated_by="governance",
        reason="Drawdown breach",
    )

    strategy = _make_social_strategy(strategy_name)
    constraints = {
        "confirmation_available": True,
        "data_fresh": True,
        "asset_exposure": 1_000.0,
        "kill_switch_active": controls.is_kill_switch_active(
            level=KillSwitchLevel.FIRM_WIDE,
            target="social",
        ),
        "kill_switch_reason": "Drawdown breach",
    }
    sizing_result = {
        "allowed": True,
        "portfolio_value": 100_000.0,
        "remaining_social_budget": 20_000.0,
        "constraints": constraints,
    }

    approved, violations = controls.validate_social_constraints(strategy, sizing_result)

    assert approved is False
    assert any("kill switch" in v.lower() for v in violations)


def test_governance_overrides_logged():
    controls = MultiAgentRiskControls()
    controls.register_kill_switch(
        switch_id="firm_social",
        level=KillSwitchLevel.FIRM_WIDE,
        target="social",
    )
    controls.activate_kill_switch(
        switch_id="firm_social",
        activated_by="risk-ops",
        reason="Social contagion",
    )

    strategy = _make_social_strategy("override-test")
    base_constraints = {
        "confirmation_available": True,
        "data_fresh": True,
        "asset_exposure": 1_000.0,
    }
    sizing_template = {
        "allowed": True,
        "portfolio_value": 100_000.0,
        "remaining_social_budget": 25_000.0,
    }

    constraints_blocked = {
        **base_constraints,
        "kill_switch_active": controls.is_kill_switch_active(
            level=KillSwitchLevel.FIRM_WIDE,
            target="social",
        ),
        "kill_switch_reason": "Social contagion",
    }
    blocked_result = {**sizing_template, "constraints": constraints_blocked}

    approved_before, violations_before = controls.validate_social_constraints(
        strategy,
        blocked_result,
    )
    assert approved_before is False
    assert any("kill switch" in v.lower() for v in violations_before)

    controls.deactivate_kill_switch(
        switch_id="firm_social",
        deactivated_by="governance-override",
        reason="Override approved",
    )

    constraints_after = {
        **base_constraints,
        "kill_switch_active": controls.is_kill_switch_active(
            level=KillSwitchLevel.FIRM_WIDE,
            target="social",
        ),
    }
    result_after = {**sizing_template, "constraints": constraints_after}

    approved_after, violations_after = controls.validate_social_constraints(
        strategy,
        result_after,
    )
    assert approved_after is True
    assert violations_after == []

    override_events = controls.get_risk_events(event_type="kill_switch_deactivated")
    assert any(
        event.metadata.get("deactivated_by") == "governance-override"
        for event in override_events
    ), "Governance override should log a kill-switch deactivation"
