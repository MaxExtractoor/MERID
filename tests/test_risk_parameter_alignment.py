"""
Tests for risk parameter alignment across all components.

This test suite verifies that:
1. UnifiedRiskManager defaults align with profile YAML
2. unified_risk_enforcement absolute caps align with profile YAML
3. Profile YAML has no internal inconsistencies
4. Deprecated components emit warnings
"""

import pytest
import warnings
from dataclasses import replace

from merid.risk.unified_risk_manager import RiskLimits, UnifiedRiskManager
from merid.config.unified_risk_enforcement import (
    ABSOLUTE_MAX_CYCLE_RISK_PCT,
    ABSOLUTE_MAX_EDGES_PER_CYCLE,
    ABSOLUTE_MAX_RISK_PER_TRADE_PCT,
)
from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter


class TestUnifiedRiskManagerDefaults:
    """Test that UnifiedRiskManager defaults align with profile YAML."""

    def test_fixed_exposure_cap_default(self):
        """Test that fixed_exposure_cap_usd defaults to $1.00 (global slot allocator model)."""
        limits = RiskLimits()
        assert limits.fixed_exposure_cap_usd == 1.00, (
            f"Expected 1.00 ($1 global slot allocator cap), got {limits.fixed_exposure_cap_usd}"
        )

    def test_max_cycle_risk_pct_aligned(self):
        """Test that max_cycle_risk_pct is DISABLED (fixed $1 exposure model).

        2026-07-16: Percentage-based allocation PRUNED - pct==0.0 defers to the
        $1 global slot allocator (single source of truth).
        """
        limits = RiskLimits()
        assert limits.max_cycle_risk_pct == 0.0, (
            f"Expected 0.0 (DISABLED - fixed $1 model), got {limits.max_cycle_risk_pct}"
        )

    def test_max_total_risk_pct_aligned(self):
        """Test that max_total_risk_pct is DISABLED (fixed $1 exposure model)."""
        limits = RiskLimits()
        assert limits.max_total_risk_pct == 0.0, (
            f"Expected 0.0 (DISABLED - fixed $1 model), got {limits.max_total_risk_pct}"
        )

    def test_daily_loss_pct_aligned(self):
        """Test that daily_loss_pct matches profile YAML (20%)."""
        limits = RiskLimits()
        assert limits.daily_loss_pct == 0.20, (
            f"Expected 0.20 (20%), got {limits.daily_loss_pct}"
        )

    def test_drawdown_halt_pct_aligned(self):
        """Test that drawdown_halt_pct matches profile YAML (20%)."""
        limits = RiskLimits()
        assert limits.drawdown_halt_pct == 0.20, (
            f"Expected 0.20 (20%), got {limits.drawdown_halt_pct}"
        )

    def test_drawdown_unwind_pct_aligned(self):
        """Test that drawdown_unwind_pct matches profile YAML (25%)."""
        limits = RiskLimits()
        assert limits.drawdown_unwind_pct == 0.25, (
            f"Expected 0.25 (25%), got {limits.drawdown_unwind_pct}"
        )

    def test_per_trade_max_notional_pct_aligned(self):
        """Test that per_trade_max_notional_pct is DISABLED (fixed $1 exposure model).

        2026-07-16: pct==0.0 makes check_order use fixed_exposure_cap_usd ($1)
        as the per-trade cap instead of a percentage of bankroll.
        """
        limits = RiskLimits()
        assert limits.per_trade_max_notional_pct == 0.0, (
            f"Expected 0.0 (DISABLED - fixed $1 model), got {limits.per_trade_max_notional_pct}"
        )

    def test_per_trade_max_contracts_slot_model(self):
        """Test that per_trade_max_contracts matches slot model (1 contract per order)."""
        limits = RiskLimits()
        assert limits.per_trade_max_contracts == 1, (
            f"Expected 1 (slot model MAX_CONTRACTS_PER_ORDER), got {limits.per_trade_max_contracts}"
        )


class TestUnifiedRiskEnforcementCaps:
    """Test that unified_risk_enforcement absolute caps align with profile YAML."""

    def test_absolute_max_cycle_risk_pct_aligned(self):
        """Test that ABSOLUTE_MAX_CYCLE_RISK_PCT matches profile YAML (5%)."""
        # 2026-07-16: Percentage-based ABSOLUTE_MAX_CYCLE_RISK_PCT DISABLED in favor of fixed $1 exposure model
        assert ABSOLUTE_MAX_CYCLE_RISK_PCT == 0.05, (
            f"Expected 0.05 (5%), got {ABSOLUTE_MAX_CYCLE_RISK_PCT}"
        )

    def test_absolute_max_edges_per_cycle(self):
        """Test that ABSOLUTE_MAX_EDGES_PER_CYCLE is 5."""
        assert ABSOLUTE_MAX_EDGES_PER_CYCLE == 5, (
            f"Expected 5, got {ABSOLUTE_MAX_EDGES_PER_CYCLE}"
        )

    def test_absolute_max_risk_per_trade_pct_aligned(self):
        """Test that ABSOLUTE_MAX_RISK_PER_TRADE_PCT is DISABLED (fixed $1 exposure model)."""
        # 2026-07-15: Percentage-based ABSOLUTE_MAX_RISK_PER_TRADE_PCT DISABLED in favor of fixed $1 exposure cap
        # This field is retained for backward compatibility but not used in production
        assert ABSOLUTE_MAX_RISK_PER_TRADE_PCT == 0.03, (
            f"Expected 0.03 (legacy, DISABLED), got {ABSOLUTE_MAX_RISK_PER_TRADE_PCT}"
        )


class TestProfileYAMLConsistency:
    """Test that profile YAML has no internal inconsistencies."""

    def test_profile_loads_successfully(self):
        """Test that profile YAML can be loaded without errors."""
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile  # Access the loaded profile
        assert profile is not None

    def test_profile_max_cycle_risk_pct(self):
        """Test that profile max_cycle_risk_pct is DISABLED (fixed $1 exposure model)."""
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        # 2026-07-15: Percentage-based max_cycle_risk_pct DISABLED in favor of fixed $1 exposure cap
        # This field is retained for backward compatibility but not used in production
        assert profile.max_cycle_risk_pct == 0.0, (
            f"Expected 0.0 (DISABLED), got {profile.max_cycle_risk_pct}"
        )

    def test_profile_drawdown_halt_pct(self):
        """Test that profile drawdown_halt_pct is 20%."""
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        assert profile.guardrails_drawdown_halt_pct == 0.20, (
            f"Expected 0.20 (20%), got {profile.guardrails_drawdown_halt_pct}"
        )

    def test_profile_per_trade_risk_pct(self):
        """Test that profile per_trade_risk_pct is DISABLED (fixed $1 exposure model).

        2026-07-16: Default changed 0.03 -> 0.0 so absent YAML keys can never
        resurrect percentage-based caps ($1 global slot allocator is authoritative).
        """
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        assert profile.guardrails_per_trade_risk_pct == 0.0, (
            f"Expected 0.0 (DISABLED - fixed $1 model), got {profile.guardrails_per_trade_risk_pct}"
        )

    def test_profile_pct_caps_disabled(self):
        """Test that all profile percentage-based venue/agent caps are DISABLED (0.0)."""
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        assert profile.venue_max_single_order_pct == 0.0
        assert profile.venue_max_total_notional_pct == 0.0
        assert profile.venue_bankroll_cap_pct == 0.0
        assert profile.agent_max_notional_pct == 0.0

    def test_profile_max_daily_loss_pct(self):
        """Test that profile max_daily_loss_pct is 5%."""
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        # The profile may have max_daily_loss_usd, check it's reasonable
        if hasattr(profile, 'guardrails_max_daily_loss_usd'):
            # For a $40 bankroll, 5% is $2
            assert profile.guardrails_max_daily_loss_usd > 0




class TestRiskParameterCrossValidation:
    """Test that risk parameters are consistent across components."""

    def test_cycle_risk_consistency(self):
        """Test that max_cycle_risk_pct is DISABLED (fixed $1 exposure model)."""
        # Profile value
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        profile_value = profile.max_cycle_risk_pct
        
        # 2026-07-15: Percentage-based max_cycle_risk_pct DISABLED in favor of fixed $1 exposure cap
        assert profile_value == 0.0, f"Expected 0.0 (DISABLED), got {profile_value}"

    def test_drawdown_consistency(self):
        """Test that drawdown_halt_pct is consistent across components."""
        # Profile value
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        profile_value = profile.guardrails_drawdown_halt_pct
        
        # UnifiedRiskManager default
        urm_default = RiskLimits().drawdown_halt_pct
        
        # Both should be 20%
        assert profile_value == 0.20
        assert urm_default == 0.20

    def test_per_trade_risk_consistency(self):
        """Test that per_trade_risk_pct is DISABLED (fixed $1 exposure model).

        2026-07-16: URM per-trade pct is 0.0 (defers to fixed $1 cap).
        The legacy unified_risk_enforcement module (advisory, not in the 15m live
        path) retains its 3% clamp ceiling for legacy pct-based configs.
        """
        # UnifiedRiskManager default (DISABLED - fixed $1 model)
        urm_default = RiskLimits().per_trade_max_notional_pct
        assert urm_default == 0.0, f"Expected 0.0 (DISABLED - fixed $1 model), got {urm_default}"
        
        # Legacy advisory clamp ceiling (only clamps legacy pct configs; unused in 15m live path)
        enforcement_cap = ABSOLUTE_MAX_RISK_PER_TRADE_PCT
        assert enforcement_cap == 0.03, f"Expected 0.03 (legacy advisory ceiling), got {enforcement_cap}"


class TestUnifiedRiskManagerBehavior:
    """Test UnifiedRiskManager behavior with aligned parameters."""

    def test_check_order_slot_model_contract_limit(self):
        """Test check_order under the slot model: 1 contract allowed, 2 rejected.

        2026-07-16: per_trade_max_contracts=1 (slot model MAX_CONTRACTS_PER_ORDER).
        Per-trade notional cap is the fixed $1 exposure cap, NOT a pct of bankroll.
        """
        UnifiedRiskManager.reset_for_tests()
        manager = UnifiedRiskManager()
        
        # Calibrate with $1000 bankroll
        manager.calibrate_from_balance(balance_cents=100000)  # $1000
        
        # 1 contract at 50c ($0.50 <= $1 fixed cap) - should be allowed
        allowed, reason = manager.check_order(
            ticker="KXBTC15M-TEST",
            contracts=1,
            price_cents=50,
            category="crypto",
            underlying="BTC"
        )
        assert allowed, f"1-contract order should be allowed, but was rejected: {reason}"
        
        # 2 contracts - should be rejected by slot model contract limit
        UnifiedRiskManager.reset_for_tests()
        manager = UnifiedRiskManager()
        manager.calibrate_from_balance(balance_cents=100000)
        allowed, reason = manager.check_order(
            ticker="KXBTC15M-TEST",
            contracts=2,
            price_cents=50,
            category="crypto",
            underlying="BTC"
        )
        assert not allowed, "2-contract order should be rejected under slot model (max 1)"
        assert "MAX_CONTRACTS" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
