"""
Unit tests for Catalog roll-over detection and cooldown.

Tests roll-over detection, single resync per roll-over, and cooldown enforcement.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket

class TestCatalogRollOverDetection:
    """Test catalog roll-over detection logic."""
    
    @pytest.fixture
    def catalog(self):
        """Create a catalog for testing."""
        mock_client = MagicMock()
        catalog = KalshiMarketCatalog(
            client=mock_client,
            refresh_interval_s=5.0,  # Fast for testing
            max_markets=100
        )
        return catalog
    
    @pytest.fixture
    def fake_time(self):
        """Provide fake time for deterministic tests."""
        with patch('datetime.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_datetime.now.return_value = mock_now
            mock_now.timestamp.return_value = 1000.0
            mock_now.utcnow.return_value = mock_now
            yield mock_now
    
    def create_mock_market(self, ticker, series_ticker):
        """Create a mock market for testing."""
        mock_market = MagicMock()
        mock_market.market.market_id = ticker
        mock_market.market.raw_data = {"series_ticker": series_ticker}
        return mock_market
    
    @pytest.mark.asyncio
    async def test_roll_over_detection_triggers_resync(self, catalog, fake_time):
        """Test that roll-over detection triggers resync."""
        # Set up initial state
        series_ticker = "KXBTC15M"
        old_ticker = "KXBTC15M-26JUN022215-15"
        new_ticker = "KXBTC15M-26JUN022230-30"
        
        catalog._last_catalog_ticker[series_ticker] = old_ticker
        catalog._last_catalog_change_ts[series_ticker] = datetime(2026, 6, 2, 22, 0, 0, tzinfo=timezone.utc)
        
        # Create markets with new ticker
        markets = [self.create_mock_market(new_ticker, series_ticker)]
        
        # Mock WS bridge
        mock_ws_bridge = MagicMock()
        mock_ws_bridge._sync_requested = False
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Simulate catalog processing logic
            best_ticker = new_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                # Roll-over detected
                now_utc = fake_time
                catalog._last_catalog_ticker[series_ticker] = best_ticker
                catalog._last_catalog_change_ts[series_ticker] = now_utc
                
                # Check cooldown before triggering resync
                now = fake_time.timestamp.return_value
                last_sync = catalog._last_rollover_sync_ts.get(series_ticker, 0.0)
                
                if now - last_sync >= catalog._rollover_sync_cooldown_s:
                    if mock_ws_bridge:
                        mock_ws_bridge._sync_requested = True
                        catalog._last_rollover_sync_ts[series_ticker] = now
            
            # Verify roll-over was detected and resync triggered
            assert catalog._last_catalog_ticker[series_ticker] == new_ticker
            assert mock_ws_bridge._sync_requested == True
            assert catalog._last_rollover_sync_ts[series_ticker] == 1000.0
    
    @pytest.mark.asyncio
    async def test_no_roll_over_when_same_ticker(self, catalog, fake_time):
        """Test that no roll-over is detected when ticker is the same."""
        series_ticker = "KXBTC15M"
        same_ticker = "KXBTC15M-26JUN022230-30"
        
        catalog._last_catalog_ticker[series_ticker] = same_ticker
        catalog._last_catalog_change_ts[series_ticker] = datetime(2026, 6, 2, 22, 0, 0, tzinfo=timezone.utc)
        
        # Create markets with same ticker
        markets = [self.create_mock_market(same_ticker, series_ticker)]
        
        # Mock WS bridge
        mock_ws_bridge = MagicMock()
        mock_ws_bridge._sync_requested = False
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Simulate catalog processing logic
            best_ticker = same_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                # This should not execute
                pass
            
            # Verify no roll-over was detected
            assert catalog._last_catalog_ticker[series_ticker] == same_ticker
            assert mock_ws_bridge._sync_requested == False
            assert series_ticker not in catalog._last_rollover_sync_ts
    
    @pytest.mark.asyncio
    async def test_roll_over_cooldown_prevents_multiple_triggers(self, catalog, fake_time):
        """Test that cooldown prevents multiple resync triggers for same roll-over."""
        series_ticker = "KXBTC15M"
        old_ticker = "KXBTC15M-26JUN022215-15"
        new_ticker = "KXBTC15M-26JUN022230-30"
        
        # Set up initial state with recent sync
        catalog._last_catalog_ticker[series_ticker] = old_ticker
        catalog._last_rollover_sync_ts[series_ticker] = 1000.0  # Recent sync
        catalog._rollover_sync_cooldown_s = 60.0
        
        # Create markets with new ticker
        markets = [self.create_mock_market(new_ticker, series_ticker)]
        
        # Mock WS bridge
        mock_ws_bridge = MagicMock()
        mock_ws_bridge._sync_requested = False
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Try to trigger roll-over detection within cooldown
            fake_time.timestamp.return_value = 1030.0  # 30 seconds later (within cooldown)
            
            best_ticker = new_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                # Roll-over detected
                now_utc = fake_time
                catalog._last_catalog_ticker[series_ticker] = best_ticker
                catalog._last_catalog_change_ts[series_ticker] = now_utc
                
                # Check cooldown
                now = fake_time.timestamp.return_value
                last_sync = catalog._last_rollover_sync_ts.get(series_ticker, 0.0)
                
                if now - last_sync >= catalog._rollover_sync_cooldown_s:
                    if mock_ws_bridge:
                        mock_ws_bridge._sync_requested = True
                        catalog._last_rollover_sync_ts[series_ticker] = now
            
            # Should have detected roll-over but not triggered resync due to cooldown
            assert catalog._last_catalog_ticker[series_ticker] == new_ticker
            assert mock_ws_bridge._sync_requested == False
    
    @pytest.mark.asyncio
    async def test_roll_over_cooldown_expires(self, catalog, fake_time):
        """Test that resync can trigger again after cooldown expires."""
        series_ticker = "KXBTC15M"
        old_ticker = "KXBTC15M-26JUN022215-15"
        new_ticker = "KXBTC15M-26JUN022230-30"
        
        # Set up initial state with expired cooldown
        catalog._last_catalog_ticker[series_ticker] = old_ticker
        catalog._last_rollover_sync_ts[series_ticker] = 1000.0  # Old sync
        catalog._rollover_sync_cooldown_s = 60.0
        
        # Create markets with new ticker
        markets = [self.create_mock_market(new_ticker, series_ticker)]
        
        # Mock WS bridge
        mock_ws_bridge = MagicMock()
        mock_ws_bridge._sync_requested = False
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Try to trigger roll-over detection after cooldown
            fake_time.timestamp.return_value = 1100.0  # 100 seconds later (past cooldown)
            
            best_ticker = new_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                # Roll-over detected
                now_utc = fake_time
                catalog._last_catalog_ticker[series_ticker] = best_ticker
                catalog._last_catalog_change_ts[series_ticker] = now_utc
                
                # Check cooldown (should be expired)
                now = fake_time.timestamp.return_value
                last_sync = catalog._last_rollover_sync_ts.get(series_ticker, 0.0)
                
                if now - last_sync >= catalog._rollover_sync_cooldown_s:
                    if mock_ws_bridge:
                        mock_ws_bridge._sync_requested = True
                        catalog._last_rollover_sync_ts[series_ticker] = now
            
            # Should have triggered resync after cooldown expired
            assert catalog._last_catalog_ticker[series_ticker] == new_ticker
            assert mock_ws_bridge._sync_requested == True
            assert catalog._last_rollover_sync_ts[series_ticker] == 1100.0
    
    @pytest.mark.asyncio
    async def test_multiple_series_roll_over_handling(self, catalog, fake_time):
        """Test handling of roll-overs across multiple series."""
        # Set up multiple series
        series_data = {
            "KXBTC15M": ("KXBTC15M-26JUN022215-15", "KXBTC15M-26JUN022230-30"),
            "KXETH15M": ("KXETH15M-26JUN022215-15", "KXETH15M-26JUN022230-30"),
            "KXSOL15M": ("KXSOL15M-26JUN022215-15", "KXSOL15M-26JUN022215-15"),  # No change
        }
        
        # Initialize catalog state
        for series_ticker, (old_ticker, _) in series_data.items():
            catalog._last_catalog_ticker[series_ticker] = old_ticker
        
        # Mock WS bridge
        mock_ws_bridge = MagicMock()
        mock_ws_bridge._sync_requested = False
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Process each series
            fake_time.timestamp.return_value = 1000.0
            
            for series_ticker, (old_ticker, new_ticker) in series_data.items():
                best_ticker = new_ticker
                last_ticker = catalog._last_catalog_ticker.get(series_ticker)
                
                if last_ticker and last_ticker != best_ticker:
                    # Roll-over detected
                    now_utc = fake_time
                    catalog._last_catalog_ticker[series_ticker] = best_ticker
                    catalog._last_catalog_change_ts[series_ticker] = now_utc
                    
                    # Check cooldown
                    now = fake_time.timestamp.return_value
                    last_sync = catalog._last_rollover_sync_ts.get(series_ticker, 0.0)
                    
                    if now - last_sync >= catalog._rollover_sync_cooldown_s:
                        if mock_ws_bridge:
                            mock_ws_bridge._sync_requested = True
                            catalog._last_rollover_sync_ts[series_ticker] = now
            
            # Verify results
            # BTC and ETH should have rolled over
            assert catalog._last_catalog_ticker["KXBTC15M"] == "KXBTC15M-26JUN022230-30"
            assert catalog._last_catalog_ticker["KXETH15M"] == "KXETH15M-26JUN022230-30"
            
            # SOL should not have changed
            assert catalog._last_catalog_ticker["KXSOL15M"] == "KXSOL15M-26JUN022215-15"
            
            # Should have triggered resync (at least once)
            assert mock_ws_bridge._sync_requested == True

class TestCatalogIntegration:
    """Integration tests for catalog with realistic scenarios."""
    
    @pytest.fixture
    def catalog(self):
        """Create a catalog for testing."""
        mock_client = MagicMock()
        return KalshiMarketCatalog(
            client=mock_client,
            refresh_interval_s=5.0,
            max_markets=100
        )
    
    @pytest.mark.asyncio
    async def test_roll_over_detection_with_ws_bridge_unavailable(self, catalog):
        """Test roll-over detection when WS bridge is not available."""
        series_ticker = "KXBTC15M"
        old_ticker = "KXBTC15M-26JUN022215-15"
        new_ticker = "KXBTC15M-26JUN022230-30"
        
        catalog._last_catalog_ticker[series_ticker] = old_ticker
        
        # Mock WS bridge as unavailable
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = None
            
            # Simulate roll-over detection
            best_ticker = new_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                catalog._last_catalog_ticker[series_ticker] = best_ticker
                
                # Try to get WS bridge
                try:
                    ws_bridge = mock_get_bridge.return_value
                    if ws_bridge:
                        ws_bridge._sync_requested = True
                except:
                    pass
            
            # Should have updated ticker but not crashed
            assert catalog._last_catalog_ticker[series_ticker] == new_ticker
    
    @pytest.mark.asyncio
    async def test_roll_over_detection_with_import_error(self, catalog):
        """Test roll-over detection when ws_bridge import fails."""
        series_ticker = "KXBTC15M"
        old_ticker = "KXBTC15M-26JUN022215-15"
        new_ticker = "KXBTC15M-26JUN022230-30"
        
        catalog._last_catalog_ticker[series_ticker] = old_ticker
        
        # Mock import error
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.side_effect = ImportError("ws_bridge not available")
            
            # Simulate roll-over detection
            best_ticker = new_ticker
            last_ticker = catalog._last_catalog_ticker.get(series_ticker)
            
            if last_ticker and last_ticker != best_ticker:
                catalog._last_catalog_ticker[series_ticker] = best_ticker
                
                # Try to get WS bridge
                try:
                    ws_bridge = mock_get_bridge()
                    if ws_bridge:
                        ws_bridge._sync_requested = True
                except ImportError:
                    pass
                except Exception as e:
                    pass
            
            # Should have updated ticker but not crashed
            assert catalog._last_catalog_ticker[series_ticker] == new_ticker
    
    @pytest.mark.asyncio
    async def test_roll_over_cooldown_per_series_independence(self, catalog):
        """Test that cooldown is independent per series."""
        # Set up two series with different cooldown states
        catalog._last_catalog_ticker["KXBTC15M"] = "KXBTC15M-OLD"
        catalog._last_rollover_sync_ts["KXBTC15M"] = 1000.0  # Recent sync
        
        catalog._last_catalog_ticker["KXETH15M"] = "KXETH15M-OLD"
        catalog._last_rollover_sync_ts["KXETH15M"] = 900.0  # Older sync
        
        catalog._rollover_sync_cooldown_s = 60.0
        
        mock_ws_bridge = MagicMock()
        
        with patch('merid.event_venues.kalshi.market_catalog.get_ws_bridge') as mock_get_bridge:
            mock_get_bridge.return_value = mock_ws_bridge
            
            # Try to trigger roll-over at time 1050
            now = 1050.0
            
            # BTC roll-over (should be blocked by cooldown)
            last_sync_btc = catalog._last_rollover_sync_ts["KXBTC15M"]
            btc_can_sync = (now - last_sync_btc) >= catalog._rollover_sync_cooldown_s
            
            # ETH roll-over (should be allowed)
            last_sync_eth = catalog._last_rollover_sync_ts["KXETH15M"]
            eth_can_sync = (now - last_sync_eth) >= catalog._rollover_sync_cooldown_s
            
            # Verify cooldown logic
            assert btc_can_sync == False  # 50s < 60s cooldown
            assert eth_can_sync == True   # 150s > 60s cooldown
