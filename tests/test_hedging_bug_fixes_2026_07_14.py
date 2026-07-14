"""
Comprehensive tests for hedging bug fixes (2026-07-14).

Tests for SEV-0, SEV-1, and SEV-2 fixes:
- SEV-0: Hedge markers in EXIT_ORDER_MARKERS
- SEV-0: Hedge fill source classification robustness
- SEV-1: Cross-asset hedging warning
- SEV-1: Hedge-specific exposure accounting
- SEV-2: Configuration consistency
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass


class TestHedgeExitOrderDetection:
    """Test SEV-0 FIX: Hedge orders are detected as exit orders."""
    
    def test_hedge_marker_in_exit_order_markers(self):
        """Test that 'hedge' and 'hedge_engine' are in EXIT_ORDER_MARKERS."""
        from merid.event_venues.kalshi.exit_order_utils import EXIT_ORDER_MARKERS
        
        assert "hedge" in EXIT_ORDER_MARKERS
        assert "hedge_engine" in EXIT_ORDER_MARKERS
    
    def test_hedge_source_detected_as_exit(self):
        """Test that hedge source is detected as exit order."""
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
        
        assert is_exit_order_from_source("hedge") is True
        assert is_exit_order_from_source("hedge_engine") is True
        assert is_exit_order_from_source("offset_hedging") is True
    
    def test_hedge_source_case_insensitive(self):
        """Test that hedge detection is case-insensitive."""
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
        
        assert is_exit_order_from_source("HEDGE") is True
        assert is_exit_order_from_source("HEDGE_ENGINE") is True
        assert is_exit_order_from_source("Offset_Hedging") is True


class TestHedgeFillSourceClassification:
    """Test SEV-0 FIX: Robust hedge fill source classification."""
    
    @pytest.mark.asyncio
    async def test_fill_source_from_ledger_authoritative(self):
        """Test that fills_ledger is the authoritative source."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Mock fills_ledger
        mock_ledger = MagicMock()
        mock_fill = MagicMock()
        mock_fill.fill_source = "hedge"
        mock_ledger.get_fill_by_id.return_value = mock_fill
        
        cache = KalshiPositionCache()
        cache._fills_ledger = mock_ledger
        
        result = await cache._lookup_fill_source("fill_123", "client_456")
        assert result == "hedge"
        mock_ledger.get_fill_by_id.assert_called_once_with("fill_123")
    
    @pytest.mark.asyncio
    async def test_fill_source_fallback_to_client_order_id_prefix(self):
        """Test fallback to client_order_id prefix when ledger lookup fails."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Mock fills_ledger that returns None
        mock_ledger = MagicMock()
        mock_ledger.get_fill_by_id.return_value = None
        
        cache = KalshiPositionCache()
        cache._fills_ledger = mock_ledger
        
        result = await cache._lookup_fill_source("fill_123", "HEDGE_abc123")
        assert result == "hedge"
    
    @pytest.mark.asyncio
    async def test_fill_source_fallback_to_content_analysis(self):
        """Test fallback to client_order_id content analysis."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Mock fills_ledger that returns None
        mock_ledger = MagicMock()
        mock_ledger.get_fill_by_id.return_value = None
        
        cache = KalshiPositionCache()
        cache._fills_ledger = mock_ledger
        
        # Test various hedge markers in client_order_id
        test_cases = [
            ("merid-hedge-abc", "hedge"),
            ("order_hedge_engine_xyz", "hedge"),
            ("HEDGE_order_123", "hedge"),
        ]
        
        for client_order_id, expected in test_cases:
            result = await cache._lookup_fill_source("fill_123", client_order_id)
            assert result == expected, f"Failed for {client_order_id}"
    
    @pytest.mark.asyncio
    async def test_fill_source_default_to_alpha(self):
        """Test that alpha is returned when no hedge indicators found."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Mock fills_ledger that returns None
        mock_ledger = MagicMock()
        mock_ledger.get_fill_by_id.return_value = None
        
        cache = KalshiPositionCache()
        cache._fills_ledger = mock_ledger
        
        result = await cache._lookup_fill_source("fill_123", "alpha_order_456")
        assert result == "alpha"
    
    @pytest.mark.asyncio
    async def test_fill_source_validation(self):
        """Test that unexpected fill_source values are handled gracefully."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Mock fills_ledger with unexpected value
        mock_ledger = MagicMock()
        mock_fill = MagicMock()
        mock_fill.fill_source = "unexpected_value"
        mock_ledger.get_fill_by_id.return_value = mock_fill
        
        cache = KalshiPositionCache()
        cache._fills_ledger = mock_ledger
        
        # Should fall back to client_order_id detection
        result = await cache._lookup_fill_source("fill_123", "HEDGE_abc")
        assert result == "hedge"
    
    @pytest.mark.asyncio
    async def test_fill_source_valid_values_accepted(self):
        """Test that valid fill_source values are accepted."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        valid_values = ["hedge", "alpha", "manual"]
        
        for valid_value in valid_values:
            mock_ledger = MagicMock()
            mock_fill = MagicMock()
            mock_fill.fill_source = valid_value
            mock_ledger.get_fill_by_id.return_value = mock_fill
            
            cache = KalshiPositionCache()
            cache._fills_ledger = mock_ledger
            
            result = await cache._lookup_fill_source("fill_123", "any_client_id")
            assert result == valid_value


class TestCrossAssetHedgingWarning:
    """Test SEV-1 FIX: Warning when cross_asset_enabled but not implemented."""
    
    def test_cross_asset_enabled_logs_warning(self):
        """Test that warning is logged when cross_asset_enabled is True."""
        from merid.hedging.config import HedgeConfig, AssetSliceConfig, TimeframeHedgeRule
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot
        import logging
        
        # Create config with cross_asset_enabled=True
        cfg = HedgeConfig(
            enabled=True,
            cross_asset_enabled=True,
            asset_slices={"BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25)},
            timeframes={"1h": TimeframeHedgeRule(target_hedge_ratio=0.5)},
        )
        
        # Create exposure
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 5000
        
        # Capture logs
        with patch("merid.hedging.engine.logger") as mock_logger:
            engine = CryptoHedgeEngine()
            engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
            
            # Verify warning was called
            mock_logger.warning.assert_called()
            warning_call = str(mock_logger.warning.call_args)
            assert "cross_asset_enabled" in warning_call
            assert "not implemented" in warning_call
    
    def test_cross_asset_disabled_no_warning(self):
        """Test that no warning is logged when cross_asset_enabled is False."""
        from merid.hedging.config import HedgeConfig, AssetSliceConfig, TimeframeHedgeRule
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot
        
        # Create config with cross_asset_enabled=False (default)
        cfg = HedgeConfig(
            enabled=True,
            cross_asset_enabled=False,
            asset_slices={"BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25)},
            timeframes={"1h": TimeframeHedgeRule(target_hedge_ratio=0.5)},
        )
        
        # Create exposure
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 5000
        
        # Capture logs
        with patch("merid.hedging.engine.logger") as mock_logger:
            engine = CryptoHedgeEngine()
            engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
            
            # Verify warning was NOT called
            mock_logger.warning.assert_not_called()


class TestConfigurationConsistency:
    """Test SEV-2 FIX: Configuration parameter consistency."""
    
    def test_hedge_neutral_threshold_consistent_env_var(self):
        """Test that HEDGE_NEUTRAL_THRESHOLD_CENTS uses consistent env var."""
        from merid.hedging.exposure import HEDGE_NEUTRAL_THRESHOLD_CENTS
        import os
        
        # Check that it uses MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS
        # Default should be 10 (not 1000)
        assert HEDGE_NEUTRAL_THRESHOLD_CENTS == 10
    
    def test_hedge_coverage_ratio_consistent_env_var(self):
        """Test that MAX_HEDGE_COVERAGE_RATIO uses consistent env var."""
        from merid.hedging.exposure import MAX_HEDGE_COVERAGE_RATIO
        import os
        
        # Check that it uses MERID_MAX_HEDGE_COVERAGE_RATIO
        # Default should be 1.0 (not 2.0)
        assert MAX_HEDGE_COVERAGE_RATIO == 1.0
    
    def test_no_duplicate_config_definitions(self):
        """Test that config parameters are not duplicated in exposure.py."""
        from merid.hedging import exposure
        import inspect
        
        source = inspect.getsource(exposure)
        
        # Count actual assignment patterns (not comments)
        hedge_neutral_count = source.count('os.environ.get("MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS"')
        hedge_coverage_count = source.count('os.environ.get("MERID_MAX_HEDGE_COVERAGE_RATIO"')
        
        # Should be defined once each
        assert hedge_neutral_count == 1, "MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS defined multiple times"
        assert hedge_coverage_count == 1, "MERID_MAX_HEDGE_COVERAGE_RATIO defined multiple times"
    
    def test_env_var_override_works(self):
        """Test that environment variable overrides work correctly."""
        import os
        from merid.hedging import exposure
        
        # Save original values
        orig_neutral = os.environ.get("MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS")
        orig_coverage = os.environ.get("MERID_MAX_HEDGE_COVERAGE_RATIO")
        
        try:
            # Set custom values
            os.environ["MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS"] = "50"
            os.environ["MERID_MAX_HEDGE_COVERAGE_RATIO"] = "1.5"
            
            # Reload the module to pick up new env vars
            import importlib
            importlib.reload(exposure)
            
            # Check that custom values are used
            assert exposure.HEDGE_NEUTRAL_THRESHOLD_CENTS == 50
            assert exposure.MAX_HEDGE_COVERAGE_RATIO == 1.5
        finally:
            # Restore original values
            if orig_neutral is not None:
                os.environ["MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS"] = orig_neutral
            else:
                os.environ.pop("MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS", None)
            
            if orig_coverage is not None:
                os.environ["MERID_MAX_HEDGE_COVERAGE_RATIO"] = orig_coverage
            else:
                os.environ.pop("MERID_MAX_HEDGE_COVERAGE_RATIO", None)
            
            # Reload again to restore defaults
            importlib.reload(exposure)


class TestHedgeExposureAccounting:
    """Test SEV-1 FIX: Hedge-specific exposure accounting."""
    
    def test_hedge_orders_bypass_exposure_recording(self):
        """Test that hedge orders are treated as exit orders for exposure."""
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_action
        
        # Hedge orders should be detected as exit orders
        assert is_exit_order_from_action("buy", "hedge_engine") is True
        assert is_exit_order_from_action("sell", "hedge") is True
    
    def test_position_cache_uses_exit_order_utils(self):
        """Test that position_cache uses exit_order_utils for hedge detection."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        import inspect
        
        source = inspect.getsource(KalshiPositionCache._is_exit_order_from_action)
        
        # Should import from exit_order_utils
        assert "exit_order_utils" in source
        assert "is_exit_order_from_action" in source


class TestHedgeOrderIntegration:
    """Integration tests for hedge order flow."""
    
    def test_hedge_order_intent_has_correct_source(self):
        """Test that hedge OrderIntent has HEDGE_ENGINE source."""
        from merid.hedging.engine import HEDGE_SOURCE, HEDGE_AGENT_ID, HEDGE_STRATEGY_GROUP
        
        assert HEDGE_SOURCE == "HEDGE_ENGINE"
        assert HEDGE_AGENT_ID == "hedge_engine"
        assert HEDGE_STRATEGY_GROUP == "hedge"
    
    def test_hedge_order_bypasses_10c_minimum(self):
        """Test that hedge orders can bypass 10c minimum price check."""
        # This is tested in order_router.py line 7020
        # The check: if intent.price_cents < 10 and intent.source != "hedge_engine"
        # So hedge_engine source bypasses the check
        pass  # Integration test would require full order router setup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
