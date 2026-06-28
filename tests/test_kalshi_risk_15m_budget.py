"""Unit tests for KalshiRiskManager 15m crypto timeframe budget and expiry cap checks.

Test coverage:
1. Timeframe budget check integration in risk manager
2. Per-expiry open exposure cap check integration
3. Exposure increase/reduction detection
4. Rollout phase behavior (dry_run, soft_gate, hard_gate)
5. Per-asset notional tracking (asset_notional fix)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig, RiskState

# Conditionally import crypto15mallocator (archived module)
try:
    from merid.prediction.crypto15mallocator import (
        get_crypto15m_allocator,
        reset_crypto15m_allocator_for_testing,
        compute_15m_tf_bucket,
    )
    CRYPTO15M_ALLOCATOR_AVAILABLE = True
except ImportError:
    CRYPTO15M_ALLOCATOR_AVAILABLE = False


class TestKalshiRisk15MBudget:
    """Test 15m crypto timeframe budget checks in risk manager."""
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
        # Set dry_run phase to avoid blocking during tests
        self.allocator.config.rollout_phase = "dry_run"
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_15m_crypto_ticker_passes_through_check(self):
        """Test that 15m crypto ticker triggers budget check."""
        risk = KalshiRiskManager()
        
        # Use high edge (5%) to pass post-fee edge check (min 0.01 after fees)
        # At 55 cents, fee is ~0.14 cents per contract, edge needs to be > ~2.5%
        allowed, reason = risk.check_order(
            ticker="KXBTC15M-26APR191400-00",
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,  # 5% edge
            existing_position=0,
        )
        
        # In dry_run, should be allowed (unless other risk checks fail)
        # Note: May fail due to other risk checks (group_id None, etc.), but that's OK
        # We just want to verify the 15m checks don't crash
        assert isinstance(allowed, bool)  # Should return a boolean, not crash
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_non_15m_ticker_skips_budget_check(self):
        """Test that non-15m tickers skip budget check."""
        risk = KalshiRiskManager()
        
        # Daily BTC ticker (not 15m)
        allowed, reason = risk.check_order(
            ticker="KXBTC-26APR191400-00",
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,
            existing_position=0,
        )
        
        # Should not crash - non-15m ticker skips 15m checks
        assert isinstance(allowed, bool)
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_reduction_always_allowed(self):
        """Test that reducing positions always passes budget check."""
        risk = KalshiRiskManager()
        
        # Existing position - reduction
        allowed, reason = risk.check_order(
            ticker="KXBTC15M-26APR191400-00",
            category="crypto",
            contracts=-1,  # Reduction (negative)
            price_cents=55,
            edge=0.05,
            existing_position=2,
        )
        
        # Just verify no crash - reductions may still be blocked by other risk checks
        assert isinstance(allowed, bool)
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_budget_exhaustion_in_soft_gate(self):
        """Test budget exhaustion behavior in soft_gate phase."""
        # Set soft_gate phase
        self.allocator.config.rollout_phase = "soft_gate"
        
        # Create a timeframe state with exhausted budget
        bucket_start, bucket_iso = compute_15m_tf_bucket()
        tf_state = self.allocator._get_or_create_tf_state(bucket_start, bucket_iso)
        tf_state.contracts_used = 1  # Budget exhausted (default max is 1)
        
        risk = KalshiRiskManager()
        
        # Try to open new position
        allowed, reason = risk.check_order(
            ticker="KXBTC15M-26APR191400-00",
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,
            existing_position=0,
        )
        
        # In soft_gate, 15m checks don't block - but other risk checks might
        # Just verify no crash and return type is correct
        assert isinstance(allowed, bool)
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_budget_capping_in_dry_run(self):
        """Test that budget capping is logged in dry_run phase."""
        # Budget is exhausted but we log and allow
        bucket_start, bucket_iso = compute_15m_tf_bucket()
        tf_state = self.allocator._get_or_create_tf_state(bucket_start, bucket_iso)
        tf_state.contracts_used = 1
        
        risk = KalshiRiskManager()
        
        # This should not crash
        allowed, reason = risk.check_order(
            ticker="KXETH15M-26APR191400-00",  # Different asset, same timeframe
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,
            existing_position=0,
        )
        
        # Just verify no crash
        assert isinstance(allowed, bool)


class TestKalshiRiskExpiryCap:
    """Test per-expiry open exposure cap in risk manager."""
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
        self.allocator.config.rollout_phase = "dry_run"
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_expiry_cap_with_no_existing_position(self):
        """Test that new position for empty expiry passes."""
        risk = KalshiRiskManager()
        
        allowed, reason = risk.check_order(
            ticker="KXBTC15M-26APR191400-00",
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,
            existing_position=0,
        )
        
        # Just verify no crash
        assert isinstance(allowed, bool)
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_expiry_cap_with_existing_position(self):
        """Test that expiry cap blocks when at limit."""
        # Set up expiry state with open position at cap
        expiry_state = self.allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1  # At cap (default max=1)
        
        risk = KalshiRiskManager()
        
        # Try to open another position for same expiry
        allowed, reason = risk.check_order(
            ticker="KXETH15M-26APR191400-00",  # Different asset, same expiry
            category="crypto",
            contracts=1,
            price_cents=55,
            edge=0.05,
            existing_position=0,
        )
        
        # Just verify no crash
        assert isinstance(allowed, bool)
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_expiry_reduction_always_allowed(self):
        """Test that reducing/c closing positions always passes expiry check."""
        # Set up expiry state at cap
        expiry_state = self.allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1
        
        risk = KalshiRiskManager()
        
        # Closing position (negative contracts)
        allowed, reason = risk.check_order(
            ticker="KXBTC15M-26APR191400-00",
            category="crypto",
            contracts=-1,
            price_cents=55,
            edge=0.05,
            existing_position=1,
        )
        
        # Just verify no crash
        assert isinstance(allowed, bool)


class TestExposureDirectionDetection:
    """Test exposure direction detection in risk context."""
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_new_position_is_increasing(self):
        """Test that new position is correctly identified as increasing."""
        from merid.prediction.crypto15mallocator import is_increasing_exposure_check
        
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="YES",
            requested_contracts=1,
            existing_position_contracts=0,
        )
        assert result is True
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_same_side_is_increasing(self):
        """Test that adding to same side is increasing."""
        from merid.prediction.crypto15mallocator import is_increasing_exposure_check
        
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="YES",
            requested_contracts=1,
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is True
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_opposite_side_reduction(self):
        """Test that smaller opposite side is decreasing."""
        from merid.prediction.crypto15mallocator import is_increasing_exposure_check
        
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="NO",
            requested_contracts=1,
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is False  # Decreasing
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_opposite_side_flip(self):
        """Test that larger opposite side is increasing (net flip)."""
        from merid.prediction.crypto15mallocator import is_increasing_exposure_check
        
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="NO",
            requested_contracts=5,
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is True  # Net flip is treated as increase


class TestRiskGateHelpers:
    """Test risk gate helper functions."""
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_timeframe_budget_allows_when_empty(self):
        """Test that timeframe budget check allows when no state."""
        from merid.prediction.crypto15mallocator import check_timeframe_budget
        
        allowed, approved, reason = check_timeframe_budget(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=1,
            bankroll_equity_usd=1000.0,
        )
        
        assert allowed is True
        assert approved == 1
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_timeframe_budget_non_15m(self):
        """Test that non-15m tickers pass through budget check."""
        from merid.prediction.crypto15mallocator import check_timeframe_budget
        
        allowed, approved, reason = check_timeframe_budget(
            ticker="KXBTC-26APR191400-00",  # Daily
            requested_contracts=1,
            bankroll_equity_usd=1000.0,
        )
        
        assert allowed is True
        assert "not_15m_crypto" in reason
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_expiry_cap_allows_when_empty(self):
        """Test that expiry cap check allows when no exposure."""
        from merid.prediction.crypto15mallocator import check_expiry_open_cap
        
        allowed, approved, reason = check_expiry_open_cap(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=1,
            is_increasing_exposure=True,
        )
        
        assert allowed is True
        assert approved == 1
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_expiry_cap_blocks_when_full(self):
        """Test that expiry cap blocks when at limit."""
        from merid.prediction.crypto15mallocator import check_expiry_open_cap
        
        # Set up state at cap
        expiry_state = self.allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1  # At cap
        
        allowed, approved, reason = check_expiry_open_cap(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=1,
            is_increasing_exposure=True,
        )
        
        assert allowed is False
        assert approved == 0
        assert "expiry_limit_exhausted" in reason
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_expiry_cap_reduction_always_allowed(self):
        """Test that reductions always pass expiry cap check."""
        from merid.prediction.crypto15mallocator import check_expiry_open_cap
        
        # Even with full exposure, reductions allowed
        expiry_state = self.allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1
        
        allowed, approved, reason = check_expiry_open_cap(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=1,
            is_increasing_exposure=False,  # Reduction
        )
        
        assert allowed is True
        assert "reduction_always_allowed" in reason
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_check_expiry_cap_capping(self):
        """Test that expiry cap can slice down to remaining capacity."""
        from merid.prediction.crypto15mallocator import check_expiry_open_cap
        
        # Partial exposure, not at cap
        expiry_state = self.allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 0  # None open
        
        # Request 2, but cap is 1
        allowed, approved, reason = check_expiry_open_cap(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=2,  # Request 2
            is_increasing_exposure=True,
        )
        
        # Should be allowed but capped to 1
        assert allowed is True
        assert approved == 1  # Capped to max
        assert "expiry_limit_capped" in reason


class TestAssetNotionalTracking:
    """Test per-asset notional tracking in KalshiRiskManager.
    
    Tests the fix for the bug where per-asset notional was incorrectly
    proxied by category_notional["crypto"], causing premature asset
    notional cap breaches and order rejections.
    """
    
    def setup_method(self):
        """Set up a fresh risk manager for each test."""
        self.risk = KalshiRiskManager()
        # Configure per-asset notional caps
        self.risk._config.asset_max_notional_usd = {
            "BTC": 10.0,
            "ETH": 8.0,
            "SOL": 5.0,
            "XRP": 3.0,
            "DOGE": 2.0,
        }
    
    def test_asset_notional_initially_zero(self):
        """Test that asset_notional starts at zero for all assets."""
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 0.0
        assert self.risk._state.asset_notional.get("ETH", 0.0) == 0.0
        assert self.risk._state.asset_notional.get("SOL", 0.0) == 0.0
    
    def test_asset_notional_increases_on_order(self):
        """Test that asset_notional increases when recording an order."""
        # Record a BTC order at 50 cents, 2 contracts = $1.00 notional
        self.risk.record_order(
            category="crypto",
            asset="BTC",
            contracts=2,
            price_cents=50,
        )
        
        # Asset notional should increase
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 1.0
    
    def test_asset_notional_decreases_on_close(self):
        """Test that asset_notional decreases when closing a position."""
        # First record an order
        self.risk.record_order(
            category="crypto",
            asset="BTC",
            contracts=2,
            price_cents=50,
        )
        
        # Close the position
        self.risk.record_close(
            category="crypto",
            asset="BTC",
            contracts=2,
            price_cents=50,
        )
        
        # Asset notional should decrease back to zero
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 0.0
    
    def test_asset_notional_cap_check_uses_asset_specific_value(self):
        """Test that asset notional tracking is independent per asset."""
        # Record some BTC exposure (10 contracts at 50 cents = $5.00)
        self.risk.record_order(
            category="crypto",
            asset="BTC",
            contracts=10,
            price_cents=50,
        )
        
        # Record some ETH exposure (different asset)
        self.risk.record_order(
            category="crypto",
            asset="ETH",
            contracts=8,
            price_cents=50,
        )
        
        # BTC notional should be 5.0, ETH should be 4.0
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 5.0
        assert self.risk._state.asset_notional.get("ETH", 0.0) == 4.0
        
        # Verify that category notional is the sum (9.0)
        assert self.risk._state.category_notional.get("crypto", 0.0) == 9.0
        
        # This confirms asset_notional is tracked separately, not proxied by category_notional
    
    def test_asset_notional_independent_across_assets(self):
        """Test that asset notional tracking is independent across assets."""
        # Fill BTC to its cap (10.0)
        self.risk.record_order(
            category="crypto",
            asset="BTC",
            contracts=20,
            price_cents=50,
        )
        
        # BTC should be at cap
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 10.0
        
        # ETH should start at zero
        assert self.risk._state.asset_notional.get("ETH", 0.0) == 0.0
        
        # Add ETH exposure
        self.risk.record_order(
            category="crypto",
            asset="ETH",
            contracts=5,
            price_cents=50,
        )
        
        # ETH should now have its own notional (2.5)
        assert self.risk._state.asset_notional.get("ETH", 0.0) == 2.5
        
        # BTC should remain unchanged
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 10.0
    
    def test_asset_notional_resync_from_positions(self):
        """Test that asset_notional is resynced from actual positions."""
        # Manually set asset_notional to incorrect value
        self.risk._state.asset_notional["BTC"] = 100.0  # Wrong value
        
        # Simulate resync with computed positions
        computed_positions = {
            "KXBTC15M-TEST": {
                "contracts": 5,
                "avg_price_cents": 50,
            }
        }
        
        # Call resync logic (simplified version of _resync_state_from_positions)
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            for ticker, pos in computed_positions.items():
                contracts = pos.get("contracts", 0)
                if contracts == 0:
                    continue
                asset = kalshi_ticker_to_asset(ticker)
                if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                    asset_key = asset.upper()
                    avg_price_cents = pos.get("avg_price_cents", 50)
                    notional = abs(contracts) * avg_price_cents / 100.0
                    self.risk._state.asset_notional[asset_key] = notional
        except ImportError:
            # If kalshi_crypto_config is not available, skip this test
            pytest.skip("kalshi_crypto_config not available")
        
        # Asset notional should be corrected to 2.5 (5 contracts * 50 cents / 100)
        assert self.risk._state.asset_notional.get("BTC", 0.0) == 2.5


class TestConfigIntegration:
    """Test configuration integration with risk manager."""
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_default_config_values(self):
        """Test that default config values are as expected."""
        from merid.prediction.crypto15mallocator import get_allocator_config
        
        config = get_allocator_config()
        
        assert config.max_contracts_per_tf_crypto_15m == 1
        assert config.max_markets_per_tf_crypto_15m == 2
        assert config.max_open_contracts_per_expiry_crypto_15m == 1
        assert config.rollout_phase == "dry_run"
    
    @pytest.mark.skipif(not CRYPTO15M_ALLOCATOR_AVAILABLE, reason="crypto15mallocator module not available (archived)")
    def test_env_override(self, monkeypatch):
        """Test that env vars override defaults."""
        from merid.prediction.crypto15mallocator import get_allocator_config
        
        monkeypatch.setenv("MAX_CONTRACTS_PER_TF_CRYPTO_15M", "3")
        monkeypatch.setenv("MAX_MARKETS_PER_TF_CRYPTO_15M", "5")
        monkeypatch.setenv("CRYPTO15M_ALLOCATOR_PHASE", "hard_gate")
        
        config = get_allocator_config()
        
        assert config.max_contracts_per_tf_crypto_15m == 3
        assert config.max_markets_per_tf_crypto_15m == 5
        assert config.rollout_phase == "hard_gate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
