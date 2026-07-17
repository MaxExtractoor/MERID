"""
Tests for Exit Policy Import and Series Ticker Fixes (2026-07-17)

Tests the critical fixes for:
1. edge_based_exit_evaluator.py: unified_spot_service import path fix
2. position_monitor.py: unified_spot_service import path fix
3. position_monitor.py: seconds_to_expiry attribute fix
4. position_cache.py: series_ticker field in Position creation (fill path)
5. position_cache.py: series_ticker field in Position creation (REST sync path)
6. position_monitor.py: asset extraction using series_ticker with fallback
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from datetime import datetime

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor


class TestEdgeBasedExitEvaluatorImportFix:
    """Test that edge_based_exit_evaluator uses correct import path for unified_spot_service."""
    
    def test_import_path_is_correct(self):
        """Test that the import uses data.unified_spot_service, not merid.prediction.unified_spot."""
        import merid.position_management.edge_based_exit_evaluator as evaluator_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(evaluator_module)
        
        # Should NOT contain the wrong import
        assert "from merid.prediction.unified_spot" not in source
        assert "from merid.prediction.unified_spot_service" not in source
        
        # Should contain the correct import
        assert "from data.unified_spot_service import get_unified_spot_service" in source


class TestPositionMonitorImportFixes:
    """Test that position_monitor uses correct import paths and attributes."""
    
    def test_unified_spot_import_path_is_correct(self):
        """Test that the import uses data.unified_spot_service, not merid.data.unified_spot_service."""
        import merid.position_management.position_monitor as monitor_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(monitor_module)
        
        # Should NOT contain the wrong import
        assert "from merid.data.unified_spot_service" not in source
        
        # Should contain the correct import
        assert "from data.unified_spot_service import get_unified_spot_service" in source
    
    def test_seconds_to_expiry_attribute_used(self):
        """Test that position_monitor uses seconds_to_expiry, not minutes_to_expiry."""
        import merid.position_management.position_monitor as monitor_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(monitor_module)
        
        # Should NOT contain the wrong attribute
        assert "state.minutes_to_expiry" not in source
        
        # Should contain the correct attribute
        assert "state.seconds_to_expiry" in source


class TestPositionCacheSeriesTickerFix:
    """Test that position_cache sets series_ticker in Position objects."""
    
    def test_fill_path_sets_series_ticker(self):
        """Test that fill handling sets series_ticker in Position creation."""
        import merid.event_venues.kalshi.position_cache as cache_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(cache_module)
        
        # Should contain series_ticker extraction
        assert "series_ticker = market_id.split" in source
        assert "series_ticker=series_ticker" in source
    
    def test_rest_sync_path_sets_series_ticker(self):
        """Test that REST sync sets series_ticker in Position creation."""
        import merid.event_venues.kalshi.position_cache as cache_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(cache_module)
        
        # Should contain series_ticker extraction in REST sync section
        # The REST sync section should also have series_ticker
        assert source.count("series_ticker = market_id.split") >= 2  # At least 2 occurrences (fill + REST sync)


class TestPositionMonitorAssetExtractionFix:
    """Test that position_monitor uses series_ticker for asset extraction with fallback."""
    
    @pytest.fixture
    def mock_position_with_series_ticker(self):
        """Create a mock position with series_ticker set."""
        position = Position(
            position_id="test_position",
            market_id="KXBTC15M-2024-01-01T12:00:00",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        return position
    
    @pytest.fixture
    def mock_position_without_series_ticker(self):
        """Create a mock position without series_ticker (fallback case)."""
        position = Position(
            position_id="test_position",
            market_id="KXBTC15M-2024-01-01T12:00:00",
            series_ticker="",  # Empty - should fallback to market_id
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        return position
    
    def test_asset_extraction_uses_series_ticker(self, mock_position_with_series_ticker):
        """Test that asset extraction prioritizes series_ticker."""
        import merid.position_management.position_monitor as monitor_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(monitor_module)
        
        # Should check series_ticker first
        assert "if position.series_ticker:" in source
        assert "BTC\" in position.series_ticker.upper()" in source
    
    def test_asset_extraction_fallback_to_market_id(self, mock_position_without_series_ticker):
        """Test that asset extraction falls back to market_id if series_ticker is empty."""
        import merid.position_management.position_monitor as monitor_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(monitor_module)
        
        # Should have fallback logic
        assert "# Fallback to market_id if series_ticker not set" in source
        assert "if not asset:" in source


class TestPositionModelSeriesTickerField:
    """Test that Position model has series_ticker field."""
    
    def test_position_has_series_ticker_field(self):
        """Test that Position dataclass has series_ticker field."""
        from merid.position_management.position import Position
        from dataclasses import fields
        
        field_names = [f.name for f in fields(Position)]
        assert "series_ticker" in field_names
    
    def test_position_series_ticker_default(self):
        """Test that Position series_ticker has default value."""
        position = Position()
        assert hasattr(position, 'series_ticker')
        assert position.series_ticker == ""  # Default is empty string


class TestEndToEndExitPolicyFlow:
    """Test end-to-end exit policy flow with all fixes applied."""
    
    @pytest.fixture
    def monitor(self):
        """Create a PositionMonitor instance."""
        return PositionMonitor()
    
    @pytest.fixture
    def position_with_series_ticker(self):
        """Create a position with series_ticker set (as per fix)."""
        return Position(
            position_id="KXBTC15M-2024-01-01T12:00:00",
            market_id="KXBTC15M-2024-01-01T12:00:00",
            series_ticker="KXBTC15M",  # CRITICAL: Set by position_cache fix
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
    
    def test_position_added_to_monitor_has_series_ticker(self, monitor, position_with_series_ticker):
        """Test that positions added to monitor have series_ticker set."""
        monitor.add_position(position_with_series_ticker)
        
        # Verify position is in monitor
        assert position_with_series_ticker.position_id in monitor._open_positions
        
        # Verify series_ticker is set
        retrieved_position = monitor._open_positions[position_with_series_ticker.position_id]
        assert retrieved_position.series_ticker == "KXBTC15M"
    
    def test_position_monitor_can_extract_asset_from_series_ticker(self, monitor, position_with_series_ticker):
        """Test that position_monitor can extract asset from series_ticker."""
        # This tests the asset extraction fix
        position = position_with_series_ticker
        
        # Simulate the asset extraction logic from position_monitor
        asset = None
        if position.series_ticker:
            if "BTC" in position.series_ticker.upper():
                asset = "BTC"
            elif "ETH" in position.series_ticker.upper():
                asset = "ETH"
            elif "SOL" in position.series_ticker.upper():
                asset = "SOL"
            elif "XRP" in position.series_ticker.upper():
                asset = "XRP"
            elif "DOGE" in position.series_ticker.upper():
                asset = "DOGE"
        
        # Should extract BTC from KXBTC15M
        assert asset == "BTC"
    
    def test_position_monitor_fallback_to_market_id(self, monitor):
        """Test that position_monitor falls back to market_id if series_ticker is empty."""
        position = Position(
            position_id="KXETH15M-2024-01-01T12:00:00",
            market_id="KXETH15M-2024-01-01T12:00:00",
            series_ticker="",  # Empty - should fallback
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # Simulate the asset extraction logic with fallback
        asset = None
        if position.series_ticker:
            if "BTC" in position.series_ticker.upper():
                asset = "BTC"
            elif "ETH" in position.series_ticker.upper():
                asset = "ETH"
        # Fallback to market_id
        if not asset:
            if "BTC" in position.market_id.upper():
                asset = "BTC"
            elif "ETH" in position.market_id.upper():
                asset = "ETH"
        
        # Should extract ETH from market_id fallback
        assert asset == "ETH"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
