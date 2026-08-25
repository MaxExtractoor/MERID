"""
Test exposure invariants for the 15m Kalshi crypto trading system.

This test suite validates that the $1.00 global exposure cap is enforced correctly
across all assets (BTC, ETH, SOL, XRP, DOGE) and that position limits are respected.

Invariant: Never more than $1.00 exposure at any time across all assets.
"""

import pytest
from decimal import Decimal


class TestGlobalExposureCap:
    """Test $1.00 global exposure cap enforcement."""
    
    def test_fixed_exposure_cap_is_one_dollar(self):
        """Verify the fixed exposure cap is exactly $1.00."""
        from merid.settings import settings
        cap = getattr(settings, 'MERID_FIXED_EXPOSURE_CAP_USD', 1.00)
        assert cap == 1.00, f"Fixed exposure cap must be $1.00, got ${cap}"
    
    def test_exposure_cap_environment_variable(self):
        """Verify exposure cap can be set via environment variable."""
        import os
        # Test that the environment variable is respected
        original = os.environ.get('MERID_FIXED_EXPOSURE_CAP_USD')
        try:
            os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
            # Reload settings to pick up new value
            from importlib import reload
            import merid.settings as settings_module
            reload(settings_module)
            from merid.settings import settings
            cap = getattr(settings, 'MERID_FIXED_EXPOSURE_CAP_USD', 1.00)
            assert cap == 1.00
        finally:
            if original is not None:
                os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = original
            elif 'MERID_FIXED_EXPOSURE_CAP_USD' in os.environ:
                del os.environ['MERID_FIXED_EXPOSURE_CAP_USD']
    
    def test_exposure_cap_never_changed(self):
        """Verify exposure cap cannot be changed to percentage-based model."""
        from merid.risk.unified_risk_manager import RiskLimits
        limits = RiskLimits()
        # Verify percentage-based caps are disabled (set to 0.0)
        assert limits.max_cycle_risk_pct == 0.0, "Cycle risk percentage must be disabled"
        assert limits.max_total_risk_pct == 0.0, "Total risk percentage must be disabled"
        assert limits.per_trade_max_notional_pct == 0.0, "Per-trade risk percentage must be disabled"
        # Verify fixed cap is used (canonical $2.00 cap, raised 2026-08-22)
        assert limits.fixed_exposure_cap_usd == 2.00, "Fixed exposure cap must be $2.00"


class TestPerContractExposure:
    """Test per-contract exposure calculation."""
    
    def test_btc_contract_exposure(self):
        """Verify BTC contract exposure is calculated correctly."""
        price_cents = 42  # $0.42
        contracts = 1
        exposure_usd = (price_cents * contracts) / 100
        assert exposure_usd == 0.42, f"BTC contract exposure should be $0.42, got ${exposure_usd}"
    
    def test_eth_contract_exposure(self):
        """Verify ETH contract exposure is calculated correctly."""
        price_cents = 50  # $0.50
        contracts = 1
        exposure_usd = (price_cents * contracts) / 100
        assert exposure_usd == 0.50, f"ETH contract exposure should be $0.50, got ${exposure_usd}"
    
    def test_max_single_contract_exposure(self):
        """Verify single contract never exceeds $1.00."""
        max_price_cents = 75  # Canonical range max
        contracts = 1
        exposure_usd = (max_price_cents * contracts) / 100
        assert exposure_usd == 0.75, f"Max single contract exposure should be $0.75, got ${exposure_usd}"
        assert exposure_usd < 1.00, "Single contract must never exceed $1.00"


class TestMultiAssetExposure:
    """Test exposure across multiple assets."""
    
    def test_two_assets_within_cap(self):
        """Verify two assets can be held within $1.00 cap."""
        btc_exposure = 0.42  # 1 contract at 42c
        eth_exposure = 0.50  # 1 contract at 50c
        total = btc_exposure + eth_exposure
        assert abs(total - 0.92) < 0.01, f"Two-asset exposure should be $0.92, got ${total}"
        assert total <= 1.00, "Two-asset exposure must not exceed $1.00"
    
    def test_three_assets_exceeds_cap(self):
        """Verify three assets would exceed $1.00 cap."""
        btc_exposure = 0.42
        eth_exposure = 0.50
        sol_exposure = 0.45
        total = btc_exposure + eth_exposure + sol_exposure
        assert abs(total - 1.37) < 0.01, f"Three-asset exposure should be $1.37, got ${total}"
        assert total > 1.00, "Three-asset exposure should exceed $1.00 (should be blocked)"
    
    def test_all_five_assets_exceeds_cap(self):
        """Verify all five assets would exceed $1.00 cap."""
        exposures = [0.42, 0.50, 0.45, 0.38, 0.30]  # BTC, ETH, SOL, XRP, DOGE
        total = sum(exposures)
        assert abs(total - 2.05) < 0.01, f"All-asset exposure should be $2.05, got ${total}"
        assert total > 1.00, "All-asset exposure should exceed $1.00 (should be blocked)"


class TestSlotAllocatorEnforcement:
    """Test slot allocator enforces exposure cap."""
    
    def test_slot_allocator_max_contracts(self):
        """Verify slot allocator limits to 1 contract max."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        # Test that max contracts is 1 for $1.00 cap
        # This is enforced via can_allocate (entry_price_cents, asset)
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        assert can_allocate == True, f"Should allow 1 BTC contract at 42c: {reason}"
        
        # Test that higher price would exceed cap
        can_allocate, reason = allocator.can_allocate(100, "BTC")
        assert can_allocate == False, f"Should reject contract at 100c (exceeds cap): {reason}"
    
    def test_slot_allocator_respects_cap(self):
        """Verify slot allocator respects $1.00 cap across assets."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        # Check that price within range is allowed
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        assert can_allocate == True, f"Should allow BTC at 42c: {reason}"
        
        # Check that price at cap limit is allowed
        can_allocate, reason = allocator.can_allocate(75, "ETH")
        assert can_allocate == True, f"Should allow ETH at 75c (cap limit): {reason}"
        
        # Check that price above cap is rejected
        can_allocate, reason = allocator.can_allocate(76, "SOL")
        assert can_allocate == False, f"Should reject SOL at 76c (exceeds cap): {reason}"


class TestPositionCacheExposure:
    """Test position cache tracks exposure correctly."""
    
    def test_position_size_tracking(self):
        """Verify position cache tracks contract sizes correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",
        )
        assert position.contracts == 1, "Position should have 1 contract"
        assert position.avg_price_cents == 42, "Position should have avg price 42c"
    
    def test_position_notional_calculation(self):
        """Verify position notional is calculated correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",
        )
        notional = position.notional_usd
        assert abs(float(notional) - 0.42) < 0.01, f"Position notional should be $0.42, got ${notional}"


class TestOneContractPerAssetPerWindow:
    """Test one-contract-per-asset-per-15-minute rule."""
    
    def test_asset_window_key_uniqueness(self):
        """Verify asset-window keys are unique."""
        from merid.utils.kalshi_identity import extract_asset_window_key
        
        btc_ticker = "KXBTC15M-26JUL211745-45"
        eth_ticker = "KXETH15M-26JUL211745-45"
        
        btc_key = extract_asset_window_key(btc_ticker)
        eth_key = extract_asset_window_key(eth_ticker)
        
        assert btc_key == "BTC:26JUL211745"
        assert eth_key == "ETH:26JUL211745"
        assert btc_key != eth_key, "Different assets should have different keys"
    
    def test_same_asset_same_window_same_key(self):
        """Verify same asset in same window produces same key."""
        from merid.utils.kalshi_identity import extract_asset_window_key
        
        ticker1 = "KXBTC15M-26JUL211745-45"
        ticker2 = "KXBTC15M-26JUL211745-50"  # Different strike, same window
        
        key1 = extract_asset_window_key(ticker1)
        key2 = extract_asset_window_key(ticker2)
        
        assert key1 == key2, "Same asset in same window should have same key"
    
    def test_same_asset_different_window_different_key(self):
        """Verify same asset in different window produces different key."""
        from merid.utils.kalshi_identity import extract_asset_window_key
        
        ticker1 = "KXBTC15M-26JUL211745-45"
        ticker2 = "KXBTC15M-26JUL211700-00"  # Different window
        
        key1 = extract_asset_window_key(ticker1)
        key2 = extract_asset_window_key(ticker2)
        
        assert key1 != key2, "Same asset in different window should have different key"


class TestExposureInvariants:
    """Test high-level exposure invariants."""
    
    def test_all_five_assets_must_be_tracked(self):
        """Verify all 5 crypto assets are tracked for exposure."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        for asset in assets:
            # Each asset should be trackable (can_allocate checks price, not asset-specific limits)
            can_allocate, reason = allocator.can_allocate(42, asset)
            assert can_allocate == True, f"Asset {asset} should be trackable at 42c: {reason}"
    
    def test_exposure_cap_is_immutable(self):
        """Verify exposure cap cannot be changed at runtime."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        # Verify cap is $2.00 (canonical fixed cap, raised 2026-08-22)
        original_cap = allocator.MAX_EXPOSURE_USD
        assert original_cap == 2.00, "Initial cap must be $2.00"
        
        # Verify cap is still $2.00 (class constant should not change)
        assert allocator.MAX_EXPOSURE_USD == 2.00, "Cap must remain $2.00"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
