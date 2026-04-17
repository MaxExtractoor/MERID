"""Tests for MERID whales module - Batch 28 Coverage."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, Mock
import asyncio
import json
from datetime import datetime

from merid.whales import (
    WhaleEvent,
    WhaleMonitorConfig,
    WhaleMonitor,
    get_whale_monitor,
    get_sentry_transaction,
    get_sentry_span,
    capture_sentry_exception,
    add_whale_client,
    remove_whale_client,
    get_whale_client_count,
    ws_clients
)


class TestSentryHelpers:
    """Tests for Sentry helper functions."""

    def test_get_sentry_transaction_no_sentry(self):
        """Test transaction helper when Sentry is not available."""
        with patch('merid.whales.start_transaction', None):
            ctx = get_sentry_transaction()
            # Should return nullcontext which is a context manager
            with ctx:
                pass  # Should work without error

    def test_get_sentry_span_no_sentry(self):
        """Test span helper when Sentry is not available."""
        with patch('merid.whales.start_span', None):
            ctx = get_sentry_span()
            with ctx:
                pass  # Should work without error

    def test_capture_sentry_exception_no_sentry(self):
        """Test exception capture when Sentry is not available."""
        with patch('merid.whales.sentry_sdk', None):
            try:
                raise ValueError("Test error")
            except Exception as e:
                # Should not raise
                capture_sentry_exception(e)


class TestWhaleEvent:
    """Tests for WhaleEvent dataclass."""

    def test_event_creation(self):
        event = WhaleEvent(
            mint="MintAddress123",
            owner="OwnerAddress456",
            amount=150000.0,
            threshold=100000.0
        )
        assert event.mint == "MintAddress123"
        assert event.owner == "OwnerAddress456"
        assert event.amount == 150000.0
        assert event.event_type == "whale"
        assert event.threshold == 100000.0
        assert isinstance(event.timestamp, datetime)

    def test_event_to_dict(self):
        event = WhaleEvent(
            mint="MintAddress123",
            owner="OwnerAddress456",
            amount=150000.0,
            threshold=100000.0
        )
        d = event.to_dict()
        assert d["type"] == "whale"
        assert d["mint"] == "MintAddress123"
        assert d["owner"] == "OwnerAddress456"
        assert d["amount"] == 150000.0
        assert d["threshold"] == 100000.0
        assert "timestamp" in d


class TestWhaleMonitorConfig:
    """Tests for WhaleMonitorConfig dataclass."""

    def test_default_config(self):
        config = WhaleMonitorConfig()
        assert config.solana_ws_url == "wss://api.mainnet-beta.solana.com"
        assert config.mint_address == "Base58MintPubkeyHere"
        assert config.whale_threshold == 100000.0
        assert config.spl_token_program == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

    def test_backoff_config(self):
        config = WhaleMonitorConfig()
        assert config.initial_backoff_seconds == 1.0
        assert config.max_backoff_seconds == 60.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_health_config(self):
        config = WhaleMonitorConfig()
        assert config.health_check_interval_seconds == 30.0
        assert config.connection_timeout_seconds == 10.0
        assert config.max_reconnect_attempts is None


class TestWhaleMonitor:
    """Tests for WhaleMonitor class."""

    @pytest.fixture
    def monitor(self):
        return WhaleMonitor()

    def test_initialization(self, monitor):
        assert monitor.config is not None
        assert monitor.client_count == 0
        assert monitor.is_running is False
        assert monitor.last_event_time is None

    def test_add_client(self, monitor):
        mock_ws = MagicMock()
        monitor.add_client(mock_ws)
        assert monitor.client_count == 1

    def test_remove_client(self, monitor):
        mock_ws = MagicMock()
        monitor.add_client(mock_ws)
        monitor.remove_client(mock_ws)
        assert monitor.client_count == 0

    def test_remove_nonexistent_client(self, monitor):
        mock_ws = MagicMock()
        # Should not raise
        monitor.remove_client(mock_ws)
        assert monitor.client_count == 0

    def test_get_recent_events_empty(self, monitor):
        events = monitor.get_recent_events()
        assert events == []

    def test_get_recent_events(self, monitor):
        event1 = WhaleEvent(mint="mint1", owner="owner1", amount=150000.0)
        event2 = WhaleEvent(mint="mint2", owner="owner2", amount=200000.0)
        monitor._event_history.append(event1)
        monitor._event_history.append(event2)
        
        events = monitor.get_recent_events(count=10)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_start_stop(self, monitor):
        # Mock the listener and health check loops
        with patch.object(monitor, '_listener_loop', new_callable=AsyncMock):
            with patch.object(monitor, '_health_check_loop', new_callable=AsyncMock):
                await monitor.start()
                assert monitor.is_running is True
                
                await monitor.stop()
                assert monitor.is_running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, monitor):
        monitor._is_running = True
        # Should not raise and should not create new tasks
        await monitor.start()
        assert monitor._listener_task is None

    @pytest.mark.asyncio
    async def test_stop_not_running(self, monitor):
        # Should not raise
        await monitor.stop()
        assert monitor.is_running is False

    @pytest.mark.asyncio
    async def test_handle_whale_event(self, monitor):
        mock_ws = AsyncMock()
        monitor.add_client(mock_ws)
        
        await monitor._handle_whale_event("owner123", 150000.0, None)
        
        assert monitor.last_event_time is not None
        assert len(monitor._event_history) == 1
        mock_ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_whale_event_no_clients(self, monitor):
        # Should not raise even with no clients
        await monitor._handle_whale_event("owner123", 150000.0, None)
        assert len(monitor._event_history) == 1

    @pytest.mark.asyncio
    async def test_broadcast_with_dead_client(self, monitor):
        from websockets.exceptions import ConnectionClosed
        dead_ws = AsyncMock()
        dead_ws.send_json.side_effect = ConnectionClosed(None, None)
        live_ws = AsyncMock()
        
        monitor.add_client(dead_ws)
        monitor.add_client(live_ws)
        
        await monitor._broadcast({"test": "alert"})
        
        # Dead client should be removed
        assert monitor.client_count == 1
        live_ws.send_json.assert_called_once()

    def test_log_health_status(self, monitor):
        # Should not raise
        monitor._log_health_status()

    def test_log_health_status_with_events(self, monitor):
        event = WhaleEvent(mint="mint1", owner="owner1", amount=150000.0)
        monitor._event_history.append(event)
        monitor._last_event_time = datetime.utcnow()
        # Should not raise
        monitor._log_health_status()


class TestGetWhaleMonitor:
    """Tests for get_whale_monitor singleton."""

    def test_singleton(self):
        # Reset singleton for test
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        monitor1 = get_whale_monitor()
        monitor2 = get_whale_monitor()
        
        assert monitor1 is monitor2

    def test_singleton_with_config(self):
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        config = WhaleMonitorConfig(whale_threshold=50000.0)
        monitor = get_whale_monitor(config)
        
        assert monitor.config.whale_threshold == 50000.0


class TestLegacyAPI:
    """Tests for legacy API functions."""

    def test_add_whale_client(self):
        import merid.whales as whales_module
        whales_module._default_monitor = None
        ws_clients.clear()
        
        mock_ws = MagicMock()
        add_whale_client(mock_ws)
        
        assert mock_ws in ws_clients
        assert get_whale_client_count() == 1

    def test_remove_whale_client(self):
        import merid.whales as whales_module
        whales_module._default_monitor = None
        ws_clients.clear()
        
        mock_ws = MagicMock()
        add_whale_client(mock_ws)
        remove_whale_client(mock_ws)
        
        assert mock_ws not in ws_clients
        assert get_whale_client_count() == 0

    def test_get_whale_client_count(self):
        import merid.whales as whales_module
        whales_module._default_monitor = None
        ws_clients.clear()
        
        assert get_whale_client_count() == 0
        
        mock_ws = MagicMock()
        add_whale_client(mock_ws)
        
        assert get_whale_client_count() == 1


class TestWhaleMonitorProcessMessage:
    """Tests for message processing."""

    @pytest.fixture
    def monitor(self):
        return WhaleMonitor()

    @pytest.mark.asyncio
    async def test_process_message_valid_whale(self, monitor):
        message = json.dumps({
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {"uiAmount": 150000.0},
                                        "owner": "Owner123"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        })
        
        with patch.object(monitor, '_handle_whale_event', new_callable=AsyncMock) as mock_handle:
            await monitor._process_message(message, None)
            mock_handle.assert_called_once_with("Owner123", 150000.0, None)

    @pytest.mark.asyncio
    async def test_process_message_below_threshold(self, monitor):
        message = json.dumps({
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {"uiAmount": 50000.0},  # Below threshold
                                        "owner": "Owner123"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        })
        
        with patch.object(monitor, '_handle_whale_event', new_callable=AsyncMock) as mock_handle:
            await monitor._process_message(message, None)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self, monitor):
        # Should not raise
        await monitor._process_message("invalid json", None)

    @pytest.mark.asyncio
    async def test_process_message_missing_data(self, monitor):
        message = json.dumps({"invalid": "structure"})
        # Should not raise
        await monitor._process_message(message, None)
