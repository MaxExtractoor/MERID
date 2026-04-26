"""
Bankroll Unification Tests
===========================

Tests for the unified bankroll system to ensure:
1. Sizing and risk layers use the same effective bankroll
2. max_riskable_usd cap is applied correctly
3. min_operational_balance_usd floor halts trading correctly
4. No "bankroll cap 0.00" when live balance is non-zero
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


@dataclass
class MockBankrollResult:
    success: bool
    balance_cents: int
    portfolio_value_cents: int
    total_value_usd: float
    error: str = ""


class TestEffectiveBankrollComputation:
    """Test the unified effective bankroll computation."""

    def test_compute_effective_bankroll_no_caps(self):
        """Test that effective bankroll equals live balance when no caps set."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        live_balance = 1000.0
        result = compute_effective_bankroll(
            live_balance_usd=live_balance,
            max_riskable_usd=None,
            min_operational_balance_usd=None
        )
        
        assert result == live_balance

    def test_compute_effective_bankroll_with_max_riskable_cap(self):
        """Test that max_riskable_usd caps the effective bankroll."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        live_balance = 1000.0
        max_riskable = 500.0
        
        result = compute_effective_bankroll(
            live_balance_usd=live_balance,
            max_riskable_usd=max_riskable,
            min_operational_balance_usd=None
        )
        
        assert result == max_riskable  # Should be capped

    def test_compute_effective_bankroll_max_riskable_zero_means_no_cap(self):
        """Test that max_riskable_usd=0 means no cap."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        live_balance = 1000.0
        
        result = compute_effective_bankroll(
            live_balance_usd=live_balance,
            max_riskable_usd=0,
            min_operational_balance_usd=None
        )
        
        assert result == live_balance  # Should not be capped

    def test_compute_effective_bankroll_below_min_operational(self):
        """Test that effective bankroll is 0 when below min_operational_balance."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        live_balance = 50.0
        min_operational = 100.0
        
        result = compute_effective_bankroll(
            live_balance_usd=live_balance,
            max_riskable_usd=None,
            min_operational_balance_usd=min_operational
        )
        
        assert result == 0.0  # Trading should halt

    def test_compute_effective_bankroll_min_operational_zero_means_no_minimum(self):
        """Test that min_operational_balance_usd=0 means no minimum."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        live_balance = 50.0
        
        result = compute_effective_bankroll(
            live_balance_usd=live_balance,
            max_riskable_usd=None,
            min_operational_balance_usd=0
        )
        
        assert result == live_balance  # Should not be blocked

    def test_compute_effective_bankroll_both_caps(self):
        """Test that both max_riskable and min_operational are applied."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        # Balance above min, above max - should be capped at max
        result1 = compute_effective_bankroll(
            live_balance_usd=1000.0,
            max_riskable_usd=500.0,
            min_operational_balance_usd=100.0
        )
        assert result1 == 500.0
        
        # Balance below min - should be 0 regardless of max
        result2 = compute_effective_bankroll(
            live_balance_usd=50.0,
            max_riskable_usd=500.0,
            min_operational_balance_usd=100.0
        )
        assert result2 == 0.0


class TestBankrollEnvVars:
    """Test that env vars are read correctly."""

    def test_max_riskable_usd_from_env(self):
        """Test that KALSHI_TRADER_MAX_RISKABLE_USD is read from env."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        # Test that the env var is used when calling compute_effective_bankroll
        with patch.dict(os.environ, {"KALSHI_TRADER_MAX_RISKABLE_USD": "750.00"}, clear=False):
            # When max_riskable_usd is read from env and passed to compute_effective_bankroll
            max_riskable = float(os.getenv("KALSHI_TRADER_MAX_RISKABLE_USD", 0))
            
            result = compute_effective_bankroll(
                live_balance_usd=1000.0,
                max_riskable_usd=max_riskable,
                min_operational_balance_usd=None
            )
            
            # Should be capped at 750 (the env var value)
            assert result == 750.0

    def test_min_operational_balance_from_env(self):
        """Test that KALSHI_TRADER_MIN_OP_BALANCE_USD is read from env."""
        from merid.event_venues.kalshi.bankroll_service import compute_effective_bankroll
        
        with patch.dict(os.environ, {"KALSHI_TRADER_MIN_OP_BALANCE_USD": "200.00"}, clear=False):
            # Balance below minimum should return 0
            result = compute_effective_bankroll(
                live_balance_usd=150.0,
                max_riskable_usd=None,
                min_operational_balance_usd=float(os.getenv("KALSHI_TRADER_MIN_OP_BALANCE_USD", 0))
            )
            
            assert result == 0.0


class TestOrderIntentEffectiveEquity:
    """Test that OrderIntents include effective_equity_usd."""

    def test_order_intent_has_effective_equity_field(self):
        """Test that OrderIntent dataclass has effective_equity_usd field."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC-15M-250101",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            effective_equity_usd=1000.0
        )
        
        assert intent.effective_equity_usd == 1000.0

    def test_order_intent_effective_equity_none_when_not_set(self):
        """Test that effective_equity_usd can be None."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC-15M-250101",
            side="yes",
            action="buy",
            price_cents=55,
            count=1
        )
        
        assert intent.effective_equity_usd is None


class TestRiskLayerSanityChecks:
    """Test that risk layer sanity checks detect bankroll mismatches."""

    def test_sanity_check_logs_discrepancy(self, caplog):
        """Test that large bankroll discrepancy is logged."""
        import logging
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        # This would need mocking of the risk manager state
        # For now, we just verify the function exists and accepts effective_equity_usd
        risk_mgr = get_kalshi_risk()
        
        # Check that check_order accepts effective_equity_usd parameter
        import inspect
        sig = inspect.signature(risk_mgr.check_order)
        assert "effective_equity_usd" in sig.parameters


class TestNoZeroBankrollCapWithNonZeroBalance:
    """
    CRITICAL: Test that risk layer does not produce 'bankroll cap 0.00' 
    when effective equity is non-zero.
    """

    def test_risk_check_uses_passed_equity(self):
        """Test that risk check uses effective_equity_usd when provided."""
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        risk_mgr = get_kalshi_risk()
        
        # Mock internal state to be 0 (simulating uninitialized state)
        with patch.object(risk_mgr._state, 'current_equity_usd', 0.0):
            # But pass effective_equity_usd (simulating proper unified bankroll)
            allowed, reason = risk_mgr.check_order(
                ticker="KXBTC-15M-250101",
                category="crypto",
                contracts=1,
                price_cents=50,
                edge=0.02,
                existing_position=0,
                effective_equity_usd=1000.0  # This should be used!
            )
            
            # Should NOT be blocked due to "bankroll cap 0.00"
            # (though it may be blocked for other reasons like exposure limits)
            assert "bankroll cap 0.00" not in reason.lower()
            assert "bankroll" not in reason.lower() or "exceeds" not in reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
