"""Tests for ExitPolicyResolution and coherent risk contract system."""

import pytest
from datetime import datetime

from merid.prediction.dynamic_entry_window import (
    WindowResolution,
    ExitPolicyResolution,
    RiskTier,
    EntryWindowDecision,
    resolve_exit_policy,
    validate_exit_policy,
    _classify_risk_tier,
    _get_asset_class,
    EXIT_POLICY_TABLE,
    ASSET_CLASS_MAJOR,
    ASSET_CLASS_ALT,
)


class TestRiskTierClassification:
    """Tests for _classify_risk_tier logic."""
    
    def test_defensive_regime_tier_c(self):
        """Defensive regime always returns Tier C."""
        result = _classify_risk_tier("defensive", "low", True, 0.10)
        assert result == RiskTier.TIER_C
        
        result = _classify_risk_tier("defensive", "medium", True, 0.10)
        assert result == RiskTier.TIER_C
        
        result = _classify_risk_tier("halt", "low", True, 0.10)
        assert result == RiskTier.TIER_C
    
    def test_high_vol_weak_model_tier_c(self):
        """High volatility + weak model quality → Tier C."""
        result = _classify_risk_tier("normal", "high", False, 0.10)
        assert result == RiskTier.TIER_C
    
    def test_high_vol_thin_edge_tier_c(self):
        """High volatility + thin edge buffer → Tier C."""
        result = _classify_risk_tier("normal", "high", True, 0.01)
        assert result == RiskTier.TIER_C
    
    def test_low_vol_strong_model_good_edge_tier_a(self):
        """Low vol + strong model + good edge buffer → Tier A."""
        result = _classify_risk_tier("normal", "low", True, 0.06)
        assert result == RiskTier.TIER_A
    
    def test_aggressive_normal_regime_medium_vol_strong_model_tier_a(self):
        """Aggressive/normal regime + medium vol + strong model → Tier A."""
        result = _classify_risk_tier("aggressive", "medium", True, 0.03)
        assert result == RiskTier.TIER_A
        
        result = _classify_risk_tier("normal", "medium", True, 0.03)
        assert result == RiskTier.TIER_A
    
    def test_default_tier_b(self):
        """Mixed signals default to Tier B."""
        result = _classify_risk_tier("normal", "medium", False, 0.05)
        assert result == RiskTier.TIER_B


class TestAssetClass:
    """Tests for _get_asset_class."""
    
    def test_major_assets(self):
        """BTC and ETH are major assets."""
        for asset in ["BTC", "ETH", "btc", "eth"]:
            assert _get_asset_class(asset) == "major"
    
    def test_alt_assets(self):
        """SOL, XRP, DOGE are alt assets."""
        for asset in ["SOL", "XRP", "DOGE", "sol", "xrp", "doge"]:
            assert _get_asset_class(asset) == "alt"
    
    def test_unknown_asset_defaults_to_alt(self):
        """Unknown assets default to alt class."""
        assert _get_asset_class("UNKNOWN") == "alt"


class TestExitPolicyTable:
    """Tests for EXIT_POLICY_TABLE structure."""
    
    def test_all_tier_combinations_exist(self):
        """All (tier, asset_class) combinations should exist."""
        for tier in ["A", "B", "C"]:
            for asset_class in ["major", "alt"]:
                key = (tier, asset_class)
                assert key in EXIT_POLICY_TABLE, f"Missing key {key}"
    
    def test_tier_a_major_params(self):
        """Tier A major assets have tighter stops and higher TP."""
        params = EXIT_POLICY_TABLE[("A", "major")]
        assert params["tp_r_multiple"] == 1.8
        assert params["sl_edge_multiplier"] == 0.8
        assert params["trailing_enabled"] is True
        assert params["max_hold_seconds"] == 900
    
    def test_tier_c_no_trailing(self):
        """Tier C (fragile) has no trailing."""
        for asset_class in ["major", "alt"]:
            params = EXIT_POLICY_TABLE[("C", asset_class)]
            assert params["trailing_enabled"] is False
            assert params["trailing_activation_r_multiple"] is None
            assert params["trailing_giveback_pct"] is None
            assert params["max_hold_seconds"] == 360  # Shorter hold
    
    def test_alt_wider_stops(self):
        """Alt assets have wider stops than major assets for same tier."""
        tier_b_major = EXIT_POLICY_TABLE[("B", "major")]
        tier_b_alt = EXIT_POLICY_TABLE[("B", "alt")]
        assert tier_b_alt["sl_edge_multiplier"] > tier_b_major["sl_edge_multiplier"]


class TestResolveExitPolicy:
    """Tests for resolve_exit_policy function."""
    
    def test_entry_not_allowed_returns_disabled_policy(self):
        """When entry is not allowed, exit policy is disabled."""
        window_res = WindowResolution(
            allowed=False,
            reason=EntryWindowDecision.OUTSIDE_WINDOW,
            active_policy_name="btc_15m",
            bucket="10+",
            minutes_to_expiry=15.0,
            volatility_tier="medium",
        )
        result = resolve_exit_policy(window_res, "BTC", edge_pct=0.10)
        assert result.enabled is False
        assert result.risk_tier == "C"
    
    def test_enabled_policy_has_required_fields(self):
        """Enabled policy has all required fields populated."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="btc_15m",
            bucket="5-10",
            minutes_to_expiry=8.0,
            edge_pct=0.12,
            volatility_tier="low",
        )
        result = resolve_exit_policy(window_res, "BTC", edge_pct=0.12)
        assert result.enabled is True
        assert result.risk_tier in ["A", "B", "C"]
        assert result.take_profit_r_multiple is not None
        assert result.stop_loss_edge_multiplier > 0
        assert result.max_hold_seconds > 0
        assert result.auto_exit_enabled is True
    
    def test_rationale_contains_diagnostics(self):
        """Rationale contains diagnostic information."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="btc_15m",
            bucket="5-10",
            minutes_to_expiry=8.0,
            edge_pct=0.12,
            volatility_tier="low",
        )
        result = resolve_exit_policy(window_res, "BTC", edge_pct=0.12)
        assert "regime" in result.rationale
        assert "volatility_tier" in result.rationale
        assert "model_quality_good" in result.rationale
        assert "edge_buffer_pct" in result.rationale
        assert "asset_class" in result.rationale
    
    def test_uses_window_edge_if_not_provided(self):
        """Uses edge from WindowResolution if edge_pct not provided."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="btc_15m",
            bucket="5-10",
            minutes_to_expiry=8.0,
            edge_pct=0.15,
            volatility_tier="medium",
        )
        result = resolve_exit_policy(window_res, "BTC")
        assert result.rationale["edge_pct"] == 0.15
    
    def test_asset_class_affects_params(self):
        """Asset class affects exit parameters."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="default",
            bucket="5-10",
            minutes_to_expiry=8.0,
            edge_pct=0.12,
            volatility_tier="medium",
        )
        result_btc = resolve_exit_policy(window_res, "BTC", edge_pct=0.12)
        result_sol = resolve_exit_policy(window_res, "SOL", edge_pct=0.12)
        
        # Same tier, different asset class
        assert result_btc.risk_tier == result_sol.risk_tier
        # Alt assets may have different params
        assert result_btc.rationale["asset_class"] == "major"
        assert result_sol.rationale["asset_class"] == "alt"


class TestValidateExitPolicy:
    """Tests for validate_exit_policy."""
    
    def test_disabled_policy_fails(self):
        """Disabled policy fails validation."""
        ep = ExitPolicyResolution(
            enabled=False,
            risk_tier="C",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=False,
            max_hold_seconds=0,
            auto_exit_enabled=False,
            rationale={},
        )
        assert validate_exit_policy(ep) is False
    
    def test_invalid_stop_loss_fails(self):
        """Zero or negative stop loss multiplier fails."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=0.0,
            trailing_enabled=True,
            take_profit_r_multiple=1.5,
            max_hold_seconds=600,
            auto_exit_enabled=True,
            rationale={},
        )
        assert validate_exit_policy(ep) is False
    
    def test_auto_exit_disabled_fails(self):
        """Auto-exit must be enabled."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=True,
            take_profit_r_multiple=1.5,
            max_hold_seconds=600,
            auto_exit_enabled=False,
            rationale={},
        )
        assert validate_exit_policy(ep) is False
    
    def test_no_tp_or_trailing_fails(self):
        """Must have at least TP or trailing."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=False,
            take_profit_r_multiple=None,
            max_hold_seconds=600,
            auto_exit_enabled=True,
            rationale={},
        )
        assert validate_exit_policy(ep) is False
    
    def test_valid_policy_with_tp_passes(self):
        """Valid policy with TP passes."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=False,
            take_profit_r_multiple=1.5,
            max_hold_seconds=600,
            auto_exit_enabled=True,
            rationale={},
        )
        assert validate_exit_policy(ep) is True
    
    def test_valid_policy_with_trailing_passes(self):
        """Valid policy with trailing passes."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=True,
            trailing_activation_r_multiple=1.0,
            trailing_giveback_pct=15.0,
            take_profit_r_multiple=None,
            max_hold_seconds=600,
            auto_exit_enabled=True,
            rationale={},
        )
        assert validate_exit_policy(ep) is True
    
    def test_valid_policy_with_both_passes(self):
        """Valid policy with both TP and trailing passes."""
        ep = ExitPolicyResolution(
            enabled=True,
            risk_tier="A",
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=True,
            trailing_activation_r_multiple=1.0,
            trailing_giveback_pct=15.0,
            take_profit_r_multiple=1.5,
            max_hold_seconds=600,
            auto_exit_enabled=True,
            rationale={},
        )
        assert validate_exit_policy(ep) is True


class TestIntegrationScenarios:
    """Integration tests for realistic scenarios."""
    
    def test_high_confidence_btc_trade(self, monkeypatch):
        """High confidence BTC trade gets Tier A with tight stops."""
        # Mock model quality to return strong calibration
        def mock_get_calibration_store():
            class MockStore:
                def get_brier(self, model, domain):
                    return 0.15  # Below 0.20 threshold
            return MockStore()
        
        def mock_get_hit_ratio_tracker():
            return type('obj', (object,), {'stats': {'hit_ratio': 0.60}})()
        
        def mock_get_unified_regime_classifier():
            class MockClassifier:
                def get_current_state(self):
                    class MockState:
                        regime = type('obj', (object,), {'value': 'normal'})()
                    return MockState()
            return MockClassifier()
        
        monkeypatch.setattr(
            "merid.metrics.calibration.get_calibration_store",
            mock_get_calibration_store
        )
        monkeypatch.setattr(
            "merid.metrics.hit_ratio.get_hit_ratio_tracker",
            mock_get_hit_ratio_tracker
        )
        monkeypatch.setattr(
            "merid.signals.unified_regime_classifier.get_unified_regime_classifier",
            mock_get_unified_regime_classifier
        )
        
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="btc_15m",
            bucket="5-10",
            minutes_to_expiry=8.0,
            edge_pct=0.18,
            volatility_tier="low",
        )
        result = resolve_exit_policy(window_res, "BTC", edge_pct=0.18)
        assert result.enabled is True
        assert result.risk_tier == "A"
        assert result.take_profit_r_multiple == 1.8
        assert result.stop_loss_edge_multiplier == 0.8
        assert result.trailing_enabled is True
        assert result.max_hold_seconds == 900
    
    def test_fragile_regime_sol_trade(self):
        """Fragile regime SOL trade gets Tier C with no trailing."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="sol_15m",
            bucket="2-5",
            minutes_to_expiry=4.0,
            edge_pct=0.08,
            volatility_tier="high",
        )
        result = resolve_exit_policy(window_res, "SOL", edge_pct=0.08)
        assert result.enabled is True
        assert result.risk_tier == "C"
        assert result.trailing_enabled is False
        assert result.max_hold_seconds == 360
        assert result.stop_loss_edge_multiplier == 0.9
    
    def test_normal_eth_trade(self):
        """Normal ETH trade gets Tier B."""
        window_res = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name="eth_15m",
            bucket="5-10",
            minutes_to_expiry=7.0,
            edge_pct=0.12,
            volatility_tier="medium",
        )
        result = resolve_exit_policy(window_res, "ETH", edge_pct=0.12)
        assert result.enabled is True
        assert result.risk_tier == "B"
        assert result.take_profit_r_multiple == 1.4
        assert result.stop_loss_edge_multiplier == 1.0
        assert result.trailing_enabled is True
        assert result.max_hold_seconds == 600


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
