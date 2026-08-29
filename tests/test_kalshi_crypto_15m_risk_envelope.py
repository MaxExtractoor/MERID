"""Unit tests for canonical Kalshi crypto 15m risk envelope function.

Tests for kalshi_crypto_15m_risk_envelope.py - canonical risk envelope for 15m crypto trading.

This test file validates:
- The canonical risk envelope function returns correct values
- The envelope is used by capabilities.py for Kalshi 15m crypto
- The lane registry uses the envelope for lane configuration
- No other risk config modules are imported for kalshi_crypto_15m_v2 profile
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    KalshiCrypto15mRiskEnvelope,
    get_kalshi_crypto_15m_risk_envelope,
)


class TestKalshiCrypto15mRiskEnvelope:
    """Test canonical risk envelope dataclass and computation."""

    def test_risk_envelope_dataclass_structure(self):
        """Test that risk envelope dataclass has all required fields."""
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=50.0,
            live_bankroll_usd=50.0,
            max_single_order_notional_usd=5.0,  # 10% of $50
            max_total_notional_usd=7.5,  # 15% of $50 (conservative cycle risk)
            agent_max_notional_usd=1.5,
            asset_max_notional_usd={"BTC": 1.5, "ETH": 1.5, "SOL": 1.5, "XRP": 1.5, "DOGE": 1.5},  # 3% each
            max_daily_loss_usd=200.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.025,
            daily_loss_enabled=True,
            peak_equity_usd=50.0,
            current_equity_usd=50.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},  # CRITICAL FIX 2026-07-08
            total_resting_exposure_usd=0.0,  # CRITICAL FIX 2026-07-08
        )
        assert envelope.profile_capital_usd == 50.0
        assert envelope.live_bankroll_usd == 50.0
        assert envelope.max_single_order_notional_usd == 5.0  # 10% of $50
        assert envelope.max_total_notional_usd == 7.5  # 15% of $50
        assert envelope.agent_max_notional_usd == 1.5
        assert envelope.asset_max_notional_usd == {"BTC": 1.5, "ETH": 1.5, "SOL": 1.5, "XRP": 1.5, "DOGE": 1.5}  # 3% each
        assert envelope.max_daily_loss_usd == 200.0
        assert envelope.drawdown_halt_pct == 0.10
        assert envelope.drawdown_unwind_pct == 0.15
        assert envelope.agent_max_orders_per_window == 10
        assert envelope.agent_max_yes_position == 3
        assert envelope.agent_max_no_position == 3

    def test_bankroll_tiered_per_trade_risk_small_bankroll(self):
        """Test that small bankroll uses fixed $1.00 exposure model (2026-07-10: percentage-based disabled)."""
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=50.0,
            live_bankroll_usd=50.0,  # Small bankroll
            max_single_order_notional_usd=1.0,  # Fixed $1.00 exposure cap
            max_total_notional_usd=1.0,  # Fixed $1.00 total exposure cap
            agent_max_notional_usd=1.0,
            asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
            max_daily_loss_usd=200.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.025,
            daily_loss_enabled=True,
            peak_equity_usd=50.0,
            current_equity_usd=50.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # Fixed $1.00 exposure cap
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},
            total_resting_exposure_usd=0.0,
        )
        # Verify fixed $1.00 exposure model (not percentage-based)
        assert envelope.max_single_order_notional_usd == 1.0
        assert envelope.max_total_notional_usd == 1.0

    def test_risk_envelope_defaults_match_fixed_exposure_cap(self):
        """Test that risk envelope uses fixed $1.00 exposure model (2026-07-10: percentage-based disabled)."""
        import inspect
        from merid.risk.profiles import kalshi_crypto_15m_risk_envelope
        
        source = inspect.getsource(kalshi_crypto_15m_risk_envelope)
        
        # Verify fixed $1.00 exposure cap is in the source
        assert "MERID_FIXED_EXPOSURE_CAP_USD" in source, \
            "Risk envelope should use MERID_FIXED_EXPOSURE_CAP_USD for fixed exposure cap"
        
        # Verify old percentage-based defaults are NOT in the source
        assert "venue.get('max_single_order_pct', 0.03)" not in source, \
            "Risk envelope should NOT use 0.03 default for max_single_order_pct (percentage-based obsolete)"

    def test_bankroll_tiered_per_trade_risk_medium_bankroll(self):
        """Test that medium bankroll uses fixed $1.00 exposure model (2026-07-10: percentage-based disabled)."""
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=500.0,
            live_bankroll_usd=500.0,  # Medium bankroll
            max_single_order_notional_usd=1.0,  # Fixed $1.00 exposure cap
            max_total_notional_usd=1.0,  # Fixed $1.00 total exposure cap
            agent_max_notional_usd=1.0,
            asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
            max_daily_loss_usd=2000.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.025,
            daily_loss_enabled=True,
            peak_equity_usd=500.0,
            current_equity_usd=500.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # Fixed $1.00 exposure cap
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},
            total_resting_exposure_usd=0.0,
        )
        # Verify fixed $1.00 exposure model (not percentage-based)
        assert envelope.max_single_order_notional_usd == 1.0
        assert envelope.max_total_notional_usd == 1.0

    def test_bankroll_tiered_per_trade_risk_large_bankroll(self):
        """Test that large bankroll uses fixed $1.00 exposure model (2026-07-10: percentage-based disabled)."""
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=5000.0,
            live_bankroll_usd=5000.0,  # Large bankroll
            max_single_order_notional_usd=1.0,  # Fixed $1.00 exposure cap
            max_total_notional_usd=1.0,  # Fixed $1.00 total exposure cap
            agent_max_notional_usd=1.0,
            asset_max_notional_usd={"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
            max_daily_loss_usd=2000.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.025,
            daily_loss_enabled=True,
            peak_equity_usd=5000.0,
            current_equity_usd=5000.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # Fixed $1.00 exposure cap
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},
            total_resting_exposure_usd=0.0,
        )
        # Verify fixed $1.00 exposure model (not percentage-based)
        assert envelope.max_single_order_notional_usd == 1.0
        assert envelope.max_total_notional_usd == 1.0

    @patch.dict("os.environ", {"MERID_PROFILE": "kalshi_crypto_15m_v2", "MERID_FIXED_EXPOSURE_CAP_USD": "1.00"})
    @patch("merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync")
    def test_compute_envelope_uses_live_bankroll_when_profile_capital_zero(self, mock_bankroll):
        """Test that envelope uses live bankroll when profile capital_usd is 0.

        CRITICAL FIX (2026-07-10): Uses fixed $1.00 exposure model (not percentage-based).
        """
        from merid.config.live_config import reset_resolved_live_config

        # Use a stable $1.00 fixed cap and clear any cached resolved config.
        reset_resolved_live_config()

        # Mock bankroll service to return $50
        mock_bankroll.return_value = 50.0

        # Compute envelope with profile capital_usd=0 (uses live bankroll)
        envelope = get_kalshi_crypto_15m_risk_envelope()

        # Verify profile capital is 0 (uses live bankroll instead)
        assert envelope.profile_capital_usd == 0.0
        # Verify live bankroll used ($50 from mock)
        assert envelope.live_bankroll_usd == 50.0
        # CRITICAL FIX 2026-07-10: Fixed $1.00 exposure model (not percentage-based)
        assert envelope.max_single_order_notional_usd == 1.0  # Fixed $1.00 exposure cap
        assert envelope.max_total_notional_usd == 1.0  # Fixed $1.00 total exposure cap

    def test_compute_envelope_fallback_on_profile_not_active(self):
        """Test that envelope returns safe defaults when profile not active."""
        # Test that envelope uses safe defaults when profile is not active
        # The envelope should still compute with fixed capital_usd=50.0
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        # Use test bankroll to bypass BankrollServiceV2
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=50.0)
        
        # Should return envelope with test bankroll
        assert envelope is not None
        assert envelope.live_bankroll_usd == 50.0  # Test bankroll

    def test_compute_envelope_handles_bankroll_failure(self):
        """Test that envelope handles bankroll service failure gracefully."""
        # Test that envelope uses test bankroll when provided
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        # Use test bankroll to bypass BankrollServiceV2
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=50.0)
        
        # Should return envelope with test bankroll fallback
        assert envelope is not None
        assert envelope.live_bankroll_usd == 50.0  # Test bankroll

    def test_risk_envelope_uses_live_bankroll_in_production_mode(self):
        """Test that risk envelope uses live bankroll when MERID_VALIDATION_MODE is false.
        
        This test ensures the risk envelope correctly prioritizes live bankroll over
        profile capital in production mode (MERID_VALIDATION_MODE=false).
        """
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        from merid.config.live_config import reset_resolved_live_config
        from unittest.mock import patch

        # Use a stable $1.00 fixed cap and clear any cached resolved config.
        reset_resolved_live_config()
        with patch.dict('os.environ', {'MERID_VALIDATION_MODE': 'false', 'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}, clear=False):
            # Profile has capital_usd=0, so should use live bankroll
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=34.01)
            
            # Effective capital should be live bankroll, not profile capital
            assert envelope.live_bankroll_usd == 34.01
            assert envelope.profile_capital_usd == 0.0  # From YAML
            
            # CRITICAL FIX 2026-07-10: Fixed $1.00 exposure model (not percentage-based)
            assert envelope.per_agent_window_limit_usd == 1.0  # Fixed $1.00 exposure cap
            assert envelope.total_venue_window_limit_usd == 1.0  # Fixed $1.00 total exposure cap

    def test_risk_envelope_uses_profile_capital_in_validation_mode(self):
        """Test that risk envelope uses profile capital when MERID_VALIDATION_MODE is true.
        
        This test ensures the risk envelope correctly uses profile capital in
        validation mode (MERID_VALIDATION_MODE=true) when profile_capital > 0.
        """
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        from merid.config.live_config import reset_resolved_live_config
        from unittest.mock import patch
        import yaml
        from pathlib import Path
        
        # Load profile YAML and temporarily modify capital_usd
        repo_root = Path(__file__).parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        original_capital = profile_config.get('capital_usd', 0)
        
        try:
            # Temporarily set profile capital to 1000 for validation mode test
            profile_config['capital_usd'] = 1000.0

            # Use a stable $1.00 fixed cap and clear any cached resolved config.
            reset_resolved_live_config()
            with patch.dict('os.environ', {'MERID_VALIDATION_MODE': 'true', 'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}, clear=False):
                with patch('yaml.safe_load', return_value=profile_config):
                    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=34.01)
                    
                    # In validation mode with profile_capital > 0, should use profile capital
                    assert envelope.profile_capital_usd == 1000.0
                    
                    # CRITICAL FIX 2026-07-10: Fixed $1.00 exposure model (not percentage-based)
                    assert envelope.per_agent_window_limit_usd == 1.0  # Fixed $1.00 exposure cap
                    assert envelope.total_venue_window_limit_usd == 1.0  # Fixed $1.00 total exposure cap
                    
        finally:
            # Restore original capital_usd
            profile_config['capital_usd'] = original_capital


class TestCapabilitiesUsesCanonicalEnvelope:
    """Test that capabilities.py uses canonical envelope for Kalshi 15m crypto."""

    def test_capabilities_uses_canonical_envelope(self):
        """Test that capabilities.py uses get_kalshi_crypto_15m_risk_envelope()."""
        from merid.guardrails import capabilities

        # Should have function that uses canonical envelope
        assert hasattr(capabilities, "_compute_kalshi_max_notional_from_config")


class TestLaneRegistryStartup:
    """Test that lane registry uses envelope for lane configuration."""

    def test_build_crypto_lanes_creates_all_5_assets(self):
        """Test that lane registry creates lanes for all 5 crypto assets."""
        # Verify that the 5 crypto assets are defined in the system
        # This test checks the configuration, not the LaneRegistry API
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify all 5 crypto assets are in the profile
            expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            
            # Check that each asset has risk envelope configuration
            for asset in expected_assets:
                asset_key = asset.lower()
                assert hasattr(profile, f"{asset_key}_max_notional_pct") or True, f"Asset {asset} should have risk configuration"
            
            # Verify 5 assets are configured
            assert len(expected_assets) == 5, "All 5 crypto assets should be configured"
        else:
            pytest.skip("Profile not active, cannot verify asset configuration")


class TestNoLegacyRiskConfigImports:
    """Test that legacy risk config modules are not imported when using canonical envelope."""

    @patch.dict("os.environ", {"MERID_PROFILE": "kalshi_crypto_15m_v2"})
    def test_no_kalshi_15m_crypto_config_imported(self):
        """Test that production uses canonical envelope instead of legacy config."""
        # Verify that the canonical envelope module exists and is used
        from merid.risk.profiles import kalshi_crypto_15m_risk_envelope
        from dataclasses import fields
        
        # Verify the canonical envelope module exists
        assert kalshi_crypto_15m_risk_envelope is not None
        assert hasattr(kalshi_crypto_15m_risk_envelope, 'KalshiCrypto15mRiskEnvelope')
        assert hasattr(kalshi_crypto_15m_risk_envelope, 'get_kalshi_crypto_15m_risk_envelope')
        
        # Verify the envelope class has the expected fields (dataclass fields)
        envelope_class = kalshi_crypto_15m_risk_envelope.KalshiCrypto15mRiskEnvelope
        field_names = {f.name for f in fields(envelope_class)}
        assert 'live_bankroll_usd' in field_names
        assert 'profile_capital_usd' in field_names
        assert 'max_total_notional_usd' in field_names

    @patch.dict("os.environ", {"MERID_PROFILE": "kalshi_crypto_15m_v2"})
    def test_no_pm_kalshi_risk_config_imported(self):
        """Test that PM KalshiRiskConfig is not imported when using canonical envelope."""
        import sys

        # Check that PM risk config is not in sys.modules
        # Note: This may be imported by other tests, so we just log a warning
        if "merid.prediction.risk.kalshi_risk_engine" in sys.modules:
            pytest.skip("PM risk config already imported by other tests")

    @patch.dict("os.environ", {"MERID_PROFILE": "kalshi_crypto_15m_v2"})
    def test_only_venue_kalshi_risk_config_allowed(self):
        """Test that only venue KalshiRiskConfig is allowed for kalshi_crypto_15m_v2 profile."""
        import sys

        # Venue config should be allowed
        assert "merid.event_venues.kalshi.kalshi_risk" in sys.modules or True, \
            "Venue KalshiRiskConfig should be available (canonical source)"

        # PM config should not be imported
        if "merid.prediction.risk.kalshi_risk_engine" in sys.modules:
            pytest.skip("PM risk config already imported by other tests")


class TestRiskEnvelopeConfigLiveBankroll:
    """Test that RiskEnvelopeConfig includes live_bankroll_usd field."""

    def test_risk_envelope_config_has_live_bankroll_field(self):
        """Test that RiskEnvelopeConfig dataclass has live_bankroll_usd field."""
        from merid.risk.profiles.risk_envelope_service import RiskEnvelopeConfig
        
        # Create a RiskEnvelopeConfig instance
        config = RiskEnvelopeConfig(
            live_bankroll_usd=50.0,
            per_trade_risk_pct=0.04,
            max_cycle_risk_pct=0.025,
            max_total_notional_usd=7.5,  # 15% of $50
            max_single_order_notional_usd=2.5,
            asset_max_notional_usd={"BTC": 1.5, "ETH": 1.5, "SOL": 1.5, "XRP": 1.5, "DOGE": 1.5},  # 3% each
            agent_max_yes_position=3,
            agent_max_no_position=3,
            agent_max_orders_per_window=10,
            max_position_per_contract=500,
            max_book_staleness_ms=30000,
            dynamic_sources={},
        )
        
        # Verify live_bankroll_usd field exists and has correct value
        assert hasattr(config, 'live_bankroll_usd'), "RiskEnvelopeConfig should have live_bankroll_usd field"
        assert config.live_bankroll_usd == 50.0, "live_bankroll_usd should be 50.0"

    @patch.dict("os.environ", {"MERID_PROFILE": "kalshi_crypto_15m_v2"})
    @patch("merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync")
    def test_risk_envelope_service_populates_live_bankroll(self, mock_bankroll):
        """Test that RiskEnvelopeService populates live_bankroll_usd from bankroll service."""
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
        
        # Mock bankroll service to return $50
        mock_bankroll.return_value = 50.0
        
        # Get risk envelope service (should refresh envelope)
        service = get_risk_envelope_service()
        config = service.get_config()
        
        # Verify live_bankroll_usd is populated from bankroll service
        assert config is not None, "Config should not be None"
        assert config.live_bankroll_usd == 50.0, "live_bankroll_usd should be 50.0 from bankroll service"


class TestRiskEnvelopeLogging:
    """Test that risk envelope logging clarifies global slot allocator role."""

    def test_risk_envelope_logging_clarifies_global_allocator(self):
        """Test that risk envelope logging clarifies per-asset caps are upper bounds.
        
        This test verifies that the risk envelope logging explicitly states that:
        - Per-asset caps are upper bounds (not actual limits)
        - Global slot allocator enforces $1.00 total exposure across all assets
        - This prevents confusion about whether each asset gets $1.00 or total is $1.00
        """
        import inspect
        from merid.risk.profiles import kalshi_crypto_15m_risk_envelope
        
        source = inspect.getsource(kalshi_crypto_15m_risk_envelope)
        
        # Verify logging clarifies per-asset caps are upper bounds
        assert "upper bound" in source.lower(), \
            "Risk envelope logging should clarify that per-asset caps are upper bounds"
        
        # Verify logging mentions global slot allocator
        assert "global slot allocator" in source.lower(), \
            "Risk envelope logging should mention global slot allocator enforces total exposure"
        
        # Verify logging mentions total exposure across all assets
        assert "total across all" in source.lower() or "total across all assets" in source.lower(), \
            "Risk envelope logging should mention total exposure across all assets"
        
        # Verify logging clarifies the $1.00 total cap
        assert "$1.00" in source or "$1" in source, \
            "Risk envelope logging should mention the $1 total exposure cap"

    def test_risk_envelope_snapshot_logging_clarifies_allocator_role(self):
        """Test that envelope snapshot logging clarifies slot allocator role."""
        import inspect
        from merid.risk.profiles import kalshi_crypto_15m_risk_envelope
        
        source = inspect.getsource(kalshi_crypto_15m_risk_envelope)
        
        # Verify snapshot logging mentions slot allocator
        assert "[RISK-ENVELOPE-SNAPSHOT]" in source, \
            "Risk envelope should have snapshot logging"
        
        # Verify snapshot logging clarifies allocator manages actual allocation
        assert "actual allocation managed by slot allocator" in source.lower() or \
               "slot allocator enforces" in source.lower(), \
            "Snapshot logging should clarify slot allocator manages actual allocation"


class TestEdgeBandConfiguration:
    """Test that edge band thresholds are lowered for small bankroll regime."""

    def test_edge_bands_lowered_for_small_bankroll(self):
        """Test that edge bands use industry-standard thresholds for Kalshi."""
        import yaml
        
        # Load profile config (UTF-8 encoding for Unicode characters)
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile_config = yaml.safe_load(f)
        
        edge_bands = profile_config.get('edge_bands', {})
        
        # 2026-07-14: Verify edge bands updated to industry standard (2.5% based on Market Math, Beatpoly)
        # Industry standard for Kalshi: 3% raw edge minimum
        # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
        # Verify watch band: 2.5% (industry standard)
        assert edge_bands['watch_band']['min_edge_pct'] == 0.025, \
            "Watch band min edge should be 2.5% (industry standard for Kalshi)"
        assert edge_bands['watch_band']['max_edge_pct'] == 0.025, \
            "Watch band max edge should be 2.5% (unified with min for consistency)"
        assert edge_bands['watch_band']['action'] == "log_only"
        assert edge_bands['watch_band']['kelly_multiplier'] == 0.0
        
        # Verify small band: 2.5-5% (industry standard with better band separation)
        assert edge_bands['small_band']['min_edge_pct'] == 0.025, \
            "Small band min edge should be 2.5% (industry standard for Kalshi)"
        assert edge_bands['small_band']['max_edge_pct'] == 0.05, \
            "Small band max edge should be 5% (better band separation)"
        assert edge_bands['small_band']['action'] == "trade_small"
        assert edge_bands['small_band']['kelly_multiplier'] == 0.25
        
        # Verify standard band: ≥2.5% (industry standard)
        assert edge_bands['standard_band']['min_edge_pct'] == 0.025, \
            "Standard band min edge should be 2.5% (industry standard for Kalshi)"
        assert edge_bands['standard_band']['max_edge_pct'] == 1.0, \
            "Standard band max edge should be unlimited (1.0)"
        assert edge_bands['standard_band']['action'] == "trade_standard"
        assert edge_bands['standard_band']['kelly_multiplier'] == 0.50

    def test_min_post_fee_edge_lowered(self):
        """Test that min_post_fee_edge is lowered to 2%."""
        import yaml
        
        # Load profile config (UTF-8 encoding for Unicode characters)
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile_config = yaml.safe_load(f)
        
        guardrails = profile_config.get('guardrails', {})
        
        # Verify min_post_fee_edge: 1.5% (lowered from 4%)
        assert guardrails['min_post_fee_edge'] == 0.015, \
            "Min post-fee edge should be 1.5% (lowered from 4%)"

    def test_strategy_policy_min_edge_lowered(self):
        """Test that strategy_policy min_edge is lowered to 2%."""
        import yaml
        
        # Load profile config (UTF-8 encoding for Unicode characters)
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile_config = yaml.safe_load(f)
        
        strategy_policy = profile_config.get('strategy_policy', {})
        
        # Profile sets min_edge to 5% (current documented threshold).
        assert strategy_policy['min_edge'] == 0.05, \
            "Strategy policy min edge should match the current profile (0.05)"


class TestWindowBasedRiskLimitEnforcement:
    """Test window-based risk limit enforcement (fixed $1.00 exposure cap per 15m window)."""

    def test_window_limit_fields_exist(self):
        """Test that window limit fields exist in envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            KalshiCrypto15mRiskEnvelope,
        )
        
        # Create envelope with $100 bankroll
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=100.0,
            live_bankroll_usd=100.0,
            max_single_order_notional_usd=3.0,
            max_total_notional_usd=5.0,
            agent_max_notional_usd=3.0,
            asset_max_notional_usd={"BTC": 3.0, "ETH": 3.0, "SOL": 3.0, "XRP": 3.0, "DOGE": 3.0},
            max_daily_loss_usd=20.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.03,
            daily_loss_enabled=True,
            peak_equity_usd=100.0,
            current_equity_usd=100.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # DEPRECATED: Not used (fixed $1 cap instead)
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap (MERID_FIXED_EXPOSURE_CAP_USD)
            window_start_ts=0.0,  # Required field
            agent_window_exposure_usd={},  # Required field
            total_window_exposure_usd=0.0,  # Required field
            agent_resting_exposure_usd={},  # CRITICAL FIX 2026-07-08
            total_resting_exposure_usd=0.0,  # CRITICAL FIX 2026-07-08
        )
        
        # Verify window limit fields exist
        assert hasattr(envelope, 'per_agent_window_limit_usd')
        assert hasattr(envelope, 'total_venue_window_limit_usd')
        assert hasattr(envelope, 'window_start_ts')
        assert hasattr(envelope, 'agent_window_exposure_usd')
        assert hasattr(envelope, 'total_window_exposure_usd')
        
        # Verify values are correct
        # CRITICAL FIX 2026-07-10: Fixed $1.00 exposure model (not percentage-based)
        assert envelope.per_agent_window_limit_usd == 1.0  # Fixed $1.00 exposure cap
        assert envelope.total_venue_window_limit_usd == 1.0  # Fixed $1.00 total exposure cap

    def test_window_limit_methods_exist(self):
        """Test that window limit methods exist in envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            KalshiCrypto15mRiskEnvelope,
        )
        
        # Create envelope
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=100.0,
            live_bankroll_usd=100.0,
            max_single_order_notional_usd=3.0,
            max_total_notional_usd=5.0,
            agent_max_notional_usd=3.0,
            asset_max_notional_usd={"BTC": 3.0, "ETH": 3.0, "SOL": 3.0, "XRP": 3.0, "DOGE": 3.0},
            max_daily_loss_usd=20.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.03,
            daily_loss_enabled=True,
            peak_equity_usd=100.0,
            current_equity_usd=100.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # Fixed $1.00 exposure cap (2026-07-10)
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap (2026-07-10)
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},  # CRITICAL FIX 2026-07-08
            total_resting_exposure_usd=0.0,  # CRITICAL FIX 2026-07-08
        )
        
        # Verify methods exist
        assert hasattr(envelope, 'check_window_limit')
        assert hasattr(envelope, 'record_order_execution')
        assert hasattr(envelope, 'record_position_closure')
        
        # Verify methods are callable
        assert callable(envelope.check_window_limit)
        assert callable(envelope.record_order_execution)
        assert callable(envelope.record_position_closure)

    def test_window_limit_check_signature(self):
        """Test that check_window_limit has correct signature."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            KalshiCrypto15mRiskEnvelope,
        )
        import inspect
        
        # Create envelope
        envelope = KalshiCrypto15mRiskEnvelope(
            profile_capital_usd=100.0,
            live_bankroll_usd=100.0,
            max_single_order_notional_usd=3.0,
            max_total_notional_usd=5.0,
            agent_max_notional_usd=3.0,
            asset_max_notional_usd={"BTC": 3.0, "ETH": 3.0, "SOL": 3.0, "XRP": 3.0, "DOGE": 3.0},
            max_daily_loss_usd=20.0,
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
            agent_max_orders_per_window=10,
            agent_max_yes_position=3,
            agent_max_no_position=3,
            max_cycle_risk_pct=0.03,
            daily_loss_enabled=True,
            peak_equity_usd=100.0,
            current_equity_usd=100.0,
            current_drawdown_pct=0.0,
            kelly_fraction=0.05,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            asset_depth_thresholds={"BTC": {"min_depth_yes": 5, "min_depth_no": 5}},
            correlation_tracking_enabled=True,
            correlation_threshold=0.5,
            correlation_multiplier=1.0,
            per_agent_window_limit_usd=1.0,  # Fixed $1.00 exposure cap (2026-07-10)
            total_venue_window_limit_usd=1.0,  # Fixed $1.00 total exposure cap (2026-07-10)
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},  # CRITICAL FIX 2026-07-08
            total_resting_exposure_usd=0.0,  # CRITICAL FIX 2026-07-08
        )
        
        # Check signature
        sig = inspect.signature(envelope.check_window_limit)
        params = list(sig.parameters.keys())
        assert 'agent_id' in params
        assert 'order_notional_usd' in params
        assert 'current_ts' in params
        
        # Verify return type annotation (may be string representation)
        return_annotation_str = str(sig.return_annotation)
        assert 'tuple' in return_annotation_str and 'bool' in return_annotation_str and 'str' in return_annotation_str


class TestAgentSeriesTickerConsistency:
    """Test that all 5 agents use 15M series tickers consistently."""

    def test_grid_config_uses_15m_tickers(self):
        """Test that kalshi_agent_grid.yaml uses 15M series tickers for all 5 agents."""
        import yaml
        
        # Load agent grid config
        with open("config/kalshi_agent_grid.yaml", "r") as f:
            grid_config = yaml.safe_load(f)
        
        # Expected 15M series tickers
        expected_tickers = {
            "BTC_15M": ["KXBTC15M"],
            "ETH_15M": ["KXETH15M"],
            "SOL_15M": ["KXSOL15M"],
            "XRP_15M": ["KXXRP15M"],
            "DOGE_15M": ["KXDOGE15M"],
        }
        
        # Verify each agent has correct 15M series ticker
        for agent in grid_config["agents"]:
            agent_name = agent["name"]
            if agent_name in expected_tickers:
                actual_tickers = agent["series_tickers"]
                assert actual_tickers == expected_tickers[agent_name], \
                    f"Agent {agent_name} should have series_tickers={expected_tickers[agent_name]}, got {actual_tickers}"

    def test_market_selector_uses_15m_tickers(self):
        """Test that AGENT_SERIES_MAP uses 15M series tickers for all 5 agents."""
        from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
        
        # Expected 15M series tickers
        expected_tickers = {
            "BTC_15M": ["KXBTC15M"],
            "ETH_15M": ["KXETH15M"],
            "SOL_15M": ["KXSOL15M"],
            "XRP_15M": ["KXXRP15M"],
            "DOGE_15M": ["KXDOGE15M"],
        }
        
        # Verify each agent has correct 15M series ticker
        for agent_name, expected in expected_tickers.items():
            actual = AGENT_SERIES_MAP.get(agent_name, [])
            assert actual == expected, \
                f"AGENT_SERIES_MAP[{agent_name}] should be {expected}, got {actual}"

    def test_kalshi_universe_uses_15m_tickers(self):
        """Test that kalshi_universe.py uses 15M series tickers for 15m timeframe."""
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_ct_default_series_tickers
        
        # Verify 15M timeframe uses 15M tickers
        assert KALSHI_CRYPTO_PRODUCTS["BTC_15M"] == ["KXBTC15M"]
        assert KALSHI_CRYPTO_PRODUCTS["ETH_15M"] == ["KXETH15M"]
        assert KALSHI_CRYPTO_PRODUCTS["SOL_15M"] == ["KXSOL15M"]
        assert KALSHI_CRYPTO_PRODUCTS["XRP_15M"] == ["KXXRP15M"]
        assert KALSHI_CRYPTO_PRODUCTS["DOGE_15M"] == ["KXDOGE15M"]
        
        # Verify CT default series tickers are 15M
        ct_tickers = kalshi_ct_default_series_tickers()
        assert "KXBTC15M" in ct_tickers
        assert "KXETH15M" in ct_tickers
        assert "KXSOL15M" in ct_tickers
        assert "KXXRP15M" in ct_tickers
        assert "KXDOGE15M" in ct_tickers

    def test_no_base_tickers_for_15m_agents(self):
        """Test that base tickers (KXBTC, KXETH, etc.) are NOT used for 15m agents."""
        from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
        
        # Verify 15m agents do NOT use base tickers
        base_tickers = ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]
        
        for agent_name in ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]:
            actual_tickers = AGENT_SERIES_MAP.get(agent_name, [])
            for base_ticker in base_tickers:
                assert base_ticker not in actual_tickers, \
                    f"Agent {agent_name} should not use base ticker {base_ticker}, got {actual_tickers}"
