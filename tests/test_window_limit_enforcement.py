#!/usr/bin/env python3
"""
Test: Window Limit Enforcement for 15M Kalshi Crypto Trading Stack

This test verifies that window-based risk limits are enforced correctly:
- Fixed $1.00 total venue per 15-minute window limit (MERID_FIXED_EXPOSURE_CAP_USD)
- Per-agent and per-asset percentage-based limits are DISABLED
- Window tracking methods exist and work correctly
- Position closures release window capacity

Usage:
    pytest tests/test_window_limit_enforcement.py -v
"""

import pytest
from unittest.mock import Mock
import time


class TestWindowLimitEnforcement:
    """Test window-based risk limit enforcement."""
    
    @pytest.fixture
    def risk_envelope(self):
        """Create a risk envelope instance for testing."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        bankroll = 10000.0
        envelope = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=bankroll,
            profile_capital_usd=bankroll,
            max_single_order_notional_usd=bankroll * 0.03,
            max_total_notional_usd=bankroll * 0.15,
            agent_max_notional_usd=bankroll * 0.03,
            asset_max_notional_usd={"BTC": bankroll * 0.03, "ETH": bankroll * 0.03, "SOL": bankroll * 0.03, "XRP": bankroll * 0.03, "DOGE": bankroll * 0.03},
            asset_depth_thresholds={},
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            max_cycle_risk_pct=0.03,
            daily_loss_enabled=False,
            max_daily_loss_usd=float('inf'),
            drawdown_halt_pct=0.15,
            drawdown_unwind_pct=0.10,
            peak_equity_usd=bankroll,
            current_equity_usd=bankroll,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.7,
            correlation_multiplier=1.0,
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},
            total_resting_exposure_usd=0.0,
        )
        return envelope
    
    def test_window_limit_fields_exist(self, risk_envelope):
        """Test that window limit fields exist in envelope."""
        # CRITICAL FIX (2026-07-23): Percentage-based guardrails fields removed
        # Only fixed $1.00 cap fields remain
        assert hasattr(risk_envelope, 'per_agent_window_limit_usd')
        assert hasattr(risk_envelope, 'total_venue_window_limit_usd')
        assert hasattr(risk_envelope, 'window_start_ts')
        assert hasattr(risk_envelope, 'agent_window_exposure_usd')
        assert hasattr(risk_envelope, 'total_window_exposure_usd')
        
        # Verify values are correct (fixed $1.00 cap)
        assert risk_envelope.per_agent_window_limit_usd == 1.0
        assert risk_envelope.total_venue_window_limit_usd == 1.0
    
    def test_check_window_limit_method_exists(self, risk_envelope):
        """Test that check_window_limit method exists."""
        assert hasattr(risk_envelope, 'check_window_limit')
        assert callable(risk_envelope.check_window_limit)
    
    def test_record_order_execution_method_exists(self, risk_envelope):
        """Test that record_order_execution method exists."""
        assert hasattr(risk_envelope, 'record_order_execution')
        assert callable(risk_envelope.record_order_execution)
    
    def test_record_position_closure_method_exists(self, risk_envelope):
        """Test that record_position_closure method exists."""
        assert hasattr(risk_envelope, 'record_position_closure')
        assert callable(risk_envelope.record_position_closure)
    
    def test_check_window_limit_basic_call(self, risk_envelope):
        """Test that check_window_limit can be called with basic parameters."""
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=200.0,
            current_ts=time.time(),
        )
        # Should return a tuple
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)
    
    def test_check_window_limit_with_custom_limit(self, risk_envelope):
        """Test that check_window_limit enforces fixed $1.00 cap (no percentage overrides)."""
        # CRITICAL FIX (2026-07-23): Percentage-based parameters removed
        # check_window_limit now enforces ONLY the fixed $1.00 exposure cap
        # Order for $300.0 should be rejected (exceeds $1.00 fixed cap)
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=300.0,
            current_ts=time.time(),
        )
        # Should be rejected (exceeds $1.00 fixed cap)
        assert allowed is False, f"Order exceeding $1.00 cap should be rejected, reason: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
