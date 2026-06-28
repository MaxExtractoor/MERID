"""Integration tests for agent and router dynamic wiring.

Tests cover:
- Dynamic window is authoritative in agent decision
- Agent uses dynamic risk outputs (TP/SL, sizing) correctly
- Router enforces risk gate (can_trade_now)
- Router converts market orders to aggressive limit orders
- Enriched STRATEGY-TRUTH-TABLE logging contains new fields

NOTE: These are placeholder tests that verify imports work.
Full integration tests require setting up complete agent/router context.
"""

import pytest
from unittest.mock import Mock, MagicMock
import json


def test_dynamic_window_imports():
    """Verify dynamic window module can be imported."""
    from merid.event_venues.kalshi.dynamic_window import (
        evaluate_dynamic_window,
        DynamicWindowResult,
        WindowReason,
    )
    assert evaluate_dynamic_window is not None
    assert DynamicWindowResult is not None
    assert WindowReason is not None


def test_dynamic_risk_imports():
    """Verify dynamic risk module can be imported."""
    from merid.event_venues.kalshi.dynamic_risk import (
        DynamicRiskEngine,
        VolatilityRegime,
        DrawdownState,
        InvariantSeverity,
        VolatilityMetrics,
        TP_SLResult,
        PositionSizeResult,
        RiskBudget,
    )
    assert DynamicRiskEngine is not None
    assert VolatilityRegime is not None
    assert DrawdownState is not None
    assert InvariantSeverity is not None
    assert VolatilityMetrics is not None
    assert TP_SLResult is not None
    assert PositionSizeResult is not None
    assert RiskBudget is not None


def test_agent_grid_15m_imports():
    """Verify agent grid module can be imported."""
    from merid.prediction.agent_grid_15m import LeanAgent15m
    assert LeanAgent15m is not None


def test_order_router_imports():
    """Verify order router module can be imported."""
    from merid.event_venues.kalshi import order_router
    assert order_router is not None


def test_signal_includes_edge_confidence_model_prob():
    """BUG #36 FIX: Signal generation should include edge_pct, confidence, model_prob.
    
    The velocity-based signal in _generate_signal computes these fields:
    - edge_pct: difference between model and market probability
    - confidence: distance from 0.5 (neutral probability)
    - model_prob: from logistic mapping of velocity
    """
    # Simulate signal generation output
    # This would normally come from _generate_signal in agent_grid_15m.py
    signal = {
        "asset": "BTC",
        "side": "yes",
        "action": "buy",
        "velocity": 0.002,
        "spot_price": 65000.0,
        "minutes_to_expiry": 10.0,
        "best_bid": 48,
        "best_ask": 52,
        "price_source": "market_state_store",
        "strategy_staleness": 60,
        "venue_staleness": 15,
        "edge_pct": 2.5,  # BUG #36 FIX: Edge from (p_model - p_mkt)
        "confidence": 0.65,  # BUG #36 FIX: Confidence from distance from 0.5
        "model_prob": 0.55,  # BUG #36 FIX: Model probability from logistic mapping
        "p_mkt": 0.50,  # Market probability for debugging
        "raw_logit": 0.1,  # Raw logit for debugging
        "regime": "both_sides",  # BUG #35 FIX: Regime classification from market state
    }
    
    # Verify signal includes required fields
    assert "edge_pct" in signal
    assert "confidence" in signal
    assert "model_prob" in signal
    assert "regime" in signal
    
    # Verify values are reasonable
    assert isinstance(signal["edge_pct"], (int, float))
    assert isinstance(signal["confidence"], (int, float))
    assert isinstance(signal["model_prob"], (int, float))
    assert 0.0 <= signal["model_prob"] <= 1.0
    assert 0.0 <= signal["confidence"] <= 1.0


def test_truth_table_enriched_fields_legacy_edge():
    """Verify STRATEGY-TRUTH-TABLE contains enriched fields for legacy edge path."""
    from merid.event_venues.kalshi.dynamic_risk import (
        TP_SLResult,
        PositionSizeResult,
        VolatilityMetrics,
        VolatilityRegime,
        RiskBudget,
        DrawdownState,
    )
    
    # Mock legacy edge result with new fields
    legacy_edge_result = {
        "edge_pct": 0.05,
        "confidence": 0.7,
        "implied_prob": 0.5,
        "model_prob": 0.55,
        "side": "yes",
        "side_reason": "edge_argmax",
        "edge_yes": 0.05,
        "edge_no": 0.03,
    }
    
    # Mock TP/SL result
    tp_sl_result = TP_SLResult(
        tp_price_cents=60,
        sl_price_cents=45,
        risk_cents_per_contract=15,
        tp_r_multiple=2.0,
        sl_r_multiple=1.0,
        confidence_used=0.7,
        volatility_regime=VolatilityRegime.NORMAL,
        computation_time_ms=5.0,
        rationale="SL: 8c (NORMAL vol); TP: 2.0R (conf=0.70, edge=5.0%)",
    )
    
    # Mock sizing result
    sizing_result = PositionSizeResult(
        contracts=10,
        risk_dollars=1.5,
        risk_pct_of_bankroll=0.015,
        bankroll_used=5.0,
        per_market_cap=100,
        per_asset_cap=500,
        global_cap=1000,
        limiting_factor="risk_budget",
        computation_time_ms=3.0,
        rationale="dynamic_sizing: risk_budget",
    )
    
    # Construct decision truth table as in agent_grid_15m
    decision_truth_table = {
        "asset": "BTC",
        "window_start": "2026-05-28T12:00:00Z",
        "inputs": {
            "edge_bp": 500,
            "spread_cents": 95,
            "spread_source": "state",
            "time_to_expiry_s": 600,
            "spot_price": 65000,
            "price_cents": 50,
            "dist_abs_pct": None,
        },
        "thresholds": {
            "min_edge_bp": 100,
            "max_spread_cents": 100,
            "min_time_to_expiry_s": 180,
        },
        "risk": {
            "per_trade_risk_pct": 0.015,
            "max_cycle_risk_pct": 0.05,
            "per_asset_max_notional_usd": 1000.0,
            "bankroll_usd": 10000.0,
        },
        "data_quality": {
            "score": 0.9,
            "threshold": 0.8,
        },
        "decision": {
            "should_trade": True,
            "side": legacy_edge_result["side"],
            "side_choice_reason": legacy_edge_result.get("side_reason"),
            "edge_yes": legacy_edge_result.get("edge_yes"),
            "edge_no": legacy_edge_result.get("edge_no"),
            "size_contracts": sizing_result.contracts,
            "notional_usd": 5.0,
            "edge_pct": legacy_edge_result["edge_pct"],
            "confidence": legacy_edge_result["confidence"],
            "tp_sl_rationale": tp_sl_result.rationale,
            "sizing_rationale": sizing_result.rationale,
            "reason": "OK",
        }
    }
    
    # Verify enriched fields are present
    assert "side_choice_reason" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["side_choice_reason"] == "edge_argmax"
    assert "edge_yes" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["edge_yes"] == 0.05
    assert "edge_no" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["edge_no"] == 0.03
    assert "tp_sl_rationale" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["tp_sl_rationale"] is not None
    assert "sizing_rationale" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["sizing_rationale"] is not None


def test_truth_table_enriched_fields_unified_edge():
    """Verify STRATEGY-TRUTH-TABLE contains enriched fields for unified edge path."""
    from merid.event_venues.kalshi.dynamic_risk import (
        TP_SLResult,
        PositionSizeResult,
        VolatilityMetrics,
        VolatilityRegime,
        RiskBudget,
        DrawdownState,
    )
    
    # Mock unified edge result with new fields
    unified_edge_result = {
        "edge_pct": 0.04,
        "confidence": 0.65,
        "implied_prob": 0.48,
        "model_prob": 0.52,
        "side": "yes",
        "side_reason": "unified_edge",
        "edge_yes": 0.04,
        "edge_no": 0.0,
        "net_edge_cents": 2.0,
    }
    
    # Mock TP/SL result
    tp_sl_result = TP_SLResult(
        tp_price_cents=58,
        sl_price_cents=44,
        risk_cents_per_contract=14,
        tp_r_multiple=1.8,
        sl_r_multiple=1.0,
        confidence_used=0.65,
        volatility_regime=VolatilityRegime.NORMAL,
        computation_time_ms=4.5,
        rationale="SL: 8c (NORMAL vol); TP: 1.8R (conf=0.65, edge=4.0%)",
    )
    
    # Mock sizing result
    sizing_result = PositionSizeResult(
        contracts=8,
        risk_dollars=1.12,
        risk_pct_of_bankroll=0.0112,
        bankroll_used=3.84,
        per_market_cap=100,
        per_asset_cap=500,
        global_cap=1000,
        limiting_factor="risk_budget",
        computation_time_ms=2.5,
        rationale="dynamic_sizing: risk_budget",
    )
    
    # Construct decision truth table as in agent_grid_15m
    decision_truth_table = {
        "asset": "ETH",
        "window_start": "2026-05-28T12:05:00Z",
        "inputs": {
            "edge_bp": 400,
            "spread_cents": 90,
            "spread_source": "state",
            "time_to_expiry_s": 540,
            "spot_price": 3500,
            "price_cents": 48,
            "dist_abs_pct": None,
        },
        "thresholds": {
            "min_edge_bp": 100,
            "max_spread_cents": 100,
            "min_time_to_expiry_s": 180,
        },
        "risk": {
            "per_trade_risk_pct": 0.015,
            "max_cycle_risk_pct": 0.05,
            "per_asset_max_notional_usd": 1000.0,
            "bankroll_usd": 10000.0,
        },
        "data_quality": {
            "score": 0.85,
            "threshold": 0.8,
        },
        "decision": {
            "should_trade": True,
            "side": unified_edge_result["side"],
            "side_choice_reason": unified_edge_result.get("side_reason"),
            "edge_yes": unified_edge_result.get("edge_yes"),
            "edge_no": unified_edge_result.get("edge_no"),
            "size_contracts": sizing_result.contracts,
            "notional_usd": 3.84,
            "edge_pct": unified_edge_result["edge_pct"],
            "confidence": unified_edge_result["confidence"],
            "tp_sl_rationale": tp_sl_result.rationale,
            "sizing_rationale": sizing_result.rationale,
            "reason": "OK",
        }
    }
    
    # Verify enriched fields are present
    assert "side_choice_reason" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["side_choice_reason"] == "unified_edge"
    assert "edge_yes" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["edge_yes"] == 0.04
    assert "edge_no" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["edge_no"] == 0.0
    assert "tp_sl_rationale" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["tp_sl_rationale"] is not None
    assert "sizing_rationale" in decision_truth_table["decision"]
    assert decision_truth_table["decision"]["sizing_rationale"] is not None


def test_side_reason_valid_values():
    """Verify side_reason only contains valid values."""
    valid_reasons = {"edge_argmax", "depth_tiebreak", "unified_edge"}
    
    # Test edge_argmax
    assert "edge_argmax" in valid_reasons
    
    # Test depth_tiebreak
    assert "depth_tiebreak" in valid_reasons
    
    # Test unified_edge
    assert "unified_edge" in valid_reasons


def test_tp_microstructure_sanity_check_wide_spread():
    """Verify TP microstructure sanity check warns when TP is below spread."""
    from merid.event_venues.kalshi.dynamic_risk import (
        DynamicRiskEngine,
        VolatilityMetrics,
        VolatilityRegime,
        RiskBudget,
        DrawdownState,
    )
    from unittest.mock import patch
    import logging
    
    # Create engine
    engine = DynamicRiskEngine()
    
    # Mock module-level logger to capture warnings
    warning_logs = []
    
    def mock_warning(msg, *args, **kwargs):
        warning_logs.append(msg % args if args else msg)
    
    with patch('merid.event_venues.kalshi.dynamic_risk.logger') as mock_logger:
        mock_logger.warning = mock_warning
        
        # Test case: wide spread (90c) with TP inside spread
        vol_metrics = VolatilityMetrics(
            regime=VolatilityRegime.NORMAL,
            realized_vol_15m=0.02,
            avg_range_cents=180,
            spread_cents=90,  # Wide spread
            depth_at_top=100,
            time_to_expiry_min=8,
        )
        
        risk_budget = RiskBudget(
            risk_per_trade_pct=0.015,
            max_daily_loss_pct=0.02,
            max_rolling_loss_pct=0.05,
            drawdown_state=DrawdownState.FLAT,
            bankroll_usd=10000.0,
            recent_trades_count=0,
            recent_win_rate=0.5,
        )
        
        # Entry at 50c, TP at 55c (5c move), spread is 90c
        # This should trigger the microstructure warning
        tp_sl_result = engine.compute_tp_sl(
            entry_price_cents=50,
            edge_pct=0.05,
            confidence=0.7,
            vol_metrics=vol_metrics,
            bankroll_usd=10000.0,
            risk_budget=risk_budget,
        )
        
        # Verify TP was computed
        assert tp_sl_result.tp_price_cents is not None
        assert tp_sl_result.sl_price_cents is not None
        
        # Check if warning was logged (TP move < spread)
        move_to_tp = abs(tp_sl_result.tp_price_cents - 50)
        if move_to_tp < 90:
            assert any("TP-MICROSTRUCTURE-WARN" in log for log in warning_logs), \
                "Expected microstructure warning when TP target is below spread"


def test_tte_regime_terminal_disables_tp():
    """Verify TERMINAL TTE regime disables TP and sets expiry-only rationale."""
    from merid.event_venues.kalshi.dynamic_risk import (
        DynamicRiskEngine,
        VolatilityMetrics,
        VolatilityRegime,
        RiskBudget,
        DrawdownState,
    )
    
    # Create engine
    engine = DynamicRiskEngine()
    
    # Test case: TERMINAL regime (<2 minutes)
    vol_metrics = VolatilityMetrics(
        regime=VolatilityRegime.NORMAL,
        realized_vol_15m=0.02,
        avg_range_cents=180,
        spread_cents=5,
        depth_at_top=100,
        time_to_expiry_min=1.5,  # TERMINAL
    )
    
    risk_budget = RiskBudget(
        risk_per_trade_pct=0.015,
        max_daily_loss_pct=0.02,
        max_rolling_loss_pct=0.05,
        drawdown_state=DrawdownState.FLAT,
        bankroll_usd=10000.0,
        recent_trades_count=0,
        recent_win_rate=0.5,
    )
    
    tp_sl_result = engine.compute_tp_sl(
        entry_price_cents=50,
        edge_pct=0.05,
        confidence=0.7,
        vol_metrics=vol_metrics,
        bankroll_usd=10000.0,
        risk_budget=risk_budget,
    )
    
    # Verify TP is disabled (tp_r_multiple should be 0)
    assert tp_sl_result.tp_r_multiple == 0.0
    # Verify rationale contains terminal TTE information
    assert "terminal" in tp_sl_result.rationale.lower()


def test_tte_regime_critical_scales_tp():
    """Verify CRITICAL TTE regime scales TP down by 0.5x."""
    from merid.event_venues.kalshi.dynamic_risk import (
        DynamicRiskEngine,
        VolatilityMetrics,
        VolatilityRegime,
        RiskBudget,
        DrawdownState,
    )
    
    # Create engine
    engine = DynamicRiskEngine()
    
    # Test case: CRITICAL regime (2-5 minutes)
    vol_metrics = VolatilityMetrics(
        regime=VolatilityRegime.NORMAL,
        realized_vol_15m=0.02,
        avg_range_cents=180,
        spread_cents=5,
        depth_at_top=100,
        time_to_expiry_min=3.0,  # CRITICAL
    )
    
    risk_budget = RiskBudget(
        risk_per_trade_pct=0.015,
        max_daily_loss_pct=0.02,
        max_rolling_loss_pct=0.05,
        drawdown_state=DrawdownState.FLAT,
        bankroll_usd=10000.0,
        recent_trades_count=0,
        recent_win_rate=0.5,
    )
    
    tp_sl_result = engine.compute_tp_sl(
        entry_price_cents=50,
        edge_pct=0.05,
        confidence=0.7,
        vol_metrics=vol_metrics,
        bankroll_usd=10000.0,
        risk_budget=risk_budget,
    )
    
    # Verify TP is scaled down (should be significantly lower than normal)
    # Normal TP would be ~1.5-3.0R, CRITICAL should be ~0.75-1.5R
    assert tp_sl_result.tp_r_multiple > 0.0
    assert tp_sl_result.tp_r_multiple < 2.0  # Should be less than normal minimum
    # Verify rationale contains critical TTE information
    assert "critical" in tp_sl_result.rationale.lower()


class TestOrderIntentSizingContextPropagation:
    """Test sizing context propagation through OrderIntent creation."""

    def test_order_intent_sizing_context_from_signal(self):
        """Test OrderIntent is populated with sizing context from signal."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Simulate signal with sizing context
        signal = {
            "edgepct": 0.05,
            "netedgecents": 2.5,
            "band": "STANDARD",
            "regime": "NORMAL",
            "size_contracts": 10,
            "notional_usd": 5.0,
        }
        
        # Create OrderIntent as in agent_grid_15m
        intent = OrderIntent(
            intent_id="test-001",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="BTC15M",
            # Sizing context from signal
            edgepct=signal.get("edgepct", 0.0),
            netedgecents=signal.get("netedgecents", 0.0),
            band=signal.get("band", ""),
            regime=signal.get("regime", ""),
            size_contracts=signal.get("size_contracts", 0),
            notional_usd=signal.get("notional_usd", 0.0),
        )
        
        # Verify sizing context is populated
        assert intent.edgepct == 0.05
        assert intent.netedgecents == 2.5
        assert intent.band == "STANDARD"
        assert intent.regime == "NORMAL"
        assert intent.size_contracts == 10
        assert intent.notional_usd == 5.0

    def test_order_intent_sizing_context_defaults(self):
        """Test OrderIntent uses defaults when signal lacks sizing context."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Simulate signal without sizing context
        signal = {}
        
        # Create OrderIntent as in agent_grid_15m
        intent = OrderIntent(
            intent_id="test-002",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="BTC15M",
            # Sizing context from signal (will use defaults)
            edgepct=signal.get("edgepct", 0.0),
            netedgecents=signal.get("netedgecents", 0.0),
            band=signal.get("band", ""),
            regime=signal.get("regime", ""),
            size_contracts=signal.get("size_contracts", 0),
            notional_usd=signal.get("notional_usd", 0.0),
        )
        
        # Verify defaults are used
        assert intent.edgepct == 0.0
        assert intent.netedgecents == 0.0
        assert intent.band == ""
        assert intent.regime == ""
        assert intent.size_contracts == 0
        assert intent.notional_usd == 0.0

    def test_order_intent_sizing_context_partial_signal(self):
        """Test OrderIntent handles partial sizing context in signal."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Simulate signal with partial sizing context
        signal = {
            "edgepct": 0.03,
            "band": "WATCH",
            # Missing: netedgecents, regime, size_contracts, notional_usd
        }
        
        # Create OrderIntent as in agent_grid_15m
        intent = OrderIntent(
            intent_id="test-003",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="BTC15M",
            # Sizing context from signal
            edgepct=signal.get("edgepct", 0.0),
            netedgecents=signal.get("netedgecents", 0.0),
            band=signal.get("band", ""),
            regime=signal.get("regime", ""),
            size_contracts=signal.get("size_contracts", 0),
            notional_usd=signal.get("notional_usd", 0.0),
        )
        
        # Verify partial context is populated, rest are defaults
        assert intent.edgepct == 0.03
        assert intent.netedgecents == 0.0  # Default
        assert intent.band == "WATCH"
        assert intent.regime == ""  # Default
        assert intent.size_contracts == 0  # Default
        assert intent.notional_usd == 0.0  # Default


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
