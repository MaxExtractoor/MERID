"""End-to-end scenario test for full strip with dynamic risk.

This is a minimal "smoke test" that verifies the dynamic risk components
can be instantiated and used together.

NOTE: Full end-to-end tests require complete agent/router context.
This test verifies the components work in isolation.
"""

import pytest
from datetime import datetime, timedelta, timezone

from merid.event_venues.kalshi.dynamic_risk import (
    DynamicRiskEngine,
    VolatilityRegime,
    VolatilityMetrics,
    RiskBudget,
    InvariantSeverity,
)
from merid.event_venues.kalshi.dynamic_window import (
    evaluate_dynamic_window,
    DynamicWindowResult,
    WindowReason,
)


def test_dynamic_window_healthy_conditions():
    """Test dynamic window allows trading with healthy conditions."""
    now = datetime.now(timezone.utc)
    strip_start = now - timedelta(seconds=60)
    strip_end = now + timedelta(seconds=600)
    
    result = evaluate_dynamic_window(
        now=now,
        strip_start=strip_start,
        strip_end=strip_end,
        spread_cents=3,
        depth_at_top=20,
        is_stale=False,
        vol_regime="NORMAL",
        execution_slippage=0.5,
        execution_fill_rate=0.95,
        cooldown_active=False,
        drawdown_state="FLAT",
        recent_invariant_violations=0,
        shadow_mode=False,
    )
    
    assert result.would_allow_trade
    assert result.reason == WindowReason.ALLOWED


def test_dynamic_risk_engine_creation():
    """Test DynamicRiskEngine can be instantiated."""
    engine = DynamicRiskEngine()
    assert engine is not None
    assert engine._daily_pnl_usd == 0.0
    assert engine._peak_bankroll == 0.0


def test_risk_gate_cooldown():
    """Test risk gate blocks on cooldown."""
    engine = DynamicRiskEngine()
    engine.register_invariant_violation(
        severity=InvariantSeverity.MINOR,
        reason="Test cooldown",
    )
    
    can_trade, reason = engine.can_trade_now()
    assert not can_trade
    assert "cooldown" in reason.lower()


def test_execution_metrics_tracking():
    """Test execution metrics can be tracked."""
    engine = DynamicRiskEngine()
    engine.update_execution_metrics("BTC", slippage_cents=0.5, filled=True)
    
    metrics = engine.get_execution_metrics("BTC")
    assert metrics is not None
    assert metrics["avg_slippage"] == 0.5
    assert metrics["fill_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
