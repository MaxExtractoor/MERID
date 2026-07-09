"""
Tests for diagnostic script fixes.

Tests that the diagnostic script correctly identifies configuration issues
and that the fixes are properly applied across the stack.
"""

import pytest
from pathlib import Path
import yaml


class TestDiagnosticScriptYAMLPathResolution:
    """Test that diagnostic script correctly resolves nested YAML paths."""
    
    @pytest.fixture
    def profile_yaml_path(self):
        """Path to the profile YAML file."""
        return Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
    
    @pytest.fixture
    def profile_config(self, profile_yaml_path):
        """Load the profile YAML."""
        with open(profile_yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def test_guardrails_per_window_risk_pct_path(self, profile_config):
        """Test that guardrails_per_window_risk_pct is at top level, not nested."""
        # Should be at top level
        assert 'guardrails_per_window_risk_pct' in profile_config
        value = profile_config['guardrails_per_window_risk_pct']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.03
    
    def test_guardrails_total_venue_risk_pct_path(self, profile_config):
        """Test that guardrails_total_venue_risk_pct is at top level, not nested."""
        assert 'guardrails_total_venue_risk_pct' in profile_config
        value = profile_config['guardrails_total_venue_risk_pct']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.05
    
    def test_venue_max_total_notional_pct_path(self, profile_config):
        """Test that venue.max_total_notional_pct is nested under venue."""
        assert 'venue' in profile_config
        venue = profile_config['venue']
        assert 'max_total_notional_pct' in venue
        value = venue['max_total_notional_pct']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.15
    
    def test_kelly_hard_cap_path(self, profile_config):
        """Test that kelly.kelly_hard_cap is nested under kelly."""
        assert 'kelly' in profile_config
        kelly = profile_config['kelly']
        assert 'kelly_hard_cap' in kelly
        value = kelly['kelly_hard_cap']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.02
    
    def test_kelly_global_notional_cap_pct_path(self, profile_config):
        """Test that kelly.kelly_global_notional_cap_pct is nested under kelly."""
        assert 'kelly' in profile_config
        kelly = profile_config['kelly']
        assert 'kelly_global_notional_cap_pct' in kelly
        value = kelly['kelly_global_notional_cap_pct']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.02
    
    def test_agent_defaults_max_notional_pct_path(self, profile_config):
        """Test that agent_defaults.max_notional_pct is nested under agent_defaults."""
        assert 'agent_defaults' in profile_config
        agent_defaults = profile_config['agent_defaults']
        assert 'max_notional_pct' in agent_defaults
        value = agent_defaults['max_notional_pct']
        if isinstance(value, dict):
            value = value.get('value')
        assert value == 0.03
    
    def test_velocity_thresholds_path(self, profile_config):
        """Test that velocity_thresholds is a top-level section, not nested in velocity_model."""
        # Should be at top level, not in velocity_model.coefficients
        assert 'velocity_thresholds' in profile_config
        velocity_thresholds = profile_config['velocity_thresholds']
        
        # Check all 5 assets
        expected = {
            'BTC': 0.00015,
            'ETH': 0.00015,
            'SOL': 0.000225,
            'XRP': 0.000225,
            'DOGE': 0.0003,
        }
        
        for asset, expected_value in expected.items():
            assert asset in velocity_thresholds
            assert velocity_thresholds[asset] == expected_value


class TestDiagnosticScriptImportPaths:
    """Test that diagnostic script uses correct import paths."""
    
    def test_market_state_store_import(self):
        """Test that market state store is imported from market_state.py, not market_state_store.py."""
        # This should not raise ImportError
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        assert KalshiMarketStateStore is not None
    
    def test_websocket_bridge_exists(self):
        """Test that ws_bridge.py exists (the production WebSocket implementation)."""
        ws_bridge_path = Path("c:/Dev/MERID/merid/event_venues/kalshi/ws_bridge.py")
        assert ws_bridge_path.exists()
    
    def test_legacy_main_py_renamed(self):
        """Test that legacy main.py has been renamed to prevent contamination."""
        main_path = Path("c:/Dev/MERID/web/main.py")
        main_legacy_path = Path("c:/Dev/MERID/web/main.py.legacy")
        
        # Original main.py should not exist
        assert not main_path.exists()
        
        # Legacy version should exist
        assert main_legacy_path.exists()
    
    def test_production_main_15m_lean_exists(self):
        """Test that production main_15m_lean.py exists."""
        main_15m_path = Path("c:/Dev/MERID/web/main_15m_lean.py")
        assert main_15m_path.exists()


class TestAgentGridConfiguration:
    """Test that agent grid configuration matches profile YAML."""
    
    def test_max_orders_per_15m_window_value(self):
        """Test that max_orders_per_15m_window is 12, not 5."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        # Get the default value from the dataclass field
        max_orders = LeanAgentConfig.__dataclass_fields__['max_orders_per_15m_window'].default
        assert max_orders == 12, f"Expected 12, got {max_orders}"
    
    def test_velocity_thresholds_match_profile(self):
        """Test that agent grid velocity thresholds match profile YAML."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        expected = {
            'velocity_threshold_btc': 0.00015,
            'velocity_threshold_eth': 0.00015,
            'velocity_threshold_sol': 0.000225,
            'velocity_threshold_xrp': 0.000225,
            'velocity_threshold_doge': 0.0003,
        }
        
        for attr, expected_value in expected.items():
            actual = LeanAgentConfig.__dataclass_fields__[attr].default
            assert actual == expected_value, f"{attr}: expected {expected_value}, got {actual}"


class TestRiskEnvelopeConsistency:
    """Test that risk envelope correctly reads from profile YAML."""
    
    def test_per_trade_risk_pct_uniform(self):
        """Test that per_trade_risk_pct is uniform 3% for all bankroll sizes."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        # Test with different bankroll sizes
        for bankroll in [50.0, 100.0, 500.0, 1000.0, 5000.0]:
            envelope = KalshiCrypto15mRiskEnvelope(
                live_bankroll_usd=bankroll,
                profile_capital_usd=1000.0,
                max_cycle_risk_pct=0.05,
                max_total_notional_usd=bankroll * 0.15,
                max_single_order_notional_usd=bankroll * 0.03,
                asset_max_notional_usd={},
                asset_depth_thresholds={},
                agent_max_notional_usd=bankroll * 0.03,
                agent_max_orders_per_window=12,
                agent_max_yes_position=5,
                agent_max_no_position=5,
                guardrails_per_window_risk_pct=0.03,
                guardrails_total_venue_risk_pct=0.05,
                per_agent_window_limit_usd=bankroll * 0.03,
                total_venue_window_limit_usd=bankroll * 0.05,
                window_start_ts=0.0,
                agent_window_exposure_usd={},
                total_window_exposure_usd=0.0,
                daily_loss_enabled=False,
                max_daily_loss_usd=float('inf'),
                drawdown_halt_pct=0.20,
                drawdown_unwind_pct=0.25,
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
                correlation_threshold=0.5,
                correlation_multiplier=1.0,
                max_concurrent_trades=8,
            )
            assert envelope.get_per_trade_risk_pct() == 0.03


class TestUnifiedSizingConsistency:
    """Test that unified sizing correctly reads from profile."""
    
    def test_bankroll_cap_pct_reads_from_profile(self):
        """Test that _get_bankroll_cap_pct reads from venue.bankroll_cap_pct."""
        # This test verifies the function exists and has the correct docstring
        from merid.prediction.unified_sizing import _get_bankroll_cap_pct
        
        # Check that the function mentions the correct YAML path
        docstring = _get_bankroll_cap_pct.__doc__
        assert 'venue.bankroll_cap_pct' in docstring
    
    def test_per_trade_risk_pct_reads_from_profile(self):
        """Test that _get_per_trade_risk_pct reads from guardrails.per_trade_risk_pct."""
        from merid.prediction.unified_sizing import _get_per_trade_risk_pct
        
        docstring = _get_per_trade_risk_pct.__doc__
        assert 'guardrails.per_trade_risk_pct' in docstring
    
    def test_max_single_order_pct_reads_from_profile(self):
        """Test that _get_max_single_order_pct reads from venue.max_single_order_pct."""
        from merid.prediction.unified_sizing import _get_max_single_order_pct
        
        docstring = _get_max_single_order_pct.__doc__
        assert 'venue.max_single_order_pct' in docstring
    
    def test_per_asset_risk_pct_reads_from_profile(self):
        """Test that _get_per_asset_risk_pct reads from per-asset max_notional_pct."""
        from merid.prediction.unified_sizing import _get_per_asset_risk_pct
        
        docstring = _get_per_asset_risk_pct.__doc__
        assert 'max_notional_pct' in docstring


class TestWindowTrackingImplementation:
    """Test that window-based risk tracking is correctly implemented."""
    
    def test_window_tracking_state_at_module_level(self):
        """Test that window tracking state is at module level for consistency."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _WINDOW_TRACKING_STATE
        
        # Should be a dict with the expected keys
        assert isinstance(_WINDOW_TRACKING_STATE, dict)
        assert 'window_start_ts' in _WINDOW_TRACKING_STATE
        assert 'agent_exposure_usd' in _WINDOW_TRACKING_STATE
        assert 'total_exposure_usd' in _WINDOW_TRACKING_STATE
    
    def test_check_window_limit_exists(self):
        """Test that check_window_limit method exists in risk envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        # Create a minimal envelope
        envelope = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=1000.0,
            profile_capital_usd=1000.0,
            max_cycle_risk_pct=0.05,
            max_total_notional_usd=150.0,
            max_single_order_notional_usd=30.0,
            asset_max_notional_usd={},
            asset_depth_thresholds={},
            agent_max_notional_usd=30.0,
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            guardrails_per_window_risk_pct=0.03,
            guardrails_total_venue_risk_pct=0.05,
            per_agent_window_limit_usd=30.0,
            total_venue_window_limit_usd=50.0,
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            daily_loss_enabled=False,
            max_daily_loss_usd=float('inf'),
            drawdown_halt_pct=0.20,
            drawdown_unwind_pct=0.25,
            peak_equity_usd=1000.0,
            current_equity_usd=1000.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            max_concurrent_trades=8,
        )
        
        # Should have check_window_limit method
        assert hasattr(envelope, 'check_window_limit')
        assert callable(envelope.check_window_limit)
    
    def test_window_limit_check_in_unified_sizing(self):
        """Test that unified_sizing calls check_window_limit."""
        # This is verified by checking the source code
        from merid.prediction import unified_sizing
        import inspect
        
        source = inspect.getsource(unified_sizing)
        assert 'check_window_limit' in source


class TestAssetCoverage:
    """Test that all 5 crypto assets are consistently covered."""
    
    @pytest.fixture
    def profile_yaml_path(self):
        """Path to the profile YAML file."""
        return Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
    
    @pytest.fixture
    def profile_config(self, profile_yaml_path):
        """Load the profile YAML."""
        with open(profile_yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def test_all_5_assets_in_profile(self, profile_config):
        """Test that all 5 assets are defined in profile YAML."""
        assert 'assets' in profile_config
        assets = profile_config['assets']
        
        required_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        for asset in required_assets:
            assert asset in assets, f"Asset {asset} missing from profile"
    
    def test_all_5_assets_have_max_notional_pct(self, profile_config):
        """Test that all 5 assets have max_notional_pct defined."""
        assets = profile_config['assets']
        
        required_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        for asset in required_assets:
            asset_config = assets[asset]
            assert 'max_notional_pct' in asset_config
            value = asset_config['max_notional_pct']
            if isinstance(value, dict):
                value = value.get('value')
            assert value == 0.03, f"{asset} max_notional_pct should be 0.03, got {value}"
    
    def test_all_5_assets_have_velocity_thresholds(self, profile_config):
        """Test that all 5 assets have velocity thresholds defined."""
        velocity_thresholds = profile_config['velocity_thresholds']
        
        required_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        for asset in required_assets:
            assert asset in velocity_thresholds, f"Asset {asset} missing from velocity_thresholds"
    
    def test_all_5_assets_in_agent_grid(self):
        """Test that agent grid has velocity thresholds for all 5 assets."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        required_attrs = [
            'velocity_threshold_btc',
            'velocity_threshold_eth',
            'velocity_threshold_sol',
            'velocity_threshold_xrp',
            'velocity_threshold_doge',
        ]
        
        for attr in required_attrs:
            assert attr in LeanAgentConfig.__dataclass_fields__


class Test50cSweetSpotThreshold:
    """Test that the 50c sweet spot threshold is correctly implemented (2026-07-08)."""

    def test_deep_otm_expensive_cents_value(self):
        """Test that DEEP_OTM_EXPENSIVE_CENTS is 50 (2026-07-08 update)."""
        from merid.event_venues.kalshi.risk_parameters import DEEP_OTM_EXPENSIVE_CENTS

        assert DEEP_OTM_EXPENSIVE_CENTS == 50

    def test_50c_threshold_in_profile_yaml(self):
        """Test that 50c threshold is reflected in profile YAML."""
        profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = yaml.safe_load(f)
        
        # Check guardrails.max_spread_cents (liquidity threshold, not entry price)
        assert 'guardrails' in profile
        guardrails = profile['guardrails']
        assert guardrails['max_spread_cents'] == 75  # Remains 75c for DOGE spreads

        # Check universe.max_spread_cents (liquidity threshold, not entry price)
        assert 'universe' in profile
        universe = profile['universe']
        assert universe['max_spread_cents'] == 75  # Remains 75c for DOGE spreads

        # Check guardrails max_contract_price_cents (entry price threshold)
        # 2026-07-08: Updated to 50c for sweet spot (10-50c)
        assert guardrails['max_contract_price_cents'] == 50
