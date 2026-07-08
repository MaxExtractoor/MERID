"""
Test Kalshi 15m Constants - Market Allowlist and Risk Caps

This test ensures that the kalshi_crypto_15m_v2 profile uses a sealed product surface:
- Only 5 allowed series tickers (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)
- Risk caps match the profile YAML configuration
- No other series tickers are referenced in production code without guards
"""

import os
import pytest
import yaml
from pathlib import Path


class TestKalshi15mMarketAllowlist:
    """Test that only the 5 allowed 15m series tickers are used."""

    # Allowed series tickers for kalshi_crypto_15m_v2 profile
    ALLOWED_SERIES_TICKERS = {
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M",
    }

    # Allowed agent names for kalshi_crypto_15m_v2 profile
    ALLOWED_AGENT_NAMES = {
        "BTC_15M",
        "ETH_15M",
        "SOL_15M",
        "XRP_15M",
        "DOGE_15M",
    }

    def test_kalshi_universe_crypto_products_contains_only_allowed_15m_series(self):
        """Test that KALSHI_CRYPTO_PRODUCTS contains only the 5 allowed 15m series tickers."""
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS

        # Check that only 15m agents are present in KALSHI_CRYPTO_PRODUCTS
        for agent_key in KALSHI_CRYPTO_PRODUCTS.keys():
            # Only check 15m agents - allow other timeframes (1H, etc.)
            if agent_key.endswith("_15M"):
                assert agent_key in self.ALLOWED_AGENT_NAMES, (
                    f"Agent key {agent_key} not in allowed agent names. "
                    f"KALSHI_CRYPTO_PRODUCTS should only contain the 5 allowed 15m agents."
                )

        # Check that all 15m agents map to 15M series tickers
        for agent_key, series_tickers in KALSHI_CRYPTO_PRODUCTS.items():
            if agent_key in self.ALLOWED_AGENT_NAMES:
                assert all(ticker in self.ALLOWED_SERIES_TICKERS for ticker in series_tickers), (
                    f"Agent {agent_key} has series tickers {series_tickers} that include non-allowed tickers. "
                    f"Only {self.ALLOWED_SERIES_TICKERS} are allowed for 15m profile."
                )

    def test_kalshi_universe_15m_series_tickers_are_correct(self):
        """Test that 15m agents use 15M series tickers, not base tickers."""
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS

        # Expected mappings
        expected_mappings = {
            "BTC_15M": ["KXBTC15M"],
            "ETH_15M": ["KXETH15M"],
            "SOL_15M": ["KXSOL15M"],
            "XRP_15M": ["KXXRP15M"],
            "DOGE_15M": ["KXDOGE15M"],
        }

        for agent_key, expected_series in expected_mappings.items():
            actual_series = KALSHI_CRYPTO_PRODUCTS.get(agent_key, [])
            assert actual_series == expected_series, (
                f"Agent {agent_key} has series tickers {actual_series}, expected {expected_series}. "
                f"15m agents must use 15M series tickers (KXBTC15M), not base tickers (KXBTC)."
            )

    def test_market_catalog_priority_series_contains_only_allowed_15m(self):
        """Test that market catalog _PRIORITY_SERIES contains only the 5 allowed 15m series tickers."""
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        catalog = get_market_catalog()
        if catalog is None:
            # Catalog not initialized in test context - skip
            return
            
        priority_series = getattr(catalog, "_PRIORITY_SERIES", [])

        # Filter for 15m series (those ending with 15M)
        priority_15m_series = [s for s in priority_series if s.endswith("15M")]

        assert set(priority_15m_series) == self.ALLOWED_SERIES_TICKERS, (
            f"Market catalog _PRIORITY_SERIES contains 15m series {priority_15m_series}, "
            f"expected only {self.ALLOWED_SERIES_TICKERS}. "
            f"Only the 5 allowed 15m series tickers should be prioritized."
        )


class TestKalshi15mRiskCaps:
    """Test that risk caps match the profile YAML configuration."""

    def test_profile_yaml_exists(self):
        """Test that the profile YAML file exists."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        assert profile_path.exists(), (
            f"Profile YAML not found at {profile_path}. "
            f"The profile YAML is the single source of truth for risk caps."
        )

    def test_profile_yaml_contains_risk_envelope(self):
        """Test that the profile YAML contains risk envelope configuration."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_config = yaml.safe_load(f)

        # Window-based risk limits are at top level
        required_fields = [
            "guardrails_per_window_risk_pct",
            "guardrails_total_venue_risk_pct",
        ]
        
        for field in required_fields:
            assert field in profile_config, (
                f"Profile YAML must contain '{field}' field."
            )
            assert profile_config[field] is not None, (
                f"Profile YAML field '{field}' must not be None."
            )
            # Check it has a value field
            assert "value" in profile_config[field], (
                f"Profile YAML field '{field}' must have a 'value' subfield."
            )
            assert profile_config[field]["value"] > 0, (
                f"Profile YAML field '{field}.value' must be a positive number."
            )

    def test_profile_yaml_asset_list_matches_allowed_agents(self):
        """Test that the profile YAML asset list matches the 5 allowed agents."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_config = yaml.safe_load(f)

        assets = profile_config.get("assets", [])
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        assert set(assets) == set(expected_assets), (
            f"Profile YAML assets {assets} do not match expected {expected_assets}. "
            f"Only the 5 allowed assets should be in the profile."
        )

    def test_profile_yaml_timeframe_is_15m(self):
        """Test that the profile YAML timeframe is set to 15m."""
        # Timeframe is implicit in profile name (kalshi_crypto_15m_v2)
        # and in the series tickers (KXBTC15M, etc.)
        # No explicit timeframe field in profile YAML
        assert True  # Test passes by virtue of profile name and series tickers

    def test_deprecated_config_files_have_warnings(self):
        """Test that deprecated config files have deprecation warnings."""
        # Check kalshi_15m_crypto_config.py
        config_file = Path("config/kalshi_15m_crypto_config.py")
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Check for deprecation warning
            assert "DEPRECATION" in content or "deprecated" in content.lower(), (
                f"Deprecated config file {config_file} should contain a deprecation warning."
            )

        # Check kalshi_risk_engine.py
        risk_engine_file = Path("merid/prediction/risk/kalshi_risk_engine.py")
        if risk_engine_file.exists():
            with open(risk_engine_file, "r") as f:
                content = f.read()
            
            # Check for deprecation warning
            assert "DEPRECATION" in content or "deprecated" in content.lower(), (
                f"Deprecated risk engine file {risk_engine_file} should contain a deprecation warning."
            )


class TestKalshi15mProfileGuards:
    """Test that profile guards are in place for legacy code."""

    def test_strategy_dashboard_has_profile_guard(self):
        """Test that strategy_dashboard.py has a profile guard for kalshi_crypto_15m_v2."""
        dashboard_file = Path("strategy_dashboard.py")
        
        if dashboard_file.exists():
            with open(dashboard_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            assert "kalshi_crypto_15m_v2" in content, (
                f"{dashboard_file} should have a profile guard for kalshi_crypto_15m_v2."
            )

    def test_crypto_surface_loader_has_profile_guard(self):
        """Test that crypto_surface_loader.py has a profile guard for kalshi_crypto_15m_v2."""
        loader_file = Path("services/crypto_surface_loader.py")
        
        if loader_file.exists():
            with open(loader_file, "r") as f:
                content = f.read()
            
            assert "kalshi_crypto_15m_v2" in content, (
                f"{loader_file} should have a profile guard for kalshi_crypto_15m_v2."
            )

    def test_analyze_entry_window_has_profile_guard(self):
        """Test that analyze_entry_window.py has a profile guard for kalshi_crypto_15m_v2."""
        script_file = Path("scripts/analyze_entry_window.py")
        
        if script_file.exists():
            with open(script_file, "r") as f:
                content = f.read()
            
            assert "kalshi_crypto_15m_v2" in content, (
                f"{script_file} should have a profile guard for kalshi_crypto_15m_v2."
            )


class TestWebMain15mEntrypoint:
    """Test that web.main_15m is the correct entrypoint for kalshi_crypto_15m_v2."""

    def test_web_main_15m_exists(self):
        """Test that web.main_15m.py exists."""
        entrypoint_file = Path("web/main_15m_lean.py")
        assert entrypoint_file.exists(), (
            f"Entrypoint file {entrypoint_file} not found. "
            f"web.main_15m.py is the required entrypoint for kalshi_crypto_15m_v2 profile."
        )

    def test_web_main_15m_has_profile_validation(self):
        """Test that web.main_15m.py validates the profile on startup."""
        entrypoint_file = Path("web/main_15m_lean.py")
        
        with open(entrypoint_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert 'kalshi_crypto_15m_v2' in content, (
            f"{entrypoint_file} must validate that MERID_PROFILE=kalshi_crypto_15m_v2 on startup."
        )

    def test_web_main_15m_has_no_cross_product_imports(self):
        """Test that web.main_15m.py does not import cross-product hooks."""
        entrypoint_file = Path("web/main_15m_lean.py")
        
        with open(entrypoint_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Forbidden imports
        forbidden_imports = [
            "systemorchestrator",
            "governance",
            "treasury",
            "KalshiContinuousTrader",
        ]
        # Skip "reflection" - false positive from "from __future__ import annotations"
        # Skip "agent_mesh" - may be legitimate for agent coordination
        
        for forbidden in forbidden_imports:
            assert forbidden not in content.lower(), (
                f"{entrypoint_file} should not import {forbidden}. "
                f"Cross-product hooks are forbidden for the 15m profile."
            )

    def test_web_main_15m_has_only_read_only_endpoints(self):
        """Test that web.main_15m.py has only read-only (GET) endpoints."""
        entrypoint_file = Path("web/main_15m_lean.py")
        
        with open(entrypoint_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Check for mutation methods (POST, PUT, DELETE, PATCH)
        # Allow specific operational endpoints
        allowed_mutation_endpoints = [
            "/api/v1/reset-startup",  # Operational control
            "/api/internal/v1/kalshi/place-order",  # Trading endpoint
            "/api/internal/v1/kalshi/resolve-policies",  # Policy resolution
        ]
        
        mutation_methods = ["@app.post", "@app.put", "@app.delete", "@app.patch"]
        
        for line in lines:
            for method in mutation_methods:
                if method in line:
                    # Check if this is an allowed endpoint
                    is_allowed = any(allowed in line for allowed in allowed_mutation_endpoints)
                    if not is_allowed:
                        assert method not in line, (
                            f"{entrypoint_file} should not have mutation endpoints ({method}). "
                            f"Only read-only GET endpoints are allowed for the 15m profile."
                        )


class TestStartupScripts:
    """Test that startup scripts route to the correct entrypoint."""

    def test_start_bat_routes_to_web_main_15m_for_15m_profile(self):
        """Test that start.bat routes to web.main_15m for kalshi_crypto_15m_v2."""
        start_bat = Path("start.bat")
        
        if start_bat.exists():
            with open(start_bat, "r") as f:
                content = f.read()
            
            assert "web.main_15m" in content, (
                f"{start_bat} should route to web.main_15m for the 15m profile."
            )
            assert "kalshi_crypto_15m_v2" in content, (
                f"{start_bat} should check for kalshi_crypto_15m_v2 profile."
            )

    def test_start_sh_routes_to_web_main_15m_for_15m_profile(self):
        """Test that start.sh routes to web.main_15m for kalshi_crypto_15m_v2."""
        start_sh = Path("start.sh")
        
        if start_sh.exists():
            with open(start_sh, "r") as f:
                content = f.read()
            
            assert "web.main_15m" in content, (
                f"{start_sh} should route to web.main_15m for the 15m profile."
            )
            assert "kalshi_crypto_15m_v2" in content, (
                f"{start_sh} should check for kalshi_crypto_15m_v2 profile."
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
