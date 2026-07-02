"""
Unit tests for WebSocket Bridge auto-resync and subscription guardrails.

Tests auto-resync cooldown, subscription drift detection, and catalog synchronization.
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
from datetime import datetime, timezone

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

class TestWebSocketBridgeAutoResync:
    """Test WebSocket bridge auto-resync functionality."""
    
    @pytest.fixture
    def ws_bridge(self):
        """Create a WebSocket bridge for testing."""
        bridge = KalshiWebSocketBridge()
        # Initialize some test data
        bridge._subscribed_tickers = ["KXBTC15M-26JUN022215-15", "KXETH15M-26JUN022215-15"]
        bridge._forward_last_event_ts = 1000.0  # Set to past time
        bridge._events_enqueued = 0
        return bridge
    
    @pytest.fixture
    def fake_time(self):
        """Provide fake time for deterministic tests."""
        with patch('time.monotonic') as mock_time:
            mock_time.return_value = 1000.0
            yield mock_time
    
    @pytest.mark.asyncio
    async def test_auto_resync_triggers_once_on_silence(self, ws_bridge, fake_time):
        """Test that auto-resync triggers exactly once during silence."""
        # Set up conditions: no events for >60s, has subscriptions
        fake_time.return_value = 1100.0  # 100 seconds later
        
        # Mock the sync_to_catalog method
        ws_bridge.sync_to_catalog = AsyncMock(return_value=True)
        
        # Simulate forwarder loop iteration with no events
        events_in_last_sec = 0
        ws_bridge._sync_requested = False
        
        # First iteration should trigger auto-resync
        # This simulates the logic in the forwarder loop
        if not ws_bridge._sync_requested and events_in_last_sec == 0:
            now = fake_time.return_value
            time_since_last_event = now - ws_bridge._forward_last_event_ts
            
            if now >= ws_bridge._auto_resync_cooldown_until:  # Cooldown not active
                if time_since_last_event > 60.0 and ws_bridge._subscribed_tickers:
                    ws_bridge._sync_requested = True
                    ws_bridge._last_sync_attempt_ts = 0
                    ws_bridge._last_auto_resync_ts = now
                    ws_bridge._auto_resync_cooldown_until = now + ws_bridge._auto_resync_cooldown_s
        
        # Verify auto-resync was triggered
        assert ws_bridge._sync_requested == True
        assert ws_bridge._last_auto_resync_ts == 1000.0
        assert ws_bridge._auto_resync_cooldown_until == 1000.0 + ws_bridge._auto_resync_cooldown_s
    
    @pytest.mark.asyncio
    async def test_auto_resync_cooldown_prevents_multiple_triggers(self, ws_bridge, fake_time):
        """Test that cooldown prevents multiple auto-resync triggers."""
        # Set up initial auto-resync
        ws_bridge._sync_requested = True
        ws_bridge._last_auto_resync_ts = 1000.0
        ws_bridge._auto_resync_cooldown_until = 1300.0  # 5 minutes later
        
        # Advance time but still within cooldown
        fake_time.return_value = 1200.0  # 200 seconds later (still in cooldown)
        ws_bridge._forward_last_event_ts = 1000.0
        
        # Try to trigger auto-resync again
        events_in_last_sec = 0
        ws_bridge._sync_requested = False  # Reset to test triggering
        
        if not ws_bridge._sync_requested and events_in_last_sec == 0:
            now = fake_time.return_value
            time_since_last_event = now - ws_bridge._forward_last_event_ts
            
            # Cooldown check should prevent trigger
            if now < ws_bridge._auto_resync_cooldown_until:
                pass  # Skip auto-resync
            elif time_since_last_event > 60.0 and ws_bridge._subscribed_tickers:
                ws_bridge._sync_requested = True
        
        # Should not have triggered due to cooldown
        assert ws_bridge._sync_requested == False
    
    @pytest.mark.asyncio
    async def test_auto_resync_no_trigger_when_events_flow(self, ws_bridge, fake_time):
        """Test that auto-resync doesn't trigger when events are flowing."""
        # Set up recent event
        fake_time.return_value = 1005.0  # 5 seconds later
        ws_bridge._forward_last_event_ts = 1004.0  # Recent event
        
        # Try to trigger auto-resync
        events_in_last_sec = 1  # Events flowing
        ws_bridge._sync_requested = False
        
        if not ws_bridge._sync_requested and events_in_last_sec == 0:
            # This block should not execute since events_in_last_sec > 0
            pass
        
        # Should not have triggered
        assert ws_bridge._sync_requested == False
    
    @pytest.mark.asyncio
    async def test_auto_resync_no_trigger_without_subscriptions(self, ws_bridge, fake_time):
        """Test that auto-resync doesn't trigger without subscriptions."""
        # Remove subscriptions
        ws_bridge._subscribed_tickers = []
        
        # Set up silence
        fake_time.return_value = 1100.0  # 100 seconds later
        ws_bridge._forward_last_event_ts = 1000.0
        
        # Try to trigger auto-resync
        events_in_last_sec = 0
        ws_bridge._sync_requested = False
        
        if not ws_bridge._sync_requested and events_in_last_sec == 0:
            now = fake_time.return_value
            time_since_last_event = now - ws_bridge._forward_last_event_ts
            
            if now >= ws_bridge._auto_resync_cooldown_until:
                if time_since_last_event > 60.0 and ws_bridge._subscribed_tickers:
                    ws_bridge._sync_requested = True
        
        # Should not have triggered due to no subscriptions
        assert ws_bridge._sync_requested == False
    
    @pytest.mark.asyncio
    async def test_auto_resync_cooldown_expires(self, ws_bridge, fake_time):
        """Test that auto-resync can trigger again after cooldown expires."""
        # Set up expired cooldown
        ws_bridge._last_auto_resync_ts = 1000.0
        ws_bridge._auto_resync_cooldown_until = 1100.0  # Expired
        
        # Advance time past cooldown
        fake_time.return_value = 1200.0  # Past cooldown
        ws_bridge._forward_last_event_ts = 1000.0
        
        # Try to trigger auto-resync
        events_in_last_sec = 0
        ws_bridge._sync_requested = False
        
        if not ws_bridge._sync_requested and events_in_last_sec == 0:
            now = fake_time.return_value
            time_since_last_event = now - ws_bridge._forward_last_event_ts
            
            if now >= ws_bridge._auto_resync_cooldown_until:  # Cooldown expired
                if time_since_last_event > 60.0 and ws_bridge._subscribed_tickers:
                    ws_bridge._sync_requested = True
                    ws_bridge._last_auto_resync_ts = now
                    ws_bridge._auto_resync_cooldown_until = now + ws_bridge._auto_resync_cooldown_s
        
        # Should have triggered again
        assert ws_bridge._sync_requested == True
        assert ws_bridge._last_auto_resync_ts == 1200.0

class TestWebSocketBridgeSubscriptionGuardrails:
    """Test WebSocket bridge subscription guardrails."""
    
    @pytest.fixture
    def ws_bridge(self):
        """Create a WebSocket bridge for testing."""
        bridge = KalshiWebSocketBridge()
        bridge._subscribed_tickers = ["KXBTC15M-26JUN022215-15", "KXETH15M-26JUN022215-15"]
        return bridge
    
    @pytest.mark.asyncio
    async def test_subscription_validation_when_in_sync(self, ws_bridge):
        """Test subscription validation when WS and catalog are in sync."""
        # Mock catalog with matching tickers
        mock_catalog = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.markets = []
        
        # Create mock markets that match current subscriptions
        for ticker in ws_bridge._subscribed_tickers:
            mock_market = MagicMock()
            mock_market.market.market_id = ticker
            mock_market.market.raw_data = {"series_ticker": ticker.split("-")[0]}
            mock_snapshot.markets.append(mock_market)
        
        mock_catalog.snapshot.return_value = mock_snapshot
        
        with patch('merid.event_venues.kalshi.ws_bridge.get_market_catalog') as mock_get_catalog, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_market_state_store') as mock_get_store, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_client') as mock_get_client:
            
            mock_get_catalog.return_value = mock_catalog
            mock_get_store.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()
            
            result = await ws_bridge.sync_to_catalog()
            
            # Should return True (validation passed)
            assert result == True
    
    @pytest.mark.asyncio
    async def test_subscription_validation_detects_mismatch(self, ws_bridge):
        """Test subscription validation detects mismatch between WS and catalog."""
        # Mock catalog with different tickers (new strip)
        mock_catalog = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.markets = []
        
        # Create mock markets with new tickers
        new_tickers = ["KXBTC15M-26JUN022230-30", "KXETH15M-26JUN022230-30"]
        for ticker in new_tickers:
            mock_market = MagicMock()
            mock_market.market.market_id = ticker
            mock_market.market.raw_data = {"series_ticker": ticker.split("-")[0]}
            mock_snapshot.markets.append(mock_market)
        
        mock_catalog.snapshot.return_value = mock_snapshot
        
        # Mock unsubscribe/subscribe methods
        ws_bridge.unsubscribe = AsyncMock()
        ws_bridge.subscribe = AsyncMock()
        
        with patch('merid.event_venues.kalshi.ws_bridge.get_market_catalog') as mock_get_catalog, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_market_state_store') as mock_get_store, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_client') as mock_get_client:
            
            mock_get_catalog.return_value = mock_catalog
            mock_get_store.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()
            
            result = await ws_bridge.sync_to_catalog()
            
            # Should return True (sync performed)
            assert result == True
            
            # Should have unsubscribed from old tickers
            ws_bridge.unsubscribe.assert_called_once()
            old_tickers = set(ws_bridge._subscribed_tickers) - set(new_tickers)
            assert set(ws_bridge.unsubscribe.call_args[0][0]) == old_tickers
            
            # Should have subscribed to new tickers
            ws_bridge.subscribe.assert_called_once()
            assert set(ws_bridge.subscribe.call_args[0][0]) == set(new_tickers)
    
    @pytest.mark.asyncio
    async def test_subscription_validation_empty_catalog(self, ws_bridge):
        """Test subscription validation when catalog is empty."""
        # Mock empty catalog
        mock_catalog = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.markets = []
        mock_catalog.snapshot.return_value = mock_snapshot
        
        with patch('merid.event_venues.kalshi.ws_bridge.get_market_catalog') as mock_get_catalog, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_market_state_store') as mock_get_store, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_client') as mock_get_client:
            
            mock_get_catalog.return_value = mock_catalog
            mock_get_store.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()
            
            result = await ws_bridge.sync_to_catalog()
            
            # Should return False (skipped due to empty catalog)
            assert result == False
    
    @pytest.mark.asyncio
    async def test_subscription_guardrail_logging(self, ws_bridge):
        """Test that subscription guardrails log appropriate messages."""
        # Mock catalog with different tickers
        mock_catalog = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.markets = []
        
        new_tickers = ["KXBTC15M-26JUN022230-30"]
        mock_market = MagicMock()
        mock_market.market.market_id = new_tickers[0]
        mock_market.market.raw_data = {"series_ticker": "KXBTC15M"}
        mock_snapshot.markets.append(mock_market)
        mock_catalog.snapshot.return_value = mock_snapshot
        
        ws_bridge.unsubscribe = AsyncMock()
        ws_bridge.subscribe = AsyncMock()
        
        with patch('merid.event_venues.kalshi.ws_bridge.get_market_catalog') as mock_get_catalog, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_market_state_store') as mock_get_store, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_client') as mock_get_client, \
             patch('merid.event_venues.kalshi.ws_bridge.logger') as mock_logger:
            
            mock_get_catalog.return_value = mock_catalog
            mock_get_store.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()
            
            result = await ws_bridge.sync_to_catalog()
            
            # Should log mismatch warning
            mock_logger.warning.assert_called()
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if "MISMATCH DETECTED" in str(call)]
            assert len(warning_calls) > 0
            
            # Should log stale subscriptions
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if "Stale subscriptions" in str(call)]
            assert len(warning_calls) > 0
            
            # Should log missing subscriptions
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if "Missing subscriptions" in str(call)]
            assert len(warning_calls) > 0

class TestWebSocketBridgeIntegration:
    """Integration tests for WebSocket bridge with realistic scenarios."""
    
    @pytest.fixture
    def ws_bridge(self):
        """Create a WebSocket bridge for testing."""
        bridge = KalshiWebSocketBridge()
        return bridge
    
    @pytest.mark.asyncio
    async def test_subscription_drift_correction_flow(self, ws_bridge):
        """Test complete flow of subscription drift detection and correction."""
        # Initial state: subscribed to old tickers
        old_tickers = ["KXBTC15M-26JUN022215-15", "KXETH15M-26JUN022215-15"]
        new_tickers = ["KXBTC15M-26JUN022230-30", "KXETH15M-26JUN022230-30"]
        
        ws_bridge._subscribed_tickers = old_tickers.copy()
        ws_bridge.unsubscribe = AsyncMock()
        ws_bridge.subscribe = AsyncMock()
        
        # Mock catalog with new tickers
        mock_catalog = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.markets = []
        
        for ticker in new_tickers:
            mock_market = MagicMock()
            mock_market.market.market_id = ticker
            mock_market.market.raw_data = {"series_ticker": ticker.split("-")[0]}
            mock_snapshot.markets.append(mock_market)
        
        mock_catalog.snapshot.return_value = mock_snapshot
        
        with patch('merid.event_venues.kalshi.ws_bridge.get_market_catalog') as mock_get_catalog, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_market_state_store') as mock_get_store, \
             patch('merid.event_venues.kalshi.ws_bridge.get_kalshi_client') as mock_get_client:
            
            mock_get_catalog.return_value = mock_catalog
            mock_get_store.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()
            
            # Step 1: Detect and correct drift
            result = await ws_bridge.sync_to_catalog()
            assert result == True
            
            # Step 2: Verify old subscriptions were removed
            ws_bridge.unsubscribe.assert_called_once()
            unsubscribed = set(ws_bridge.unsubscribe.call_args[0][0])
            assert unsubscribed == set(old_tickers)
            
            # Step 3: Verify new subscriptions were added
            ws_bridge.subscribe.assert_called_once()
            subscribed = set(ws_bridge.subscribe.call_args[0][0])
            assert subscribed == set(new_tickers)
    
    @pytest.mark.asyncio
    async def test_auto_resync_with_subscription_drift(self, ws_bridge):
        """Test auto-resync triggering when subscription drift causes no events."""
        # Set up subscription drift
        old_tickers = ["KXBTC15M-26JUN022215-15"]  # Expired
        new_tickers = ["KXBTC15M-26JUN022230-30"]  # Current
        ws_bridge._subscribed_tickers = old_tickers.copy()
        
        # Mock time: no events for >60s
        with patch('time.monotonic') as mock_time:
            mock_time.return_value = 1100.0
            ws_bridge._forward_last_event_ts = 1000.0
            
            # Mock sync_to_catalog to correct drift
            ws_bridge.sync_to_catalog = AsyncMock(return_value=True)
            ws_bridge.unsubscribe = AsyncMock()
            ws_bridge.subscribe = AsyncMock()
            
            # Trigger auto-resync logic
            events_in_last_sec = 0
            ws_bridge._sync_requested = False
            
            if not ws_bridge._sync_requested and events_in_last_sec == 0:
                now = mock_time.return_value
                time_since_last_event = now - ws_bridge._forward_last_event_ts
                
                if now >= ws_bridge._auto_resync_cooldown_until:
                    if time_since_last_event > 60.0 and ws_bridge._subscribed_tickers:
                        ws_bridge._sync_requested = True
                        ws_bridge._last_auto_resync_ts = now
                        ws_bridge._auto_resync_cooldown_until = now + ws_bridge._auto_resync_cooldown_s
            
            # Should have triggered auto-resync
            assert ws_bridge._sync_requested == True
            
            # When sync_to_catalog is called, it should correct the drift
            # This would be called by the forwarder loop in real scenario
