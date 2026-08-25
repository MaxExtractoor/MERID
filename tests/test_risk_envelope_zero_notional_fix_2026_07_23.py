"""
Test for zero notional handling in risk envelope (2026-07-23)

This test verifies that record_order_execution handles zero notional
(zero-fill orders) gracefully without raising assertion errors.
"""

import pytest
import time
from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    KalshiCrypto15mRiskEnvelope,
    get_kalshi_crypto_15m_risk_envelope,
    _reset_shared_window_state_for_testing
)


def test_record_order_execution_zero_notional():
    """
    Test that record_order_execution handles zero notional gracefully.
    
    Zero-fill orders (filled=0) should not trigger assertion errors.
    The function should log an INFO message and return early.
    """
    # Reset shared state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create a risk envelope
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=100.0,
        profile_capital_usd=100.0,
        max_single_order_notional_usd=1.0,
        max_total_notional_usd=1.0,
        asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
        asset_depth_thresholds={
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 30, "min_depth_no": 30},
            "XRP": {"min_depth_yes": 30, "min_depth_no": 30},
            "DOGE": {"min_depth_yes": 30, "min_depth_no": 30},
        },
        agent_max_notional_usd=1.0,
        agent_max_orders_per_window=10,
        agent_max_yes_position=1,
        agent_max_no_position=1,
        max_cycle_risk_pct=0.0,
        daily_loss_enabled=False,
        max_daily_loss_usd=10.0,
        drawdown_halt_pct=0.20,
        drawdown_unwind_pct=0.25,
        peak_equity_usd=100.0,
        current_equity_usd=100.0,
        current_drawdown_pct=0.0,
        kelly_fraction=0.5,
        adaptive_risk_bands=[],
        per_trade_risk_multiplier=1.0,
        is_halted=False,
        current_risk_band=None,
        resume_if_drawdown_improves=False,
        correlation_tracking_enabled=False,
        correlation_threshold=0.8,
        correlation_multiplier=1.0,
        window_start_ts=int(time.time() // 900) * 900,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0.0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0.0,
    )
    
    # Test zero notional - should not raise assertion error
    envelope.record_order_execution(
        agent_id="BTC_15M",
        order_notional_usd=0.0,  # Zero notional (zero-fill order)
        asset="BTC"
    )
    
    # Verify total exposure is still zero (not incremented)
    assert envelope.total_window_exposure_usd == 0.0
    assert envelope.agent_window_exposure_usd.get("BTC_15M", 0.0) == 0.0


def test_record_order_execution_negative_notional():
    """
    Test that record_order_execution handles negative notional gracefully.
    
    Negative notional should also be handled gracefully (though it shouldn't
    occur in normal operation).
    """
    # Reset shared state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create a risk envelope
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=100.0,
        profile_capital_usd=100.0,
        max_single_order_notional_usd=1.0,
        max_total_notional_usd=1.0,
        asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
        asset_depth_thresholds={
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 30, "min_depth_no": 30},
            "XRP": {"min_depth_yes": 30, "min_depth_no": 30},
            "DOGE": {"min_depth_yes": 30, "min_depth_no": 30},
        },
        agent_max_notional_usd=1.0,
        agent_max_orders_per_window=10,
        agent_max_yes_position=1,
        agent_max_no_position=1,
        max_cycle_risk_pct=0.0,
        daily_loss_enabled=False,
        max_daily_loss_usd=10.0,
        drawdown_halt_pct=0.20,
        drawdown_unwind_pct=0.25,
        peak_equity_usd=100.0,
        current_equity_usd=100.0,
        current_drawdown_pct=0.0,
        kelly_fraction=0.5,
        adaptive_risk_bands=[],
        per_trade_risk_multiplier=1.0,
        is_halted=False,
        current_risk_band=None,
        resume_if_drawdown_improves=False,
        correlation_tracking_enabled=False,
        correlation_threshold=0.8,
        correlation_multiplier=1.0,
        window_start_ts=int(time.time() // 900) * 900,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0.0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0.0,
    )
    
    # Test negative notional - should not raise assertion error
    envelope.record_order_execution(
        agent_id="ETH_15M",
        order_notional_usd=-0.01,  # Negative notional (shouldn't happen but handle gracefully)
        asset="ETH"
    )
    
    # Verify total exposure is still zero (not incremented)
    assert envelope.total_window_exposure_usd == 0.0
    assert envelope.agent_window_exposure_usd.get("ETH_15M", 0.0) == 0.0


def test_record_order_execution_positive_notional():
    """
    Test that record_order_execution still works correctly for positive notional.
    
    This ensures the fix doesn't break the normal case where orders have
    positive notional.
    """
    # Reset shared state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create a risk envelope
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=100.0,
        profile_capital_usd=100.0,
        max_single_order_notional_usd=1.0,
        max_total_notional_usd=1.0,
        asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
        asset_depth_thresholds={
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 30, "min_depth_no": 30},
            "XRP": {"min_depth_yes": 30, "min_depth_no": 30},
            "DOGE": {"min_depth_yes": 30, "min_depth_no": 30},
        },
        agent_max_notional_usd=1.0,
        agent_max_orders_per_window=10,
        agent_max_yes_position=1,
        agent_max_no_position=1,
        max_cycle_risk_pct=0.0,
        daily_loss_enabled=False,
        max_daily_loss_usd=10.0,
        drawdown_halt_pct=0.20,
        drawdown_unwind_pct=0.25,
        peak_equity_usd=100.0,
        current_equity_usd=100.0,
        current_drawdown_pct=0.0,
        kelly_fraction=0.5,
        adaptive_risk_bands=[],
        per_trade_risk_multiplier=1.0,
        is_halted=False,
        current_risk_band=None,
        resume_if_drawdown_improves=False,
        correlation_tracking_enabled=False,
        correlation_threshold=0.8,
        correlation_multiplier=1.0,
        window_start_ts=int(time.time() // 900) * 900,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0.0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0.0,
    )
    
    # Test positive notional - should increment exposure
    envelope.record_order_execution(
        agent_id="SOL_15M",
        order_notional_usd=0.42,  # Positive notional (normal case)
        asset="SOL"
    )
    
    # Verify total exposure was incremented
    assert envelope.total_window_exposure_usd == 0.42
    assert envelope.agent_window_exposure_usd.get("SOL_15M", 0.0) == 0.42


def test_record_order_execution_mixed_zero_and_positive():
    """
    Test that record_order_execution handles a mix of zero and positive notional.
    
    This simulates a realistic scenario where some orders fill (positive notional)
    and some don't (zero notional).
    """
    # Reset shared state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create a risk envelope
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=100.0,
        profile_capital_usd=100.0,
        max_single_order_notional_usd=1.0,
        max_total_notional_usd=1.0,
        asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
        asset_depth_thresholds={
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 30, "min_depth_no": 30},
            "XRP": {"min_depth_yes": 30, "min_depth_no": 30},
            "DOGE": {"min_depth_yes": 30, "min_depth_no": 30},
        },
        agent_max_notional_usd=1.0,
        agent_max_orders_per_window=10,
        agent_max_yes_position=1,
        agent_max_no_position=1,
        max_cycle_risk_pct=0.0,
        daily_loss_enabled=False,
        max_daily_loss_usd=10.0,
        drawdown_halt_pct=0.20,
        drawdown_unwind_pct=0.25,
        peak_equity_usd=100.0,
        current_equity_usd=100.0,
        current_drawdown_pct=0.0,
        kelly_fraction=0.5,
        adaptive_risk_bands=[],
        per_trade_risk_multiplier=1.0,
        is_halted=False,
        current_risk_band=None,
        resume_if_drawdown_improves=False,
        correlation_tracking_enabled=False,
        correlation_threshold=0.8,
        correlation_multiplier=1.0,
        window_start_ts=int(time.time() // 900) * 900,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0.0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0.0,
    )
    
    # Record a zero-fill order
    envelope.record_order_execution(
        agent_id="BTC_15M",
        order_notional_usd=0.0,
        asset="BTC"
    )
    
    # Record a filled order
    envelope.record_order_execution(
        agent_id="ETH_15M",
        order_notional_usd=0.61,
        asset="ETH"
    )
    
    # Record another zero-fill order
    envelope.record_order_execution(
        agent_id="SOL_15M",
        order_notional_usd=0.0,
        asset="SOL"
    )
    
    # Verify only the filled order contributed to exposure
    assert envelope.total_window_exposure_usd == 0.61
    assert envelope.agent_window_exposure_usd.get("BTC_15M", 0.0) == 0.0
    assert envelope.agent_window_exposure_usd.get("ETH_15M", 0.0) == 0.61
    assert envelope.agent_window_exposure_usd.get("SOL_15M", 0.0) == 0.0


def test_check_window_limit_zero_notional():
    """
    Test that check_window_limit handles zero notional gracefully.
    
    Zero notional orders should pass the window limit check without assertion errors.
    """
    # Reset shared state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create a risk envelope
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=100.0,
        profile_capital_usd=100.0,
        max_single_order_notional_usd=1.0,
        max_total_notional_usd=1.0,
        asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
        asset_depth_thresholds={
            "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
            "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
            "SOL": {"min_depth_yes": 30, "min_depth_no": 30},
            "XRP": {"min_depth_yes": 30, "min_depth_no": 30},
            "DOGE": {"min_depth_yes": 30, "min_depth_no": 30},
        },
        agent_max_notional_usd=1.0,
        agent_max_orders_per_window=10,
        agent_max_yes_position=1,
        agent_max_no_position=1,
        max_cycle_risk_pct=0.0,
        daily_loss_enabled=False,
        max_daily_loss_usd=10.0,
        drawdown_halt_pct=0.20,
        drawdown_unwind_pct=0.25,
        peak_equity_usd=100.0,
        current_equity_usd=100.0,
        current_drawdown_pct=0.0,
        kelly_fraction=0.5,
        adaptive_risk_bands=[],
        per_trade_risk_multiplier=1.0,
        is_halted=False,
        current_risk_band=None,
        resume_if_drawdown_improves=False,
        correlation_tracking_enabled=False,
        correlation_threshold=0.8,
        correlation_multiplier=1.0,
        window_start_ts=int(time.time() // 900) * 900,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0.0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0.0,
    )
    
    # Test zero notional - should not raise assertion error
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=0.0,  # Zero notional (zero-fill order)
        current_ts=time.time(),
        asset="BTC"
    )
    
    # Should be allowed (zero notional doesn't add exposure)
    assert allowed, f"Zero notional order should be allowed, but got reason: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
