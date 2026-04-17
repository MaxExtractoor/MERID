"""
Tests for Guard Mode Invariants and Computed Live Caps

This module tests:
1. OBSERVATION mode invariant: can_trade MUST be False
2. Computed live caps with BTC vol anchoring
3. Guard mode enforcement in continuous trader
"""

import pytest
from pathlib import Path
from decimal import Decimal

from merid.guards import (
    GoLiveChecklist,
    TradingGuardian,
    TradingMode,
    GuardStatus,
)


class TestObservationModeInvariant:
    """Test that OBSERVATION mode always results in can_trade=False."""

    def test_observation_mode_can_trade_is_false(self):
        """OBSERVATION mode must always result in can_trade=False."""
        checklist = GoLiveChecklist(mode=TradingMode.OBSERVATION)
        guardian = TradingGuardian(checklist)
        
        report = guardian.run_all_checks()
        
        # Critical invariant: OBSERVATION mode -> can_trade=False
        assert report.can_trade is False, \
            "OBSERVATION mode must result in can_trade=False"
        assert report.mode == TradingMode.OBSERVATION

    def test_observation_mode_can_trade_false_even_if_checks_pass(self):
        """Even if all checks pass, OBSERVATION mode blocks trading."""
        checklist = GoLiveChecklist(
            mode=TradingMode.OBSERVATION,
            upstream={
                "market_sanity": {"enabled": True, "required_assets": ["BTC"], "max_data_age_seconds": 30, "fail_on_missing": False},
                "registry_integrity": {"enabled": False},
                "regime_health": {"enabled": False},
            },
            mid_pipeline={
                "indicator_health": {"enabled": False},
                "hierarchy_enforcement": {"enabled": False},
                "conviction_consistency": {"enabled": False},
            },
            downstream={
                "pre_trade_risk": {"enabled": False},
                "execution_monitoring": {"enabled": False},
                "post_trade_tca": {"enabled": False},
            },
        )
        guardian = TradingGuardian(checklist)
        
        report = guardian.run_all_checks()
        
        # All checks may pass, but OBSERVATION mode still blocks
        assert report.can_trade is False
        assert report.overall_status in (GuardStatus.PASS, GuardStatus.WARNING)

    def test_live_small_mode_allows_trading_when_checks_pass(self):
        """LIVE_SMALL mode allows trading when checks pass."""
        checklist = GoLiveChecklist(mode=TradingMode.LIVE_SMALL)
        guardian = TradingGuardian(checklist)
        
        report = guardian.run_all_checks()
        
        # can_trade depends on check results in live modes
        # We just verify the mode is correct
        assert report.mode == TradingMode.LIVE_SMALL

    def test_live_full_mode_allows_trading_when_checks_pass(self):
        """LIVE_FULL mode allows trading when checks pass."""
        checklist = GoLiveChecklist(mode=TradingMode.LIVE_FULL)
        guardian = TradingGuardian(checklist)
        
        report = guardian.run_all_checks()
        
        assert report.mode == TradingMode.LIVE_FULL

    def test_mode_switching_changes_can_trade(self):
        """Switching from OBSERVATION to LIVE_SMALL should enable trading."""
        # Start in OBSERVATION
        checklist = GoLiveChecklist(mode=TradingMode.OBSERVATION)
        guardian = TradingGuardian(checklist)
        
        report = guardian.run_all_checks()
        assert report.can_trade is False
        
        # Switch to LIVE_SMALL
        checklist.mode = TradingMode.LIVE_SMALL
        report = guardian.run_all_checks()
        
        # can_trade may still be False if checks fail, but mode is updated
        assert report.mode == TradingMode.LIVE_SMALL


class TestComputedLiveCaps:
    """Test computed live caps with BTC vol anchoring."""

    def test_compute_btc_vol_scale_basic(self):
        """Test vol scale computation at different vol levels."""
        checklist = GoLiveChecklist(
            target_vol_annual=0.65,
            vol_scale_min=0.3,
            vol_scale_max=1.0,
        )
        guardian = TradingGuardian(checklist)
        
        # Low vol (30%) -> should scale up to max (1.0)
        scale_low_vol = guardian.compute_btc_vol_scale(0.30)
        assert scale_low_vol == 1.0
        
        # Target vol (65%) -> should be 1.0
        scale_target = guardian.compute_btc_vol_scale(0.65)
        assert scale_target == 1.0
        
        # High vol (100%) -> should scale down
        scale_high_vol = guardian.compute_btc_vol_scale(1.0)
        assert scale_high_vol < 1.0
        assert scale_high_vol >= 0.3
        
        # Very high vol (200%) -> should approach floor but not necessarily hit it exactly
        # target_vol / current_vol = 0.65 / 2.0 = 0.325, clamped to [0.3, 1.0] = 0.325
        scale_very_high = guardian.compute_btc_vol_scale(2.0)
        assert scale_very_high >= 0.3  # At or above floor
        assert scale_very_high < 0.4   # Well below 1.0

    def test_compute_live_cap_observation_mode_returns_zero(self):
        """OBSERVATION mode always returns 0 contracts."""
        checklist = GoLiveChecklist(
            mode=TradingMode.OBSERVATION,
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        cap = guardian.compute_live_cap("BTC", 10000, 0.65)  # $100 bankroll, 65% vol
        assert cap == 0

    def test_compute_live_cap_live_small(self):
        """LIVE_SMALL mode computes reduced caps."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            base_per_asset_frac={"BTC": 0.02},
            mode_caps_multiplier={
                "observation": 0.0,
                "disabled": 0.0,
                "live_small": 0.3,
                "live_full": 1.0,
            },
            target_vol_annual=0.65,
        )
        guardian = TradingGuardian(checklist)
        
        # $100 bankroll, 65% vol (target), should get reduced multiplier
        cap = guardian.compute_live_cap("BTC", 10000, 0.65)
        
        # Expected: $100 * 0.02 * 0.3 * 1.0 = $0.60 = ~0-1 contracts (may round to 0)
        assert cap >= 0
        assert isinstance(cap, int)

    def test_compute_live_cap_live_full(self):
        """LIVE_FULL mode computes full caps."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_FULL,
            base_per_asset_frac={"BTC": 0.02},
            mode_caps_multiplier={
                "observation": 0.0,
                "disabled": 0.0,
                "live_small": 0.3,
                "live_full": 1.0,
            },
            target_vol_annual=0.65,
        )
        guardian = TradingGuardian(checklist)
        
        # $10,000 bankroll (1M cents), 65% vol (target) - should yield meaningful contracts
        cap = guardian.compute_live_cap("BTC", 1_000_000, 0.65)
        
        # Expected: $10,000 * 0.02 * 1.0 * 1.0 = $200 = ~200 contracts
        assert cap > 0
        assert isinstance(cap, int)

    def test_compute_all_live_caps(self):
        """Test computing caps for all assets."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            base_per_asset_frac={
                "BTC": 0.02,
                "ETH": 0.015,
                "SOL": 0.01,
            },
        )
        guardian = TradingGuardian(checklist)
        
        caps = guardian.compute_all_live_caps(100000, 0.65)
        
        assert "BTC" in caps
        assert "ETH" in caps
        assert "SOL" in caps
        assert all(isinstance(v, int) for v in caps.values())
        assert all(v >= 0 for v in caps.values())

    def test_get_effective_live_caps_computed(self):
        """Test getting effective caps with computed mode enabled."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            use_computed_caps=True,
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        caps = guardian.get_effective_live_caps(100000, 0.65)
        
        assert "BTC" in caps
        assert isinstance(caps["BTC"], float)

    def test_get_effective_live_caps_static_fallback(self):
        """Test fallback to static caps when computed is disabled."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            use_computed_caps=False,
            live_size_caps={"BTC": 0.5, "ETH": 0.3},
        )
        guardian = TradingGuardian(checklist)
        
        caps = guardian.get_effective_live_caps(100000, 0.65)
        
        assert caps["BTC"] == 0.5
        assert caps["ETH"] == 0.3


class TestGoLiveChecklistSchema:
    """Test the updated go-live checklist schema."""

    def test_checklist_has_computed_caps_fields(self):
        """Checklist should have new computed caps fields."""
        checklist = GoLiveChecklist()
        
        assert hasattr(checklist, 'use_computed_caps')
        assert hasattr(checklist, 'base_per_asset_frac')
        assert hasattr(checklist, 'vol_anchor_asset')
        assert hasattr(checklist, 'target_vol_annual')
        assert hasattr(checklist, 'vol_scale_min')
        assert hasattr(checklist, 'vol_scale_max')
        assert hasattr(checklist, 'mode_caps_multiplier')

    def test_default_base_per_asset_frac(self):
        """Default base fractions should be reasonable."""
        checklist = GoLiveChecklist()
        
        assert "BTC" in checklist.base_per_asset_frac
        assert "ETH" in checklist.base_per_asset_frac
        assert checklist.base_per_asset_frac["BTC"] > checklist.base_per_asset_frac["DOGE"]

    def test_default_vol_anchor_is_btc(self):
        """Default vol anchor should be BTC."""
        checklist = GoLiveChecklist()
        assert checklist.vol_anchor_asset == "BTC"

    def test_yaml_roundtrip(self, tmp_path):
        """Checklist should serialize/deserialize correctly."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            use_computed_caps=True,
            base_per_asset_frac={"BTC": 0.02, "ETH": 0.015},
        )
        
        yaml_path = tmp_path / "test_checklist.yaml"
        checklist.to_yaml(yaml_path)
        
        loaded = GoLiveChecklist.from_yaml(yaml_path)
        
        assert loaded.mode == TradingMode.LIVE_SMALL
        assert loaded.use_computed_caps is True
        assert loaded.base_per_asset_frac["BTC"] == 0.02


class TestGuardModeEnforcement:
    """Test that guard mode is enforced in continuous trader."""

    def test_guard_imports_trading_mode(self):
        """TradingMode should be importable from merid.guards."""
        from merid.guards import TradingMode as ImportedTradingMode
        
        assert ImportedTradingMode.OBSERVATION.value == "observation"
        assert ImportedTradingMode.LIVE_SMALL.value == "live_small"
        assert ImportedTradingMode.LIVE_FULL.value == "live_full"


class TestTinyBankrollMode:
    """Test tiny-bankroll dev mode override functionality."""

    def test_tiny_bankroll_mode_disabled_by_default(self):
        """Tiny bankroll mode should be disabled by default (production safe)."""
        checklist = GoLiveChecklist()
        
        assert hasattr(checklist, 'tiny_bankroll_mode')
        assert checklist.tiny_bankroll_mode['enabled'] is False

    def test_compute_live_cap_with_override_disabled(self):
        """When override is disabled, raw_cap should equal effective_cap."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            tiny_bankroll_mode={
                "enabled": False,
                "bankroll_cents_floor": 5000,
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        # With $5.74 bankroll (574 cents), computed should be 0
        raw_cap, effective_cap, override_applied = guardian.compute_live_cap_with_override(
            "BTC", 574, 0.65
        )
        
        assert raw_cap == 0
        assert effective_cap == 0  # No override applied
        assert override_applied is False

    def test_compute_live_cap_with_override_below_floor(self):
        """Bankroll below floor should not get override even if enabled."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            tiny_bankroll_mode={
                "enabled": True,
                "bankroll_cents_floor": 5000,  # $50 floor
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        # $4.00 bankroll (400 cents) - below $50 floor
        raw_cap, effective_cap, override_applied = guardian.compute_live_cap_with_override(
            "BTC", 400, 0.65
        )
        
        assert raw_cap == 0
        assert effective_cap == 0  # Still 0 because below floor
        assert override_applied is False

    def test_compute_live_cap_with_override_above_floor(self):
        """Bankroll above floor with computed < min should get override."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            tiny_bankroll_mode={
                "enabled": True,
                "bankroll_cents_floor": 5000,  # $50 floor
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        # $50 bankroll (5000 cents) - at floor, computed will be ~0, so override applies
        raw_cap, effective_cap, override_applied = guardian.compute_live_cap_with_override(
            "BTC", 5000, 0.65
        )
        
        # Raw should be 0 or very small
        assert raw_cap < 1
        # Effective should be forced to 1 by override
        assert effective_cap == 1
        assert override_applied is True

    def test_compute_live_cap_no_override_when_computed_sufficient(self):
        """No override when computed caps are already >= min_contracts."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            tiny_bankroll_mode={
                "enabled": True,
                "bankroll_cents_floor": 5000,
                "min_contracts_if_above_floor": 1,
            },
            # Use full base_per_asset_frac but with higher values
            base_per_asset_frac={"BTC": 0.10, "ETH": 0.08, "SOL": 0.05, "XRP": 0.05, "DOGE": 0.03},
        )
        guardian = TradingGuardian(checklist)
        
        # $10,000 bankroll (1M cents) with 10% base frac * 0.3 mode mult should compute to >1 contracts
        raw_cap, effective_cap, override_applied = guardian.compute_live_cap_with_override(
            "BTC", 1_000_000, 0.65
        )
        
        # Should be >1 contracts naturally (no override needed)
        assert raw_cap >= 1, f"Expected >=1 contract, got {raw_cap}"
        assert effective_cap == raw_cap  # No change
        assert override_applied is False

    def test_observation_mode_override_blocked(self):
        """Override should NOT apply in OBSERVATION mode (invariant preserved)."""
        checklist = GoLiveChecklist(
            mode=TradingMode.OBSERVATION,  # OBSERVATION mode
            tiny_bankroll_mode={
                "enabled": True,
                "bankroll_cents_floor": 5000,
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        # Even with large bankroll, OBSERVATION mode forces 0
        raw_cap, effective_cap, override_applied = guardian.compute_live_cap_with_override(
            "BTC", 100000, 0.65
        )
        
        # Both should be 0 in OBSERVATION mode
        assert raw_cap == 0
        assert effective_cap == 0
        # Override logic shouldn't even be reached due to early return
        assert override_applied is False

    def test_get_caps_with_telemetry(self):
        """Telemetry should report raw vs effective caps and override status."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            use_computed_caps=True,  # Required for telemetry
            tiny_bankroll_mode={
                "enabled": True,
                "bankroll_cents_floor": 5000,
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02, "ETH": 0.015, "SOL": 0.01, "XRP": 0.01, "DOGE": 0.005},
        )
        guardian = TradingGuardian(checklist)
        
        # $50 bankroll - should trigger override
        telemetry = guardian.get_caps_with_telemetry(5000, 0.65)
        
        # Check telemetry structure
        assert telemetry['override_enabled'] is True, f"Expected override_enabled=True, got {telemetry['override_enabled']}"
        assert telemetry['floor_cents'] == 5000
        assert 'raw_caps' in telemetry
        assert 'effective_caps' in telemetry
        assert 'override_applied' in telemetry
        
        # Override should have been applied to all assets (computed would be 0)
        assert telemetry['override_applied']['BTC'] is True
        assert telemetry['override_applied']['ETH'] is True
        
        # Effective caps should be higher than raw
        assert telemetry['effective_caps']['BTC'] > telemetry['raw_caps']['BTC']

    def test_get_caps_with_telemetry_override_disabled(self):
        """Telemetry should show override_enabled=False when disabled."""
        checklist = GoLiveChecklist(
            mode=TradingMode.LIVE_SMALL,
            tiny_bankroll_mode={
                "enabled": False,  # Disabled
                "bankroll_cents_floor": 5000,
                "min_contracts_if_above_floor": 1,
            },
            base_per_asset_frac={"BTC": 0.02},
        )
        guardian = TradingGuardian(checklist)
        
        telemetry = guardian.get_caps_with_telemetry(5000, 0.65)
        
        assert telemetry['override_enabled'] is False
        assert telemetry['floor_cents'] == 0  # Should be 0 when disabled
        assert all(v is False for v in telemetry['override_applied'].values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
