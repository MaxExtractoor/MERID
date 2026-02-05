"""Additional tests for merid/whales.py WebSocket paths."""

import pytest
import json
import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call
from websockets.exceptions import ConnectionClosed

from merid.whales import (
    WhaleMonitor,
    WhaleMonitorConfig,
    WhaleEvent,
    solana_whale_listener,
    broadcast_whale,
    add_whale_client,
    remove_whale_client,
    get_whale_client_count,
    ws_clients,
)


@pytest.fixture
def ws_config():
    """Create WebSocket test config."""
    return WhaleMonitorConfig(
        solana_ws_url="wss://test.solana.com",
        whale_threshold=1000.0,
        mint_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        initial_backoff_seconds=0.1,
        max_backoff_seconds=1.0,
        max_reconnect_attempts=3
    )


@pytest.fixture
def ws_monitor(ws_config):
    """Create test WhaleMonitor with WebSocket config."""
    return WhaleMonitor(ws_config)


class TestWhaleMonitorWebSocketLifecycle:
    """Test WhaleMonitor WebSocket lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_starts_listener_task(self, ws_monitor):
        """Test start creates listener task."""
        mock_aggregator = MagicMock()
        
        with patch.object(ws_monitor, '_listener_loop', new_callable=AsyncMock) as mock_loop:
            with patch.object(ws_monitor, '_health_check_loop', new_callable=AsyncMock):
                await ws_monitor.start(mock_aggregator)
                
                assert ws_monitor.is_running is True
                assert ws_monitor._listener_task is not None
                mock_loop.assert_called_once_with(mock_aggregator)
    
    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, ws_monitor):
        """Test stop cancels running tasks."""
        ws_monitor._is_running = True
        ws_monitor._listener_task = AsyncMock()
        ws_monitor._health_check_task = AsyncMock()
        ws_monitor._ws_clients.add(AsyncMock())
        
        await ws_monitor.stop()
        
        assert ws_monitor.is_running is False
        assert ws_monitor._shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_stop_with_active_clients(self, ws_monitor):
        """Test stop with active WebSocket clients."""
        mock_ws = AsyncMock()
        ws_monitor._ws_clients.add(mock_ws)
        ws_monitor._is_running = True
        
        await ws_monitor.stop()
        
        assert len(ws_monitor._ws_clients) == 0


class TestWhaleMonitorListenerLoop:
    """Test WhaleMonitor _listener_loop."""
    
    @pytest.mark.asyncio
    async def test_listener_loop_successful_connection(self, ws_monitor):
        """Test listener loop with successful connection."""
        mock_aggregator = MagicMock()
        
        with patch.object(ws_monitor, '_connect_and_listen', new_callable=AsyncMock) as mock_connect:
            with patch.object(ws_monitor, '_shutdown_event') as mock_event:
                mock_event.is_set.side_effect = [False, True]  # Run once then stop
                
                await ws_monitor._listener_loop(mock_aggregator)
                
                mock_connect.assert_called_once_with(mock_aggregator)
                # Backoff should reset on success
                assert ws_monitor._current_backoff == ws_monitor.config.initial_backoff_seconds
    
    @pytest.mark.asyncio
    async def test_listener_loop_websocket_exception(self, ws_monitor):
        """Test listener loop handles WebSocketException."""
        mock_aggregator = MagicMock()
        ws_monitor._current_backoff = 0.1
        
        with patch.object(ws_monitor, '_connect_and_listen', side_effect=ConnectionClosed(None, None)):
            with patch.object(ws_monitor, '_shutdown_event') as mock_event:
                mock_event.is_set.side_effect = [False, False, True]  # Run twice then stop
                with patch.object(ws_monitor, '_backoff', new_callable=AsyncMock) as mock_backoff:
                    await ws_monitor._listener_loop(mock_aggregator)
                    
                    assert mock_backoff.called
    
    @pytest.mark.asyncio
    async def test_listener_loop_max_reconnects(self, ws_monitor):
        """Test listener loop stops at max reconnects."""
        mock_aggregator = MagicMock()
        ws_monitor._reconnect_count = 3
        ws_monitor.config.max_reconnect_attempts = 3
        
        with patch.object(ws_monitor, '_connect_and_listen', side_effect=ConnectionError("Failed")):
            with patch.object(ws_monitor, '_shutdown_event') as mock_event:
                mock_event.is_set.return_value = False
                
                await ws_monitor._listener_loop(mock_aggregator)
                
                # Should stop after max reconnects
                assert ws_monitor._reconnect_count >= ws_monitor.config.max_reconnect_attempts


class TestWhaleMonitorBackoff:
    """Test WhaleMonitor backoff logic."""
    
    @pytest.mark.asyncio
    async def test_backoff_increases_delay(self, ws_monitor):
        """Test backoff increases reconnect delay."""
        ws_monitor._current_backoff = 0.1
        ws_monitor._reconnect_count = 0
        
        with patch.object(ws_monitor._shutdown_event, 'wait', new_callable=AsyncMock):
            await ws_monitor._backoff()
            
            # Delay should increase
            assert ws_monitor._current_backoff > 0.1
            assert ws_monitor._reconnect_count == 1
    
    @pytest.mark.asyncio
    async def test_backoff_respects_max(self, ws_monitor):
        """Test backoff respects max_backoff_seconds."""
        ws_monitor._current_backoff = 0.9  # Close to max of 1.0
        
        with patch.object(ws_monitor._shutdown_event, 'wait', new_callable=AsyncMock):
            await ws_monitor._backoff()
            
            # Should be capped at max
            assert ws_monitor._current_backoff <= ws_monitor.config.max_backoff_seconds


class TestWhaleMonitorMessageProcessing:
    """Test WhaleMonitor message processing."""
    
    @pytest.mark.asyncio
    async def test_process_message_valid_whale(self, ws_monitor):
        """Test processing valid whale message."""
        mock_aggregator = MagicMock()
        
        message = json.dumps({
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {"uiAmount": 5000.0},
                                        "owner": "Owner123"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        })
        
        with patch.object(ws_monitor, '_handle_whale_event', new_callable=AsyncMock) as mock_handle:
            await ws_monitor._process_message(message, mock_aggregator)
            
            mock_handle.assert_called_once_with("Owner123", 5000.0, mock_aggregator)
    
    @pytest.mark.asyncio
    async def test_process_message_below_threshold(self, ws_monitor):
        """Test processing message below whale threshold."""
        mock_aggregator = MagicMock()
        
        message = json.dumps({
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {"uiAmount": 100.0},  # Below 1000 threshold
                                        "owner": "Owner123"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        })
        
        with patch.object(ws_monitor, '_handle_whale_event', new_callable=AsyncMock) as mock_handle:
            await ws_monitor._process_message(message, mock_aggregator)
            
            mock_handle.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self, ws_monitor):
        """Test processing invalid JSON message."""
        mock_aggregator = MagicMock()
        
        with patch('merid.whales.logger') as mock_logger:
            await ws_monitor._process_message("invalid json", mock_aggregator)
            
            mock_logger.warning.assert_called()
    
    @pytest.mark.asyncio
    async def test_process_message_missing_data(self, ws_monitor):
        """Test processing message with missing data."""
        mock_aggregator = MagicMock()
        
        message = json.dumps({
            "params": {
                "result": {
                    "value": {}  # Missing account data
                }
            }
        })
        
        # Should return early without error
        await ws_monitor._process_message(message, mock_aggregator)
    
    @pytest.mark.asyncio
    async def test_handle_whale_event(self, ws_monitor):
        """Test handling whale event."""
        mock_aggregator = MagicMock()
        mock_aggregator.record_whale_event = MagicMock()
        
        ws_monitor._ws_clients.add(AsyncMock())
        
        await ws_monitor._handle_whale_event("Owner123", 5000.0, mock_aggregator)
        
        assert len(ws_monitor._event_history) == 1
        assert ws_monitor._last_event_time is not None
        mock_aggregator.record_whale_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_whale_event_no_aggregator(self, ws_monitor):
        """Test handling whale event without aggregator."""
        ws_monitor._ws_clients.add(AsyncMock())
        
        await ws_monitor._handle_whale_event("Owner123", 5000.0, None)
        
        assert len(ws_monitor._event_history) == 1


class TestWhaleMonitorBroadcast:
    """Test WhaleMonitor broadcast functionality."""
    
    @pytest.mark.asyncio
    async def test_broadcast_to_clients(self, ws_monitor):
        """Test broadcasting to multiple clients."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        ws_monitor._ws_clients.add(mock_ws1)
        ws_monitor._ws_clients.add(mock_ws2)
        
        alert = {"type": "whale", "amount": 5000.0}
        await ws_monitor._broadcast(alert)
        
        mock_ws1.send_json.assert_called_once_with(alert)
        mock_ws2.send_json.assert_called_once_with(alert)
    
    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self, ws_monitor):
        """Test broadcast removes dead clients."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = ConnectionClosed(None, None)
        ws_monitor._ws_clients.add(mock_ws)
        
        alert = {"type": "whale", "amount": 5000.0}
        await ws_monitor._broadcast(alert)
        
        # Dead client should be removed
        assert mock_ws not in ws_monitor._ws_clients
    
    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self, ws_monitor):
        """Test broadcast with no clients."""
        alert = {"type": "whale", "amount": 5000.0}
        
        # Should not raise
        await ws_monitor._broadcast(alert)


class TestWhaleMonitorHealthCheck:
    """Test WhaleMonitor health check functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_loop_logs_status(self, ws_monitor):
        """Test health check loop logs status."""
        ws_monitor._is_running = True
        ws_monitor._last_event_time = datetime.utcnow()
        ws_monitor._event_history.append(MagicMock())
        
        with patch.object(ws_monitor._shutdown_event, 'wait', side_effect=[
            asyncio.TimeoutError(),  # First iteration times out
            asyncio.TimeoutError(),  # Second iteration times out
            None  # Third iteration stops
        ]):
            with patch.object(ws_monitor, '_log_health_status') as mock_log:
                await ws_monitor._health_check_loop()
                
                mock_log.assert_called()
    
    def test_log_health_status(self, ws_monitor):
        """Test health status logging."""
        ws_monitor._is_running = True
        ws_monitor._last_event_time = datetime.utcnow()
        ws_monitor._event_history.append(MagicMock())
        
        with patch('merid.whales.logger') as mock_logger:
            ws_monitor._log_health_status()
            
            mock_logger.debug.assert_called_once()
            log_call = mock_logger.debug.call_args[0][0]
            assert "running" in log_call
            assert "clients" in log_call


class TestWhaleLegacyAPI:
    """Test legacy whale API functions."""
    
    @pytest.mark.asyncio
    async def test_solana_whale_listener(self):
        """Test legacy solana_whale_listener function."""
        with patch('merid.whales.get_whale_monitor') as mock_get_monitor:
            mock_monitor = AsyncMock()
            mock_monitor.is_running = True
            mock_get_monitor.return_value = mock_monitor
            
            # Cancel after first iteration
            async def cancel_soon():
                await asyncio.sleep(0.1)
                raise asyncio.CancelledError()
            
            with pytest.raises(asyncio.CancelledError):
                await solana_whale_listener()
            
            mock_monitor.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_whale_legacy(self):
        """Test legacy broadcast_whale function."""
        with patch('merid.whales.get_whale_monitor') as mock_get_monitor:
            mock_monitor = AsyncMock()
            mock_get_monitor.return_value = mock_monitor
            
            alert = {"type": "whale"}
            await broadcast_whale(alert)
            
            mock_monitor._broadcast.assert_called_once_with(alert)
    
    def test_add_whale_client_legacy(self):
        """Test legacy add_whale_client function."""
        mock_ws = MagicMock()
        
        with patch('merid.whales.get_whale_monitor') as mock_get_monitor:
            mock_monitor = MagicMock()
            mock_get_monitor.return_value = mock_monitor
            
            add_whale_client(mock_ws)
            
            assert mock_ws in ws_clients
            mock_monitor.add_client.assert_called_once_with(mock_ws)
    
    def test_remove_whale_client_legacy(self):
        """Test legacy remove_whale_client function."""
        mock_ws = MagicMock()
        ws_clients.add(mock_ws)
        
        with patch('merid.whales.get_whale_monitor') as mock_get_monitor:
            mock_monitor = MagicMock()
            mock_monitor.return_value = mock_monitor
            
            remove_whale_client(mock_ws)
            
            assert mock_ws not in ws_clients
            mock_monitor.remove_client.assert_called_once_with(mock_ws)
    
    def test_get_whale_client_count_legacy(self):
        """Test legacy get_whale_client_count function."""
        with patch('merid.whales.get_whale_monitor') as mock_get_monitor:
            mock_monitor = MagicMock()
            mock_monitor.client_count = 5
            mock_get_monitor.return_value = mock_monitor
            
            count = get_whale_client_count()
            
            assert count == 5


class TestWhaleEvent:
    """Test WhaleEvent dataclass."""
    
    def test_whale_event_creation(self):
        """Test WhaleEvent creation."""
        event = WhaleEvent(
            mint="mint123",
            owner="owner456",
            amount=5000.0,
            threshold=1000.0
        )
        
        assert event.mint == "mint123"
        assert event.owner == "owner456"
        assert event.amount == 5000.0
        assert event.threshold == 1000.0
        assert event.timestamp is not None
    
    def test_whale_event_to_dict(self):
        """Test WhaleEvent to_dict method."""
        event = WhaleEvent(
            mint="mint123",
            owner="owner456",
            amount=5000.0,
            threshold=1000.0
        )
        
        data = event.to_dict()
        
        assert data["mint"] == "mint123"
        assert data["owner"] == "owner456"
        assert data["amount"] == 5000.0
        assert data["threshold"] == 1000.0
        assert "timestamp" in data
        assert "is_whale" in data
        assert data["is_whale"] is True
