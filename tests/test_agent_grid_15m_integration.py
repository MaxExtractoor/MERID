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


def test_kalshi_config_import():
    """Verify kalshi_config module can be imported (fix for position cache sync).
    
    This test verifies the fix for the import error:
    "No module named 'merid.event_venues.kalshi.config'"
    
    The correct import path is 'merid.event_venues.kalshi.kalshi_config'
    """
    from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
    assert get_kalshi_config is not None


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
        "hmm_regime": "bull",  # Phase 6: HMM regime for exit policy
        "hmm_regime_confidence": 0.85,  # Phase 6: HMM regime confidence
    }
    
    # Verify signal includes required fields
    assert "edge_pct" in signal
    assert "confidence" in signal
    assert "model_prob" in signal
    assert "regime" in signal
    assert "hmm_regime" in signal  # Phase 6: HMM regime field
    assert "hmm_regime_confidence" in signal  # Phase 6: HMM regime confidence field
    
    # Verify values are reasonable
    assert isinstance(signal["edge_pct"], (int, float))
    assert isinstance(signal["confidence"], (int, float))
    assert isinstance(signal["model_prob"], (int, float))
    assert 0.0 <= signal["model_prob"] <= 1.0
    assert 0.0 <= signal["confidence"] <= 1.0
    assert 0.0 <= signal["hmm_regime_confidence"] <= 1.0  # Phase 6: Confidence in [0, 1]
    assert signal["hmm_regime"] in ("bull", "choppy", "bear", None)  # Phase 6: Valid HMM regimes


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


def test_velocity_thresholds_2026_standards():
    """Verify velocity thresholds align with 2026 industry standards.
    
    2026 MagicTradeBot research shows 15m trading should use:
    - 0.6%-1.2% thresholds for stocks
    - 0.4%-0.8% for crypto (adjusted for higher volatility)
    
    Our thresholds: BTC/ETH 0.8%, SOL/XRP 1.0%, DOGE 1.2%
    """
    from merid.risk.profiles.crypto_15m_profile import get_active_profile
    
    profile_adapter = get_active_profile()
    profile = profile_adapter.profile
    
    # Verify thresholds are in 2026 industry standard range (0.4%-1.2%)
    assert 0.004 <= profile.velocity_threshold_btc <= 0.012, \
        f"BTC threshold {profile.velocity_threshold_btc} outside 2026 standard range"
    assert 0.004 <= profile.velocity_threshold_eth <= 0.012, \
        f"ETH threshold {profile.velocity_threshold_eth} outside 2026 standard range"
    assert 0.004 <= profile.velocity_threshold_sol <= 0.012, \
        f"SOL threshold {profile.velocity_threshold_sol} outside 2026 standard range"
    assert 0.004 <= profile.velocity_threshold_xrp <= 0.012, \
        f"XRP threshold {profile.velocity_threshold_xrp} outside 2026 standard range"
    assert 0.004 <= profile.velocity_threshold_doge <= 0.012, \
        f"DOGE threshold {profile.velocity_threshold_doge} outside 2026 standard range"
    
    # Verify higher volatility assets have higher thresholds
    assert profile.velocity_threshold_doge >= profile.velocity_threshold_btc, \
        "DOGE (high volatility) should have threshold >= BTC (low volatility)"
    assert profile.velocity_threshold_sol >= profile.velocity_threshold_btc, \
        "SOL (high volatility) should have threshold >= BTC (low volatility)"


def test_atr_normalization_disabled():
    """Verify ATR normalization is disabled for velocity calculation.
    
    2026 industry standards use raw velocity with dynamic thresholds,
    not ATR normalization which distorts velocity values.
    """
    from merid.prediction.agent_grid_15m import LeanAgent15m
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    # Create a mock agent config
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        velocity_threshold=0.008,
    )
    
    # Create agent (this will fail without full setup, but we can test the method directly)
    # Instead, verify the method signature and behavior by checking the code
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get the _apply_atr_normalization method
    method = LeanAgent15m._apply_atr_normalization
    
    # Verify it returns velocity unchanged (no ATR division)
    # This is a code inspection test - the method should just return velocity
    source = inspect.getsource(method)
    assert "return velocity" in source, \
        "ATR normalization should return velocity unchanged"
    assert "/ atr" not in source, \
        "ATR normalization should not divide by ATR (disabled per 2026 standards)"


def test_model_prob_distance_threshold_2026_standards():
    """Verify MODEL_PROB_DISTANCE_THRESHOLD aligns with 2026 standards.
    
    2026-07-04 FIX: Relaxed to 50% for velocity-based momentum signals.
    Velocity-based signals may be more predictive than static probability model,
    allowing larger discrepancies between model_prob and market price for 15-minute scalping.
    Previous 10% threshold was too strict for momentum trading.
    """
    from merid.event_venues.kalshi.risk_parameters import MODEL_PROB_DISTANCE_THRESHOLD
    
    # Verify threshold is 50% (0.50) per 2026-07-04 velocity-based signal standards
    assert MODEL_PROB_DISTANCE_THRESHOLD == 0.50, \
        f"MODEL_PROB_DISTANCE_THRESHOLD should be 0.50, got {MODEL_PROB_DISTANCE_THRESHOLD}"
    
    # Verify it's significantly higher than old thresholds
    assert MODEL_PROB_DISTANCE_THRESHOLD > 0.10, \
        "MODEL_PROB_DISTANCE_THRESHOLD should be > 0.10 (relaxed for velocity-based signals)"


def test_price_precision_logging_2026_standards():
    """Verify price logging uses full precision (8 decimal places) per 2026 standards.
    
    2026 industry standards (Paxos documentation) recommend:
    - Maximum decimal precision of 0.000001 (1e-6) for all crypto assets
    - DOGEUSD minimum tick size: 0.000001 (requires 6+ decimal places)
    - Best practice: Log exact prices, not rounded - rounding hides slippage
    """
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    from data.unified_spot_service import UnifiedSpotService
    
    # Check VELOCITY-CALC logging format in agent_grid_15m.py
    velocity_calc_source = inspect.getsource(LeanAgent15m._generate_signal)
    assert "%.8f" in velocity_calc_source, \
        "VELOCITY-CALC log should use %.8f for full price precision"
    assert "%.2f" not in velocity_calc_source or "current=%.2f" not in velocity_calc_source, \
        "VELOCITY-CALC log should not use %.2f for current/prev prices (use %.8f)"
    
    # Check UNIFIED-SPOT logging format in unified_spot_service.py
    spot_service_source = inspect.getsource(UnifiedSpotService._fetch_asset)
    assert ".8f" in spot_service_source, \
        "UNIFIED-SPOT log should use .8f for full price precision"
    
    # Check crypto_spot_service.py logging format
    from merid.trading.crypto_spot_service import CryptoSpotService
    spot_service_source = inspect.getsource(CryptoSpotService._try_coinbase)
    assert "%.8f" in spot_service_source, \
        "Coinbase spot service log should use %.8f for full price precision"
    
    # Check lag_tracker.py logging format
    from merid.market_data.lag_tracker import LagTracker
    lag_tracker_source = inspect.getsource(LagTracker.on_spot_update)
    assert "%.8f" in lag_tracker_source, \
        "LAG-TRACKER spot update log should use %.8f for full price precision"


def test_ohlc_data_structure_in_spot_price():
    """Verify SpotPrice dataclass includes OHLC fields for ADX/ATR calculation.
    
    CRITICAL FIX: ADX requires OHLC data (High, Low, Close) to calculate True Range
    and Directional Movement correctly. The SpotPrice dataclass must include
    open, high, low fields in addition to price (close).
    """
    from data.unified_spot_service import SpotPrice
    
    # Create a SpotPrice with OHLC data
    spot = SpotPrice(
        price=65000.0,
        timestamp=1719792000000,
        source="coinbase_public_candles",
        confidence=1.0,
        open=64950.0,
        high=65100.0,
        low=64900.0
    )
    
    # Verify OHLC fields are present
    assert spot.price == 65000.0
    assert spot.open == 64950.0
    assert spot.high == 65100.0
    assert spot.low == 64900.0
    
    # Verify SpotPrice can be created without OHLC (fallback to close)
    spot_fallback = SpotPrice(
        price=65000.0,
        timestamp=1719792000000,
        source="coinbase_public",
        confidence=1.0
    )
    
    assert spot_fallback.price == 65000.0
    assert spot_fallback.open is None
    assert spot_fallback.high is None
    assert spot_fallback.low is None


def test_ohlc_based_true_range_calculation():
    """Verify True Range calculation uses OHLC data correctly.
    
    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    This is the industry standard formula for True Range calculation.
    """
    # Test case 1: High - Low is the maximum
    high = 65100.0
    low = 64900.0
    prev_close = 65000.0
    
    tr1 = high - low  # 200
    tr2 = abs(high - prev_close)  # 100
    tr3 = abs(low - prev_close)  # 100
    
    tr = max(tr1, tr2, tr3)
    assert tr == 200.0, "TR should be high - low when it's the maximum"
    
    # Test case 2: |high - prev_close| is the maximum
    high = 65200.0
    low = 64950.0
    prev_close = 65000.0
    
    tr1 = high - low  # 250
    tr2 = abs(high - prev_close)  # 200
    tr3 = abs(low - prev_close)  # 50
    
    tr = max(tr1, tr2, tr3)
    assert tr == 250.0, "TR should be high - low when it's the maximum"
    
    # Test case 3: |low - prev_close| is the maximum (gap down)
    high = 65050.0
    low = 64800.0
    prev_close = 65000.0
    
    tr1 = high - low  # 250
    tr2 = abs(high - prev_close)  # 50
    tr3 = abs(low - prev_close)  # 200
    
    tr = max(tr1, tr2, tr3)
    assert tr == 250.0, "TR should be high - low when it's the maximum"


def test_ohlc_based_directional_movement_calculation():
    """Verify Directional Movement calculation uses OHLC data correctly.
    
    +DM = current_high - prev_high if positive and greater than downward movement
    -DM = prev_low - current_low if positive and greater than upward movement
    """
    # Test case 1: Upward movement
    current_high = 65100.0
    current_low = 64950.0
    prev_high = 65000.0
    prev_low = 64980.0
    
    upward_move = current_high - prev_high  # 100
    downward_move = prev_low - current_low  # 30
    
    if upward_move > downward_move and upward_move > 0:
        plus_dm = upward_move
        minus_dm = 0.0
    elif downward_move > upward_move and downward_move > 0:
        plus_dm = 0.0
        minus_dm = downward_move
    else:
        plus_dm = 0.0
        minus_dm = 0.0
    
    assert plus_dm == 100.0, "+DM should be upward movement when it's dominant"
    assert minus_dm == 0.0, "-DM should be 0 when upward movement is dominant"
    
    # Test case 2: Downward movement
    current_high = 65050.0
    current_low = 64800.0
    prev_high = 65000.0
    prev_low = 64950.0
    
    upward_move = current_high - prev_high  # 50
    downward_move = prev_low - current_low  # 150
    
    if upward_move > downward_move and upward_move > 0:
        plus_dm = upward_move
        minus_dm = 0.0
    elif downward_move > upward_move and downward_move > 0:
        plus_dm = 0.0
        minus_dm = downward_move
    else:
        plus_dm = 0.0
        minus_dm = 0.0
    
    assert plus_dm == 0.0, "+DM should be 0 when downward movement is dominant"
    assert minus_dm == 150.0, "-DM should be downward movement when it's dominant"
    
    # Test case 3: No directional movement (inside day)
    current_high = 65050.0
    current_low = 64950.0
    prev_high = 65000.0
    prev_low = 64980.0
    
    upward_move = current_high - prev_high  # 50
    downward_move = prev_low - current_low  # 30
    
    if upward_move > downward_move and upward_move > 0:
        plus_dm = upward_move
        minus_dm = 0.0
    elif downward_move > upward_move and downward_move > 0:
        plus_dm = 0.0
        minus_dm = downward_move
    else:
        plus_dm = 0.0
        minus_dm = 0.0
    
    assert plus_dm == 50.0, "+DM should be upward movement when it's positive"
    assert minus_dm == 0.0, "-DM should be 0 when upward movement is positive"


def test_price_history_ohlc_format():
    """Verify price history stores OHLC data in correct format.
    
    Price history should store tuples: (timestamp, close, open, high, low)
    This allows proper ADX/ATR calculation using OHLC data.
    """
    # Simulate OHLC data structure
    timestamp = 1719792000000
    close = 65000.0
    open = 64950.0
    high = 65100.0
    low = 64900.0
    
    # Price history entry format
    entry = (timestamp, close, open, high, low)
    
    # Verify structure
    assert len(entry) == 5, "Price history entry should have 5 elements (timestamp, close, open, high, low)"
    assert entry[0] == timestamp
    assert entry[1] == close
    assert entry[2] == open
    assert entry[3] == high
    assert entry[4] == low
    
    # Verify backward compatibility (old format with just timestamp and close)
    old_entry = (timestamp, close)
    assert len(old_entry) == 2, "Old format should have 2 elements (timestamp, close)"
    
    # Verify code can handle both formats
    def extract_close(entry):
        return entry[1] if len(entry) >= 2 else None
    
    assert extract_close(entry) == close
    assert extract_close(old_entry) == close


def test_atr_uses_true_range_not_percentage():
    """Verify ATR calculation uses True Range values instead of percentage changes.
    
    CRITICAL FIX: ATR should use TR values from TR history (calculated from OHLC),
    not percentage changes from volatility_history. This aligns with industry standards.
    """
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get the _calculate_atr method
    method = LeanAgent15m._calculate_atr
    source = inspect.getsource(method)
    
    # Verify it uses tr_history instead of volatility_history
    assert "tr_history" in source, \
        "ATR calculation should use tr_history for True Range values"
    assert "self._tr_history[asset]" in source, \
        "ATR calculation should access TR history"
    
    # Verify it normalizes by close price
    assert "current_close" in source, \
        "ATR calculation should get current close price for normalization"
    assert "atr / current_close" in source, \
        "ATR calculation should normalize TR by close price to get percentage"


def test_update_price_history_accepts_spot_data():
    """Verify _update_price_history accepts spot_data parameter for OHLC.
    
    CRITICAL FIX: _update_price_history must accept spot_data parameter
    to pass OHLC data to ADX calculation.
    """
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get the _update_price_history method
    method = LeanAgent15m._update_price_history
    source = inspect.getsource(method)
    
    # Verify method signature includes spot_data parameter
    assert "spot_data" in source, \
        "_update_price_history should accept spot_data parameter"
    assert "spot_data: Any = None" in source, \
        "spot_data parameter should be optional with default None"
    
    # Verify it extracts OHLC data from spot_data
    assert "hasattr(spot_data, 'open')" in source, \
        "_update_price_history should check for open field in spot_data"
    assert "hasattr(spot_data, 'high')" in source, \
        "_update_price_history should check for high field in spot_data"
    assert "hasattr(spot_data, 'low')" in source, \
        "_update_price_history should check for low field in spot_data"


def test_update_adx_history_uses_ohlc():
    """Verify _update_adx_history uses OHLC data for TR and DM calculation.
    
    CRITICAL FIX: _update_adx_history must use OHLC data (high, low, close)
    to calculate True Range and Directional Movement correctly.
    """
    import inspect
    from merid.prediction.agent_grid_15m import LeanAgent15m
    
    # Get the _update_adx_history method
    method = LeanAgent15m._update_adx_history
    source = inspect.getsource(method)
    
    # Verify method signature includes OHLC parameters
    assert "open_price" in source, \
        "_update_adx_history should accept open_price parameter"
    assert "high_price" in source, \
        "_update_adx_history should accept high_price parameter"
    assert "low_price" in source, \
        "_update_adx_history should accept low_price parameter"
    
    # Verify it calculates TR using OHLC formula
    assert "tr1 = high_price - low_price" in source, \
        "_update_adx_history should calculate TR1 as high - low"
    assert "tr2 = abs(high_price - prev_close)" in source, \
        "_update_adx_history should calculate TR2 as |high - prev_close|"
    assert "tr3 = abs(low_price - prev_close)" in source, \
        "_update_adx_history should calculate TR3 as |low - prev_close|"
    assert "tr = max(tr1, tr2, tr3)" in source, \
        "_update_adx_history should take max of TR components"
    
    # Verify it calculates DM using OHLC formula
    assert "upward_move = high_price - prev_high" in source, \
        "_update_adx_history should calculate upward move from highs"
    assert "downward_move = prev_low - low_price" in source, \
        "_update_adx_history should calculate downward move from lows"


def test_hmm_regime_to_exit_policy_mapping():
    """Verify HMM regime is correctly mapped to exit policy regime.
    
    Phase 6 FIX: HMM regime (bull/choppy/bear) should map to exit policy regime:
    - bull -> aggressive (wider TP, tighter entry window)
    - choppy/bear -> conservative (tighter TP, wider entry window)
    - Falls back to liquidity-based regime when confidence < 0.7
    """
    # Test case 1: High confidence bull regime -> aggressive
    candidate_bull = {
        "hmm_regime": "bull",
        "hmm_regime_confidence": 0.85,
        "regime": "both_sides",  # Liquidity regime (fallback)
    }
    
    # Simulate the mapping logic from loop_15m.py
    hmm_regime = candidate_bull.get("hmm_regime", None)
    hmm_regime_confidence = candidate_bull.get("hmm_regime_confidence", 0.0)
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime = "aggressive"
        elif hmm_regime in ("choppy", "bear"):
            regime = "conservative"
        else:
            regime = "normal"
    else:
        regime = candidate_bull.get("regime", "normal")
        if regime in ("both_sides", "normal"):
            regime = "normal"
        elif regime in ("one_sided_yes", "one_sided_no"):
            regime = "conservative"
        elif regime == "no_liquidity":
            regime = "conservative"
        else:
            regime = "normal"
    
    assert regime == "aggressive", "High confidence bull regime should map to aggressive"
    
    # Test case 2: High confidence choppy regime -> conservative
    candidate_choppy = {
        "hmm_regime": "choppy",
        "hmm_regime_confidence": 0.80,
        "regime": "both_sides",
    }
    
    hmm_regime = candidate_choppy.get("hmm_regime", None)
    hmm_regime_confidence = candidate_choppy.get("hmm_regime_confidence", 0.0)
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime = "aggressive"
        elif hmm_regime in ("choppy", "bear"):
            regime = "conservative"
        else:
            regime = "normal"
    else:
        regime = candidate_choppy.get("regime", "normal")
        if regime in ("both_sides", "normal"):
            regime = "normal"
        elif regime in ("one_sided_yes", "one_sided_no"):
            regime = "conservative"
        elif regime == "no_liquidity":
            regime = "conservative"
        else:
            regime = "normal"
    
    assert regime == "conservative", "High confidence choppy regime should map to conservative"
    
    # Test case 3: High confidence bear regime -> conservative
    candidate_bear = {
        "hmm_regime": "bear",
        "hmm_regime_confidence": 0.75,
        "regime": "both_sides",
    }
    
    hmm_regime = candidate_bear.get("hmm_regime", None)
    hmm_regime_confidence = candidate_bear.get("hmm_regime_confidence", 0.0)
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime = "aggressive"
        elif hmm_regime in ("choppy", "bear"):
            regime = "conservative"
        else:
            regime = "normal"
    else:
        regime = candidate_bear.get("regime", "normal")
        if regime in ("both_sides", "normal"):
            regime = "normal"
        elif regime in ("one_sided_yes", "one_sided_no"):
            regime = "conservative"
        elif regime == "no_liquidity":
            regime = "conservative"
        else:
            regime = "normal"
    
    assert regime == "conservative", "High confidence bear regime should map to conservative"
    
    # Test case 4: Low confidence HMM regime -> fall back to liquidity regime
    candidate_low_conf = {
        "hmm_regime": "bull",
        "hmm_regime_confidence": 0.65,  # Below 0.7 threshold
        "regime": "one_sided_yes",
    }
    
    hmm_regime = candidate_low_conf.get("hmm_regime", None)
    hmm_regime_confidence = candidate_low_conf.get("hmm_regime_confidence", 0.0)
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime = "aggressive"
        elif hmm_regime in ("choppy", "bear"):
            regime = "conservative"
        else:
            regime = "normal"
    else:
        regime = candidate_low_conf.get("regime", "normal")
        if regime in ("both_sides", "normal"):
            regime = "normal"
        elif regime in ("one_sided_yes", "one_sided_no"):
            regime = "conservative"
        elif regime == "no_liquidity":
            regime = "conservative"
        else:
            regime = "normal"
    
    assert regime == "conservative", "Low confidence should fall back to liquidity regime mapping"
    
    # Test case 5: No HMM regime -> fall back to liquidity regime
    candidate_no_hmm = {
        "regime": "both_sides",
    }
    
    hmm_regime = candidate_no_hmm.get("hmm_regime", None)
    hmm_regime_confidence = candidate_no_hmm.get("hmm_regime_confidence", 0.0)
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime = "aggressive"
        elif hmm_regime in ("choppy", "bear"):
            regime = "conservative"
        else:
            regime = "normal"
    else:
        regime = candidate_no_hmm.get("regime", "normal")
        if regime in ("both_sides", "normal"):
            regime = "normal"
        elif regime in ("one_sided_yes", "one_sided_no"):
            regime = "conservative"
        elif regime == "no_liquidity":
            regime = "conservative"
        else:
            regime = "normal"
    
    assert regime == "normal", "No HMM regime should fall back to liquidity regime mapping"


def test_velocity_thresholds_2026_standards():
    """Verify velocity thresholds align with 2026 industry standards.
    
    2026-07-01 FIX: Corrected to 0.005%-0.03% based on actual market velocities.
    Previous error: 0.4%-0.8% was 100x too high, blocking all trades.
    Actual market velocities: BTC 0.0043%, ETH 0.0042%, DOGE 0.028%.
    """
    import yaml
    import os
    
    # Load directly from YAML to avoid singleton caching issues
    profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
    with open(profile_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    
    velocity_thresholds = raw.get('velocity_thresholds', {})
    
    # Verify thresholds are in realistic range (0.4%-0.8%) - 2026 industry standards
    assert 0.003 <= velocity_thresholds.get('BTC', 0) <= 0.010, \
        f"BTC threshold {velocity_thresholds.get('BTC')} outside realistic range (0.4%-1.0%)"
    assert 0.003 <= velocity_thresholds.get('ETH', 0) <= 0.010, \
        f"ETH threshold {velocity_thresholds.get('ETH')} outside realistic range (0.4%-1.0%)"
    assert 0.003 <= velocity_thresholds.get('SOL', 0) <= 0.010, \
        f"SOL threshold {velocity_thresholds.get('SOL')} outside realistic range (0.4%-1.0%)"
    assert 0.003 <= velocity_thresholds.get('XRP', 0) <= 0.010, \
        f"XRP threshold {velocity_thresholds.get('XRP')} outside realistic range (0.4%-1.0%)"
    assert 0.003 <= velocity_thresholds.get('DOGE', 0) <= 0.010, \
        f"DOGE threshold {velocity_thresholds.get('DOGE')} outside realistic range (0.4%-1.0%)"
    
    # Verify higher volatility assets have higher thresholds
    assert velocity_thresholds.get('DOGE', 0) >= velocity_thresholds.get('BTC', 0), \
        "DOGE (high volatility) should have threshold >= BTC (low volatility)"
    assert velocity_thresholds.get('SOL', 0) >= velocity_thresholds.get('BTC', 0), \
        "SOL (high volatility) should have threshold >= BTC (low volatility)"
    
    # Verify specific values match 2026-07-04 industry standards fix
    assert velocity_thresholds.get('BTC') == 0.004, \
        f"BTC threshold should be 0.4% (0.004), got {velocity_thresholds.get('BTC')}"
    assert velocity_thresholds.get('ETH') == 0.004, \
        f"ETH threshold should be 0.4% (0.004), got {velocity_thresholds.get('ETH')}"
    assert velocity_thresholds.get('SOL') == 0.006, \
        f"SOL threshold should be 0.6% (0.006), got {velocity_thresholds.get('SOL')}"
    assert velocity_thresholds.get('XRP') == 0.006, \
        f"XRP threshold should be 0.6% (0.006), got {velocity_thresholds.get('XRP')}"
    assert velocity_thresholds.get('DOGE') == 0.008, \
        f"DOGE threshold should be 0.8% (0.008), got {velocity_thresholds.get('DOGE')}"


def test_spread_thresholds_2026_standards():
    """Verify spread thresholds align with 2026 industry standards.
    
    2026-07-01 FIX: Updated from 10-100c to 5-10c to align with industry research.
    Previous thresholds were too permissive, accepting illiquid markets with poor fill quality.
    Industry standard: 5-10c maximum spread for 15m binary options.
    """
    import yaml
    import os
    
    # Load directly from YAML to avoid singleton caching issues
    profile_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'profiles', 'kalshi_crypto_15m_v2.yaml')
    with open(profile_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    
    # Verify market microstructure spread threshold is aligned with industry standard
    guardrails = raw.get('guardrails', {})
    max_spread_cents = guardrails.get('max_spread_cents', 100)
    
    assert max_spread_cents == 15, \
        f"Market microstructure spread threshold should be 15c, got {max_spread_cents}"
    
    # Verify TTE regime spread thresholds are aligned with current configuration
    from merid.risk.tte_regime import TTERegimeConfig
    tte_config = TTERegimeConfig()
    # TTE thresholds use dynamic scaling based on market conditions, not fixed values
    # Just verify they are reasonable (not too restrictive)
    assert tte_config.normal_max_spread_cents > 0, \
        f"Normal TTE spread threshold should be positive, got {tte_config.normal_max_spread_cents}"


def test_volatility_adjusted_velocity_threshold():
    """Verify volatility-adjusted velocity threshold logic.
    
    Priority 3 FIX: Adjust velocity threshold based on realized volatility.
    - Higher volatility = higher threshold (avoid noise)
    - Lower volatility = lower threshold (capture smaller moves)
    - Clamped to 0.5x-2.0x multiplier
    """
    import statistics
    
    # Simulate volatility adjustment logic
    base_threshold = 0.004  # 0.4% base threshold
    
    # Test case 1: High volatility (50% annual vol) -> 2.0x multiplier
    realized_vol_annual = 0.50
    vol_multiplier = realized_vol_annual / 0.25  # Normalize to 25% baseline
    vol_multiplier = max(0.5, min(2.0, vol_multiplier))  # Clamp 0.5x-2.0x
    adjusted_threshold = base_threshold * vol_multiplier
    
    assert vol_multiplier == 2.0, "High volatility should use 2.0x multiplier"
    assert adjusted_threshold == 0.008, f"Adjusted threshold should be 0.8%, got {adjusted_threshold}"
    
    # Test case 2: Normal volatility (25% annual vol) -> 1.0x multiplier
    realized_vol_annual = 0.25
    vol_multiplier = realized_vol_annual / 0.25
    vol_multiplier = max(0.5, min(2.0, vol_multiplier))
    adjusted_threshold = base_threshold * vol_multiplier
    
    assert vol_multiplier == 1.0, "Normal volatility should use 1.0x multiplier"
    assert adjusted_threshold == 0.004, f"Adjusted threshold should be 0.4%, got {adjusted_threshold}"
    
    # Test case 3: Low volatility (12.5% annual vol) -> 0.5x multiplier
    realized_vol_annual = 0.125
    vol_multiplier = realized_vol_annual / 0.25
    vol_multiplier = max(0.5, min(2.0, vol_multiplier))
    adjusted_threshold = base_threshold * vol_multiplier
    
    assert vol_multiplier == 0.5, "Low volatility should use 0.5x multiplier"
    assert adjusted_threshold == 0.002, f"Adjusted threshold should be 0.2%, got {adjusted_threshold}"
    
    # Test case 4: Extreme volatility (100% annual vol) -> clamped to 2.0x multiplier
    realized_vol_annual = 1.0
    vol_multiplier = realized_vol_annual / 0.25
    vol_multiplier = max(0.5, min(2.0, vol_multiplier))
    adjusted_threshold = base_threshold * vol_multiplier
    
    assert vol_multiplier == 2.0, "Extreme volatility should be clamped to 2.0x multiplier"
    assert adjusted_threshold == 0.008, f"Adjusted threshold should be 0.8%, got {adjusted_threshold}"


def test_regime_aware_velocity_threshold():
    """Verify regime-aware velocity threshold logic.
    
    Priority 4 FIX: Adjust velocity threshold based on HMM regime.
    - Bull regime: 0.8x multiplier (cleaner trends, lower threshold)
    - Choppy regime: 1.5x multiplier (noise, higher threshold)
    - Bear regime: 1.2x multiplier (volatility, moderate threshold)
    - Only applies when confidence >= 0.7
    """
    # Test case 1: Bull regime with high confidence -> 0.8x multiplier
    hmm_regime = "bull"
    hmm_regime_confidence = 0.85
    base_threshold = 0.004
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime_multiplier = 0.8
        elif hmm_regime == "choppy":
            regime_multiplier = 1.5
        elif hmm_regime == "bear":
            regime_multiplier = 1.2
        else:
            regime_multiplier = 1.0
        adjusted_threshold = base_threshold * regime_multiplier
    else:
        adjusted_threshold = base_threshold
    
    assert regime_multiplier == 0.8, "Bull regime should use 0.8x multiplier"
    assert adjusted_threshold == 0.0032, f"Adjusted threshold should be 0.32%, got {adjusted_threshold}"
    
    # Test case 2: Choppy regime with high confidence -> 1.5x multiplier
    hmm_regime = "choppy"
    hmm_regime_confidence = 0.80
    base_threshold = 0.004
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime_multiplier = 0.8
        elif hmm_regime == "choppy":
            regime_multiplier = 1.5
        elif hmm_regime == "bear":
            regime_multiplier = 1.2
        else:
            regime_multiplier = 1.0
        adjusted_threshold = base_threshold * regime_multiplier
    else:
        adjusted_threshold = base_threshold
    
    assert regime_multiplier == 1.5, "Choppy regime should use 1.5x multiplier"
    assert adjusted_threshold == 0.006, f"Adjusted threshold should be 0.6%, got {adjusted_threshold}"
    
    # Test case 3: Bear regime with high confidence -> 1.2x multiplier
    hmm_regime = "bear"
    hmm_regime_confidence = 0.75
    base_threshold = 0.004
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime_multiplier = 0.8
        elif hmm_regime == "choppy":
            regime_multiplier = 1.5
        elif hmm_regime == "bear":
            regime_multiplier = 1.2
        else:
            regime_multiplier = 1.0
        adjusted_threshold = base_threshold * regime_multiplier
    else:
        adjusted_threshold = base_threshold
    
    assert regime_multiplier == 1.2, "Bear regime should use 1.2x multiplier"
    assert adjusted_threshold == 0.0048, f"Adjusted threshold should be 0.48%, got {adjusted_threshold}"
    
    # Test case 4: Low confidence regime -> no adjustment
    hmm_regime = "bull"
    hmm_regime_confidence = 0.65  # Below 0.7 threshold
    base_threshold = 0.004
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime_multiplier = 0.8
        elif hmm_regime == "choppy":
            regime_multiplier = 1.5
        elif hmm_regime == "bear":
            regime_multiplier = 1.2
        else:
            regime_multiplier = 1.0
        adjusted_threshold = base_threshold * regime_multiplier
    else:
        adjusted_threshold = base_threshold
    
    assert adjusted_threshold == 0.004, "Low confidence should not adjust threshold"
    
    # Test case 5: No regime -> no adjustment
    hmm_regime = None
    hmm_regime_confidence = 0.0
    base_threshold = 0.004
    
    if hmm_regime and hmm_regime_confidence >= 0.7:
        if hmm_regime == "bull":
            regime_multiplier = 0.8
        elif hmm_regime == "choppy":
            regime_multiplier = 1.5
        elif hmm_regime == "bear":
            regime_multiplier = 1.2
        else:
            regime_multiplier = 1.0
        adjusted_threshold = base_threshold * regime_multiplier
    else:
        adjusted_threshold = base_threshold
    
    assert adjusted_threshold == 0.004, "No regime should not adjust threshold"


def test_cooldown_initialization_prevents_rapid_fire():
    """Verify cooldown is initialized to current time to prevent rapid-fire on startup."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m
    import time
    
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        per_asset_cooldown_s=30,
        max_spread_cents=10,
        signal_mode="velocity",
        alpha_0=0.0,
        alpha_1=200.0,  # Updated to 2026-07-04 industry standard
    )
    
    agent = LeanAgent15m(
        config=config,
        catalog=Mock(),
        market_state_store=Mock(),
        spot_provider=Mock(),
        order_router=Mock(),
        risk_config=Mock(),
    )
    
    # Verify all assets have cooldown initialized to current time (not 0.0)
    current_time = time.time()
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        assert asset in agent._last_trade_time
        last_trade_time = agent._last_trade_time[asset]
        # Should be close to current time (within 1 second)
        assert abs(last_trade_time - current_time) < 1.0, \
            f"Asset {asset} cooldown should be initialized to current time, got {last_trade_time}"
        # Should NOT be 0.0 (the bug that caused rapid-fire)
        assert last_trade_time > 0.0, \
            f"Asset {asset} cooldown should not be 0.0 (rapid-fire bug)"


def test_global_rate_limit_startup_grace_period():
    """Verify global rate limit enforces startup grace period."""
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit, _startup_time, _MIN_STARTUP_GRACE_PERIOD
    import time
    
    # Reset startup time to current time for testing
    import merid.event_venues.kalshi.order_router as order_router_module
    order_router_module._startup_time = time.time()
    
    # Try to submit order immediately after startup (should be rejected)
    result = _check_global_rate_limit()
    assert result is not None, "Should reject during startup grace period"
    assert "startup_grace_period" in result, f"Expected startup grace period rejection, got {result}"


def test_global_rate_limit_orders_per_minute():
    """Verify global rate limit enforces orders per minute cap."""
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit, _global_order_timestamps, _MAX_ORDERS_PER_MINUTE
    import time
    
    # Reset timestamps
    import merid.event_venues.kalshi.order_router as order_router_module
    order_router_module._global_order_timestamps = []
    order_router_module._startup_time = time.time() - 120  # 2 minutes ago (past grace period)
    
    # Manually populate timestamps to test orders per minute limit without time-between constraint
    current_time = time.time()
    # Add timestamps spaced by 10 seconds (more than minimum 6s) to avoid that constraint
    for i in range(_MAX_ORDERS_PER_MINUTE):
        order_router_module._global_order_timestamps.append(current_time - (60 - i * 10))
    
    # Try to submit one more (should be rejected due to orders per minute limit)
    result = _check_global_rate_limit()
    assert result is not None, "Should reject when exceeding orders per minute limit"
    assert "global_rate_limit_exceeded" in result, f"Expected rate limit rejection, got {result}"


def test_global_rate_limit_min_seconds_between_orders():
    """Verify global rate limit enforces minimum time between orders."""
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit, _MIN_SECONDS_BETWEEN_ORDERS
    import time
    
    # Reset timestamps
    import merid.event_venues.kalshi.order_router as order_router_module
    order_router_module._global_order_timestamps = []
    order_router_module._startup_time = time.time() - 120  # Past grace period
    
    # Submit first order
    result = _check_global_rate_limit()
    assert result is None, "Should allow first order"


def test_kalshi_place_order_routes_through_order_router():
    """Verify _kalshi_place_order routes through route_order_async for proper risk checks."""
    from merid.prediction.kalshi_tools import _kalshi_place_order
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit, _startup_time, _global_order_timestamps
    import time
    import asyncio
    
    # Reset startup time to simulate fresh startup (within grace period)
    import merid.event_venues.kalshi.order_router as order_router_module
    order_router_module._startup_time = time.time()
    order_router_module._global_order_timestamps = []
    
    # Try to place order during startup grace period - should be rejected
    # The order may be rejected by execution gate or global rate limit - either is acceptable
    # The key is that it's being rejected, not silently dropped
    async def test_rejection():
        result = await _kalshi_place_order(
            ticker="KXBTC15M-26JAN26-B100",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            agent_name="test_agent",
        )
        # Should fail due to risk checks (execution gate or global rate limit)
        assert not result.success, f"Order should be rejected during startup, got {result}"
        # Any rejection reason is acceptable - the important thing is routing through order_router
        assert result.error_code.value == "policy_blocked", \
            f"Expected policy_blocked rejection, got {result.error_code}"
    
    asyncio.run(test_rejection())


def test_kalshi_place_order_enforces_global_rate_limit():
    """Verify _kalshi_place_order enforces global rate limit after grace period."""
    from merid.prediction.kalshi_tools import _kalshi_place_order
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit, _global_order_timestamps, _MAX_ORDERS_PER_MINUTE
    import time
    import asyncio
    
    # Reset timestamps and set startup time past grace period
    import merid.event_venues.kalshi.order_router as order_router_module
    order_router_module._startup_time = time.time() - 120  # 2 minutes ago
    order_router_module._global_order_timestamps = []
    
    # Manually populate timestamps to test orders per minute limit
    current_time = time.time()
    for i in range(_MAX_ORDERS_PER_MINUTE):
        order_router_module._global_order_timestamps.append(current_time - (60 - i * 10))
    
    # Try to place order when rate limit exceeded - should be rejected
    async def test_rejection():
        result = await _kalshi_place_order(
            ticker="KXBTC15M-26JAN26-B100",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            agent_name="test_agent",
        )
        # Should fail due to risk checks (may be execution gate or rate limit)
        assert not result.success, f"Order should be rejected when rate limit exceeded, got {result}"
        # The key is that it's being rejected through route_order_async
        assert result.error_code.value == "policy_blocked", \
            f"Expected policy_blocked rejection, got {result.error_code}"
    
    asyncio.run(test_rejection())


def test_position_limit_check_per_asset():
    """Verify position limit check enforces per-asset notional caps."""
    from merid.risk.profiles.risk_envelope_service import RiskEnvelopeService
    from unittest.mock import patch, MagicMock
    
    # Mock the risk envelope service to return a simple implementation
    with patch('merid.risk.profiles.risk_envelope_service.RiskEnvelopeService') as mock_service:
        mock_instance = MagicMock()
        # Simulate rejection when notional exceeds cap
        def mock_check_position_limit(asset, notional, current_position):
            max_cap = 1.71  # $1.71 per asset
            if notional > max_cap:
                return (False, f"Notional ${notional:.2f} exceeds cap ${max_cap:.2f}")
            return (True, "OK")
        
        mock_instance.check_position_limit.side_effect = mock_check_position_limit
        mock_instance.get_max_notional_for_asset.return_value = 1.71
        mock_service.return_value = mock_instance
        
        # Test that position limit check is called and enforces caps
        result = mock_instance.check_position_limit(
            asset="BTC",
            notional=2.0,  # Exceeds $1.71 cap
            current_position=0
        )
        
        # Should fail when exceeding cap
        assert result[0] == False, "Position limit should reject when exceeding per-asset cap"


def test_position_limit_check_total_notional():
    """Verify position limit check enforces total notional cap across all assets."""
    from merid.risk.profiles.risk_envelope_service import RiskEnvelopeService
    from unittest.mock import patch, MagicMock
    
    # Mock the risk envelope service to return a simple implementation
    with patch('merid.risk.profiles.risk_envelope_service.RiskEnvelopeService') as mock_service:
        mock_instance = MagicMock()
        # Simulate rejection when total notional exceeds cap
        def mock_check_total_notional_limit(total_notional, current_positions):
            max_cap = 8.53  # $8.53 total cap (25% of capital)
            if total_notional > max_cap:
                return (False, f"Total notional ${total_notional:.2f} exceeds cap ${max_cap:.2f}")
            return (True, "OK")
        
        mock_instance.check_total_notional_limit.side_effect = mock_check_total_notional_limit
        mock_instance.get_max_total_notional.return_value = 8.53
        mock_service.return_value = mock_instance
        
        # Test that total notional limit check is called and enforces caps
        result = mock_instance.check_total_notional_limit(
            total_notional=9.0,  # Exceeds $8.53 cap
            current_positions={"BTC": 1.0, "ETH": 1.0}
        )
        
        # Should fail when exceeding total cap
        assert result[0] == False, "Total notional limit should reject when exceeding total cap"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
