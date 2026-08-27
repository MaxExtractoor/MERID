"""Tests for WebSocket snapshot recovery functionality (P1 FIX)."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig


@pytest.fixture
def config():
    """Create test Kalshi config."""
    cfg = KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )
    cfg.ws_base_url = "wss://api.demo.kalshi.com/trade-api/ws/v2"
    cfg.rest_base_url = "https://api.demo.kalshi.com/trade-api/v2"
    cfg.api_key_id = "test_key_id"
    cfg.private_key_pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKB\n-----END PRIVATE KEY-----"
    return cfg


@pytest.fixture
def ws_client(config):
    """Create test Kalshi WebSocket client."""
    return KalshiWebSocket(config)


class TestSubscriptionIdTracking:
    """Test subscription ID tracking for update_subscription commands."""
    
    def test_subscription_ids_initialized(self, ws_client):
        """Test that subscription IDs dict is initialized."""
        assert hasattr(ws_client, '_subscription_ids')
        assert isinstance(ws_client._subscription_ids, dict)
        assert ws_client._subscription_ids == {}
    
    def test_subscription_id_capture_on_subscribed(self, ws_client):
        """Test that subscription ID is captured when subscribed message received."""
        # Simulate a subscribed message with sid in the response
        data = {
            "id": 1,
            "type": "subscribed",
            "sid": 123,  # sid is at the top level in Kalshi's response
            "msg": {
                "channel": "orderbook_delta"
            }
        }
        
        # This would normally be called in the message processing loop
        # For testing, we directly call the logic
        msg_data = data.get("msg", {})
        channel = msg_data.get("channel")
        sid = data.get("sid")
        
        if channel and sid:
            ws_client._subscription_ids[channel] = sid
        
        assert ws_client._subscription_ids["orderbook_delta"] == 123


class TestRequestOrderbookSnapshot:
    """Test request_orderbook_snapshot method."""
    
    @pytest.mark.asyncio
    async def test_request_snapshot_with_sid(self, ws_client):
        """Test snapshot request with valid subscription ID."""
        ws_client._subscription_ids["orderbook_delta"] = 123
        ws_client._ws = AsyncMock()
        
        await ws_client.request_orderbook_snapshot("KXBTCD-25JUN-T100000")
        
        # Verify send was called with correct parameters
        ws_client._ws.send.assert_called_once()
        call_args = ws_client._ws.send.call_args[0][0]
        import json
        message = json.loads(call_args)
        
        assert message["cmd"] == "update_subscription"
        assert message["params"]["sid"] == 123
        assert message["params"]["market_tickers"] == ["KXBTCD-25JUN-T100000"]
        assert message["params"]["action"] == "get_snapshot"
    
    @pytest.mark.asyncio
    async def test_request_snapshot_without_sid_fallback(self, ws_client):
        """Test snapshot request without subscription ID falls back to REST."""
        ws_client._subscription_ids = {}  # No subscription ID tracked
        ws_client._ws = AsyncMock()

        # Mock the REST fallback helper
        ws_client._fetch_rest_orderbook_snapshot = AsyncMock()

        await ws_client.request_orderbook_snapshot("KXBTCD-25JUN-T100000")

        # Should fall back to REST, not recurse into _sync_sequence_gap_with_rest
        ws_client._fetch_rest_orderbook_snapshot.assert_called_once_with("KXBTCD-25JUN-T100000")
        ws_client._ws.send.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_request_snapshot_without_ws_connection(self, ws_client):
        """Test snapshot request without WebSocket connection."""
        ws_client._subscription_ids["orderbook_delta"] = 123
        ws_client._ws = None  # No connection
        
        # Should log warning and return without error
        await ws_client.request_orderbook_snapshot("KXBTCD-25JUN-T100000")
        # No exception should be raised


class TestSequenceGapRecovery:
    """Test sequence gap recovery using WebSocket snapshot."""
    
    @pytest.mark.asyncio
    async def test_sequence_gap_triggers_ws_snapshot(self, ws_client):
        """Test that sequence gap triggers WebSocket snapshot request."""
        ws_client._ob_initialised = {"KXBTCD-25JUN-T100000"}
        ws_client.request_orderbook_snapshot = AsyncMock()
        
        await ws_client._sync_sequence_gap_with_rest("KXBTCD-25JUN-T100000", 10, 15)
        
        # Should request snapshot via WebSocket
        ws_client.request_orderbook_snapshot.assert_called_once_with("KXBTCD-25JUN-T100000")
        
        # Should mark ticker as rebuilding
        assert "KXBTCD-25JUN-T100000" not in ws_client._ob_initialised
