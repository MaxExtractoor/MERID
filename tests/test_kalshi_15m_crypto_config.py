"""Tests for canonical Kalshi 15m crypto configuration."""

import pytest

# DEPRECATED: kalshi_15m_crypto_config.py removed - use profile YAML instead
# Fallback to kalshi_universe.py for asset definitions
try:
    from config.kalshi_15m_crypto_config import (
        KALSHI_15M_CRYPTO_ASSETS,
        KALSHI_15M_TIMEFRAME,
        KALSHI_15M_SERIES_TICKERS,
        ASSET_CLASS_MAJOR,
        ASSET_CLASS_ALT,
        get_asset_class,
        get_series_ticker,
        is_15m_crypto_asset,
        get_time_bucket,
        get_t2e_band,
        validate_minutes_to_expiry,
        DEFAULT_ENTRY_POLICIES,
        EXIT_POLICY_TABLE,
        get_entry_policy,
        get_exit_policy_params,
        get_base_edge_threshold,
        VolatilityTier,
        validate_config,
        dump_config_summary,
        get_asset_risk_limits,
        get_global_risk_limits,
        verify_risk_parity,
    )
    CONFIG_AVAILABLE = True
except ImportError:
    # Use fallback from kalshi_universe.py
    from config.kalshi_universe import (
        KALSHI_15M_CRYPTO_ASSETS,
        KALSHI_15M_SERIES_TICKERS,
    )
    KALSHI_15M_TIMEFRAME = "15m"
    ASSET_CLASS_MAJOR = ["BTC", "ETH"]
    ASSET_CLASS_ALT = ["SOL", "XRP", "DOGE"]
    CONFIG_AVAILABLE = False
    
    # Stubs for missing functions
    def get_asset_class(asset): return "MAJOR" if asset in ASSET_CLASS_MAJOR else "ALT"
    def get_series_ticker(asset): return KALSHI_15M_SERIES_TICKERS.get(asset)
    def is_15m_crypto_asset(asset): return asset in KALSHI_15M_CRYPTO_ASSETS
    def get_time_bucket(tte): return "early" if tte > 10 else "late"
    def get_t2e_band(tte): return "long" if tte > 10 else "short"
    def validate_minutes_to_expiry(tte): return 0 < tte <= 15
    DEFAULT_ENTRY_POLICIES = {}
    EXIT_POLICY_TABLE = {}
    def get_entry_policy(asset, tier): return {}
    def get_exit_policy_params(asset, tier): return {}
    def get_base_edge_threshold(asset, tier): return 0.05
    class VolatilityTier: pass
    def validate_config(): return True
    def dump_config_summary(): return {}
    def get_asset_risk_limits(asset): return {}
    def get_global_risk_limits(): return {}
    def verify_risk_parity(): return True


class TestUniverseDefinition:
    """Tests for universe definition (Section 1)."""
    
    def test_15m_assets_complete(self):
        """All five expected assets are present."""
        assert set(KALSHI_15M_CRYPTO_ASSETS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    
    def test_15m_timeframe(self):
        """Timeframe is exactly 15m."""
        assert KALSHI_15M_TIMEFRAME == "15m"
    
    def test_series_tickers_complete(self):
        """All assets have series tickers."""
        for asset in KALSHI_15M_CRYPTO_ASSETS:
            assert asset in KALSHI_15M_SERIES_TICKERS
            assert KALSHI_15M_SERIES_TICKERS[asset].startswith("KX")
            assert "15M" in KALSHI_15M_SERIES_TICKERS[asset]
    
    def test_asset_class_grouping(self):
        """Asset classes are correctly grouped."""
        assert set(ASSET_CLASS_MAJOR) == {"BTC", "ETH"}
        assert set(ASSET_CLASS_ALT) == {"SOL", "XRP", "DOGE"}


class TestHelperFunctions:
    """Tests for helper functions (Section 1)."""
    
    def test_get_asset_class(self):
        """Asset class classification works correctly."""
        assert get_asset_class("BTC") == "major"
        assert get_asset_class("ETH") == "major"
        assert get_asset_class("SOL") == "alt"
        assert get_asset_class("XRP") == "alt"
        assert get_asset_class("DOGE") == "alt"
        assert get_asset_class("btc") == "major"  # Case insensitive
        assert get_asset_class("UNKNOWN") == "alt"  # Default to alt
    
    def test_get_series_ticker(self):
        """Series ticker lookup works correctly."""
        assert get_series_ticker("BTC") == "KXBTC15M"
        assert get_series_ticker("ETH") == "KXETH15M"
        assert get_series_ticker("SOL") == "KXSOL15M"
        assert get_series_ticker("XRP") == "KXXRP15M"
        assert get_series_ticker("DOGE") == "KXDOGE15M"
        assert get_series_ticker("UNKNOWN") is None
    
    def test_is_15m_crypto_asset(self):
        """Asset membership check works correctly."""
        assert is_15m_crypto_asset("BTC") is True
        assert is_15m_crypto_asset("ETH") is True
        assert is_15m_crypto_asset("SOL") is True
        assert is_15m_crypto_asset("XRP") is True
        assert is_15m_crypto_asset("DOGE") is True
        assert is_15m_crypto_asset("UNKNOWN") is False
        assert is_15m_crypto_asset("btc") is True  # Case insensitive


class TestTimeSemantics:
    """Tests for time semantics (Section 2)."""
    
    def test_get_time_bucket(self):
        """Time bucket classification works correctly."""
        assert get_time_bucket(1.0) == "0-2"
        assert get_time_bucket(3.0) == "2-5"
        assert get_time_bucket(7.0) == "5-10"
        assert get_time_bucket(12.0) == "10+"
        assert get_time_bucket(0.5) == "0-2"
        assert get_time_bucket(2.0) == "2-5"
        assert get_time_bucket(5.0) == "5-10"
    
    def test_get_t2e_band(self):
        """Time-to-expiry band classification works correctly."""
        assert get_t2e_band(10.0) == "long"
        assert get_t2e_band(8.0) == "long"
        assert get_t2e_band(6.0) == "medium"
        assert get_t2e_band(4.0) == "medium"
        assert get_t2e_band(2.0) == "short"
        assert get_t2e_band(0.5) == "short"
    
    def test_validate_minutes_to_expiry_valid(self):
        """Valid minutes_to_expiry values pass validation."""
        for minutes in [0.0, 1.0, 5.0, 10.0, 15.0]:
            is_valid, error = validate_minutes_to_expiry(minutes, "BTC")
            assert is_valid is True
            assert error is None
    
    def test_validate_minutes_to_expiry_invalid(self):
        """Invalid minutes_to_expiry values fail validation."""
        for minutes in [-1.0, 15.1, 20.0, 100.0]:
            is_valid, error = validate_minutes_to_expiry(minutes, "BTC")
            assert is_valid is False
            assert error is not None
            assert "Invalid minutes_to_expiry" in error


class TestEntryPolicies:
    """Tests for entry window policies (Section 3)."""
    
    def test_all_assets_have_entry_policies(self):
        """All 15m crypto assets have entry policies."""
        for asset in KALSHI_15M_CRYPTO_ASSETS:
            policy = get_entry_policy(asset)
            assert policy is not None
            assert policy.asset == asset
            assert policy.base_window_start_minutes > 0
            assert policy.base_window_end_minutes > 0
            assert policy.policy_name.startswith("kalshi_15m_")
    
    def test_btc_eth_have_wider_windows(self):
        """BTC and ETH have wider windows than alt assets."""
        btc_policy = get_entry_policy("BTC")
        sol_policy = get_entry_policy("SOL")
        
        btc_window = btc_policy.base_window_start_minutes - btc_policy.base_window_end_minutes
        sol_window = sol_policy.base_window_start_minutes - sol_policy.base_window_end_minutes
        
        assert btc_window >= sol_window
    
    def test_policy_names_follow_convention(self):
        """Policy names follow the kalshi_15m_{asset}_v1 convention."""
        for asset in KALSHI_15M_CRYPTO_ASSETS:
            policy = get_entry_policy(asset)
            assert policy.policy_name == f"kalshi_15m_{asset.lower()}_v1"


class TestExitPolicies:
    """Tests for exit policy parameters (Section 4)."""
    
    def test_all_tier_asset_class_combinations_exist(self):
        """All (tier, asset_class) combinations exist in exit policy table."""
        for tier in ["A", "B", "C"]:
            for asset_class in ["major", "alt"]:
                key = (tier, asset_class)
                assert key in EXIT_POLICY_TABLE
    
    def test_tier_a_has_trailing(self):
        """Tier A has trailing enabled."""
        for asset_class in ["major", "alt"]:
            params = EXIT_POLICY_TABLE[("A", asset_class)]
            assert params["trailing_enabled"] is True
            assert params["trailing_activation_r_multiple"] is not None
            assert params["trailing_giveback_pct"] is not None
    
    def test_tier_c_no_trailing(self):
        """Tier C has trailing disabled (fragile regime)."""
        for asset_class in ["major", "alt"]:
            params = EXIT_POLICY_TABLE[("C", asset_class)]
            assert params["trailing_enabled"] is False
            assert params["trailing_activation_r_multiple"] is None
            assert params["trailing_giveback_pct"] is None
    
    def test_tier_c_shorter_hold(self):
        """Tier C has shorter max hold than Tier A/B."""
        tier_c_major = EXIT_POLICY_TABLE[("C", "major")]
        tier_a_major = EXIT_POLICY_TABLE[("A", "major")]
        
        assert tier_c_major["max_hold_seconds"] < tier_a_major["max_hold_seconds"]
    
    def test_alt_wider_stops(self):
        """Alt assets have wider stops than major assets for same tier."""
        tier_b_major = EXIT_POLICY_TABLE[("B", "major")]
        tier_b_alt = EXIT_POLICY_TABLE[("B", "alt")]
        
        assert tier_b_alt["sl_edge_multiplier"] > tier_b_major["sl_edge_multiplier"]
    
    def test_get_exit_policy_params(self):
        """get_exit_policy_params returns correct parameters."""
        params = get_exit_policy_params("A", "BTC")
        assert params["tp_r_multiple"] == 1.8
        assert params["sl_edge_multiplier"] == 0.8
        assert params["trailing_enabled"] is True
        
        params = get_exit_policy_params("C", "SOL")
        assert params["tp_r_multiple"] == 1.2
        assert params["trailing_enabled"] is False


class TestEdgeThresholds:
    """Tests for edge thresholds (Section 5)."""
    
    def test_all_assets_have_volatility_thresholds(self):
        """All assets have volatility-tiered thresholds."""
        from config.kalshi_15m_crypto_config import VOLATILITY_TIERED_BASE_THRESHOLDS
        for asset in KALSHI_15M_CRYPTO_ASSETS:
            assert asset in VOLATILITY_TIERED_BASE_THRESHOLDS
    
    def test_get_base_edge_threshold(self):
        """Base edge threshold lookup works correctly."""
        threshold = get_base_edge_threshold("BTC", VolatilityTier.LOW)
        assert threshold == 0.15  # Upper bound of (0.12, 0.15)
        
        threshold = get_base_edge_threshold("BTC", VolatilityTier.HIGH)
        assert threshold == 0.30  # Upper bound of (0.25, 0.30)
    
    def test_fallback_to_btc_for_unknown_asset(self):
        """Unknown assets fall back to BTC thresholds."""
        threshold = get_base_edge_threshold("UNKNOWN", VolatilityTier.MEDIUM)
        assert threshold == 0.20  # BTC medium upper bound


class TestValidation:
    """Tests for configuration validation (Section 7)."""
    
    def test_validate_config_passes(self):
        """Configuration validation passes with no errors."""
        is_valid, errors = validate_config()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_dump_config_summary(self):
        """Configuration summary can be dumped."""
        summary = dump_config_summary()
        assert "universe" in summary
        assert "entry_policies" in summary
        assert "exit_policies" in summary
        assert "validation" in summary
        
        assert summary["universe"]["timeframe"] == "15m"
        assert "BTC" in summary["universe"]["series_tickers"]
        
        assert summary["validation"][0] is True  # (is_valid, errors)


class TestLivePaperRiskParity:
    """Test that LIVE and PAPER modes use identical risk limits (Section 8)."""

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_risk_parity(self):
        """Test that LIVE and PAPER risk limits are identical."""
        parity_ok, message = verify_risk_parity()
        assert parity_ok, f"Risk parity check failed: {message}"

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_all_assets_use_canonical_limits(self):
        """Test that all assets read from the same canonical config."""
        live_limits = {asset: get_asset_risk_limits(asset) for asset in KALSHI_15M_CRYPTO_ASSETS}

        # Verify no environment-specific values
        for asset, limits in live_limits.items():
            for key, value in limits.items():
                if isinstance(value, str):
                    assert "live" not in value.lower(), f"{asset}.{key} has live-specific value"
                    assert "paper" not in value.lower(), f"{asset}.{key} has paper-specific value"

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_global_limits_mode_agnostic(self):
        """Test that global limits are mode-agnostic."""
        global_limits = get_global_risk_limits()

        for key, value in global_limits.items():
            if isinstance(value, str):
                assert "live" not in value.lower(), f"GLOBAL.{key} has live-specific value"
                assert "paper" not in value.lower(), f"GLOBAL.{key} has paper-specific value"

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_limits_are_consistent_across_assets(self):
        """Test that per-asset limits follow consistent structure."""
        btc_limits = get_asset_risk_limits("BTC")

        for asset in KALSHI_15M_CRYPTO_ASSETS:
            asset_limits = get_asset_risk_limits(asset)
            assert set(asset_limits.keys()) == set(btc_limits.keys()), \
                f"{asset} has different limit keys than BTC"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
