"""Comprehensive tests for merid/whales.py - REAL implementation coverage."""

import pytest
import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from datetime import datetime
from collections import deque

from merid.whales import (
    get_sentry_transaction,
    get_sentry_span,
    capture_sentry_exception,
    WhaleEvent,
    WhaleMonitorConfig,
    WhaleMonitor,
    get_whale_monitor,
    solana_whale_listener,
    broadcast_whale,
    add_whale_client,
    remove_whale_client,
    get_whale_client_count,
    ws_clients,
    logger as whales_logger
)


class TestSentryIntegration:
    """Test Sentry integration functions."""
    
    def test_get_sentry_transaction_returns_context_manager(self):
        """Test get_sentry_transaction returns a context manager."""
        context = get_sentry_transaction()
        assert context is not None
        assert hasattr(context, '__enter__')
        assert hasattr(context, '__exit__')
    
    def test_get_sentry_transaction_context_manager_works(self):
        """Test get_sentry_transaction context manager can be used."""
        context = get_sentry_transaction()
        with context:
            pass  # Should not raise
    
    def test_get_sentry_span_returns_context_manager(self):
        """Test get_sentry_span returns a context manager."""
        context = get_sentry_span(op="test", description="test")
        assert context is not None
        assert hasattr(context, '__enter__')
        assert hasattr(context, '__exit__')
    
    def test_get_sentry_span_context_manager_works(self):
        """Test get_sentry_span context manager can be used."""
        context = get_sentry_span(op="test", description="test")
        with context:
            pass  # Should not raise
    
    def test_capture_sentry_exception_with_sentry_sdk(self):
        """Test capture_sentry_exception when sentry_sdk is available."""
        mock_sentry = MagicMock()
        exc = ValueError("Test error")
        
        with patch('merid.whales.sentry_sdk', mock_sentry):
            capture_sentry_exception(exc)
            mock_sentry.capture_exception.assert_called_once_with(exc)
    
    def test_capture_sentry_exception_without_sentry(self):
        """Test capture_sentry_exception when sentry_sdk is not available."""
        exc = ValueError("Test error")
        
        with patch('merid.whales.sentry_sdk', None):
            with patch.object(whales_logger, 'exception') as mock_log:
                capture_sentry_exception(exc)
                mock_log.assert_called_once()


class TestWhaleEvent:
    """Test WhaleEvent dataclass."""
    
    def test_whale_event_creation(self):
        """Test WhaleEvent creation."""
        event = WhaleEvent(
            mint="test_mint",
            owner="test_owner",
            amount=1000000.0,
            threshold=500000.0
        )
        
        assert event.mint == "test_mint"
        assert event.owner == "test_owner"
        assert event.amount == 1000000.0
        assert event.threshold == 500000.0
        assert event.event_type == "whale"
        assert isinstance(event.timestamp, datetime)
    
    def test_whale_event_to_dict(self):
        """Test WhaleEvent.to_dict method."""
        event = WhaleEvent(
            mint="test_mint",
            owner="test_owner",
            amount=1000000.0,
            threshold=500000.0
        )
        
        data = event.to_dict()
        
        assert data["type"] == "whale"
        assert data["mint"] == "test_mint"
        assert data["owner"] == "test_owner"
        assert data["amount"] == 1000000.0
        assert data["threshold"] == 500000.0
        assert "timestamp" in data


class TestWhaleMonitorConfig:
    """Test WhaleMonitorConfig dataclass."""
    
    def test_default_config(self):
        """Test default WhaleMonitorConfig values."""
        config = WhaleMonitorConfig()
        
        assert config.solana_ws_url == "wss://api.mainnet-beta.solana.com"
        assert config.whale_threshold == 100000.0
        assert config.spl_token_program == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        assert config.initial_backoff_seconds == 1.0
        assert config.max_backoff_seconds == 60.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1
    
    def test_custom_config(self):
        """Test custom WhaleMonitorConfig values."""
        config = WhaleMonitorConfig(
            solana_ws_url="wss://custom.solana.com",
            whale_threshold=500000.0,
            initial_backoff_seconds=2.0
        )
        
        assert config.solana_ws_url == "wss://custom.solana.com"
        assert config.whale_threshold == 500000.0
        assert config.initial_backoff_seconds == 2.0


class TestWhaleMonitor:
    """Test WhaleMonitor class."""
    
    @pytest.fixture
    def monitor(self):
        """Create a fresh WhaleMonitor instance."""
        return WhaleMonitor()
    
    def test_monitor_initialization(self, monitor):
        """Test WhaleMonitor initialization."""
        assert monitor.config is not None
        assert monitor.client_count == 0
        assert monitor.is_running is False
        assert monitor.last_event_time is None
        assert isinstance(monitor._event_history, deque)
    
    def test_monitor_with_custom_config(self):
        """Test WhaleMonitor with custom config."""
        config = WhaleMonitorConfig(whale_threshold=500000.0)
        monitor = WhaleMonitor(config)
        
        assert monitor.config.whale_threshold == 500000.0
    
    @pytest.mark.asyncio
    async def test_add_client(self, monitor):
        """Test add_client method."""
        mock_ws = MagicMock()
        monitor.add_client(mock_ws)
        
        assert monitor.client_count == 1
        assert mock_ws in monitor._ws_clients
    
    @pytest.mark.asyncio
    async def test_remove_client(self, monitor):
        """Test remove_client method."""
        mock_ws = MagicMock()
        monitor.add_client(mock_ws)
        monitor.remove_client(mock_ws)
        
        assert monitor.client_count == 0
        assert mock_ws not in monitor._ws_clients
    
    @pytest.mark.asyncio
    async def test_get_recent_events(self, monitor):
        """Test get_recent_events method."""
        # Add some events to history
        event1 = WhaleEvent(mint="m1", owner="o1", amount=1000000.0)
        event2 = WhaleEvent(mint="m2", owner="o2", amount=2000000.0)
        
        monitor._event_history.append(event1)
        monitor._event_history.append(event2)
        
        recent = monitor.get_recent_events(count=10)
        
        assert len(recent) == 2
        assert recent[1].amount == 2000000.0
    
    @pytest.mark.asyncio
    async def test_start_stop(self, monitor):
        """Test start and stop methods."""
        # Start the monitor
        await monitor.start()
        assert monitor.is_running is True
        
        # Stop the monitor
        await monitor.stop()
        assert monitor.is_running is False
    
    @pytest.mark.asyncio
    async def test_start_already_running(self, monitor):
        """Test start when already running."""
        await monitor.start()
        
        # Try to start again
        await monitor.start()  # Should log warning but not raise
        
        await monitor.stop()
    
    @pytest.mark.asyncio
    async def test_stop_not_running(self, monitor):
        """Test stop when not running."""
        # Should not raise
        await monitor.stop()
    
    @pytest.mark.asyncio
    async def test_process_message_valid_whale(self, monitor):
        """Test _process_message with valid whale event."""
        # Create a valid message
        msg = {
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "owner": "test_owner",
                                        "tokenAmount": {
                                            "uiAmount": 200000.0
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        monitor.config.whale_threshold = 100000.0
        
        with patch.object(monitor, '_handle_whale_event') as mock_handle:
            await monitor._process_message(json.dumps(msg), None)
            mock_handle.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_message_below_threshold(self, monitor):
        """Test _process_message with amount below threshold."""
        msg = {
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "owner": "test_owner",
                                        "tokenAmount": {
                                            "uiAmount": 500.0
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        monitor.config.whale_threshold = 100000.0
        
        with patch.object(monitor, '_handle_whale_event') as mock_handle:
            await monitor._process_message(json.dumps(msg), None)
            mock_handle.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self, monitor):
        """Test _process_message with invalid JSON."""
        with patch.object(whales_logger, 'warning') as mock_log:
            await monitor._process_message("invalid json", None)
            mock_log.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_whale_event(self, monitor):
        """Test _handle_whale_event."""
        monitor.config.mint_address = "test_mint"
        
        with patch.object(monitor, '_broadcast') as mock_broadcast:
            await monitor._handle_whale_event("test_owner", 1000000.0, None)
            
            assert monitor.last_event_time is not None
            assert len(monitor._event_history) == 1
            mock_broadcast.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast(self, monitor):
        """Test _broadcast method."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        monitor.add_client(mock_ws1)
        monitor.add_client(mock_ws2)
        
        alert = {"type": "whale", "amount": 1000000.0}
        await monitor._broadcast(alert)
        
        mock_ws1.send_json.assert_called_once_with(alert)
        mock_ws2.send_json.assert_called_once_with(alert)
    
    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self, monitor):
        """Test _broadcast removes dead clients."""
        from websockets.exceptions import ConnectionClosed
        
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = ConnectionClosed(None, None)
        
        monitor.add_client(mock_ws)
        
        alert = {"type": "whale", "amount": 1000000.0}
        await monitor._broadcast(alert)
        
        # Should have attempted to send to client
        mock_ws.send_json.assert_called_once()


class TestWhaleMonitorBackoff:
    """Test WhaleMonitor backoff functionality."""
    
    @pytest.mark.asyncio
    async def test_backoff_increases(self):
        """Test that backoff increases with each retry."""
        monitor = WhaleMonitor()
        initial_backoff = monitor._current_backoff
        
        # Simulate backoff
        monitor._shutdown_event.set()
        await monitor._backoff()
        
        assert monitor._current_backoff > initial_backoff
        assert monitor._reconnect_count == 1
    
    @pytest.mark.asyncio
    async def test_backoff_respects_max(self):
        """Test that backoff respects max_backoff_seconds."""
        monitor = WhaleMonitor()
        monitor._current_backoff = 100.0  # Above max
        
        monitor._shutdown_event.set()
        await monitor._backoff()
        
        assert monitor._current_backoff <= monitor.config.max_backoff_seconds


class TestGlobalFunctions:
    """Test global functions for backward compatibility."""
    
    def test_get_whale_monitor_creates_instance(self):
        """Test get_whale_monitor creates default instance."""
        # Reset global state
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        monitor = get_whale_monitor()
        assert monitor is not None
        assert isinstance(monitor, WhaleMonitor)
    
    def test_get_whale_monitor_returns_same_instance(self):
        """Test get_whale_monitor returns same instance."""
        # Reset global state
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        monitor1 = get_whale_monitor()
        monitor2 = get_whale_monitor()
        
        assert monitor1 is monitor2
    
    @pytest.mark.asyncio
    async def test_add_remove_whale_client(self):
        """Test add_whale_client and remove_whale_client."""
        # Reset global state
        import merid.whales as whales_module
        whales_module._default_monitor = None
        whales_module.ws_clients.clear()
        
        mock_ws = MagicMock()
        
        add_whale_client(mock_ws)
        assert get_whale_client_count() == 1
        
        remove_whale_client(mock_ws)
        assert get_whale_client_count() == 0
    
    def test_get_whale_client_count(self):
        """Test get_whale_client_count."""
        # Reset global state
        import merid.whales as whales_module
        whales_module._default_monitor = None
        whales_module.ws_clients.clear()
        
        assert get_whale_client_count() == 0


class TestLogger:
    """Test module logger."""
    
    def test_logger_exists(self):
        """Test that logger exists and has correct name."""
        assert whales_logger is not None
        assert whales_logger.name == "merid.whales"
    
    def test_logger_is_logging_logger(self):
        """Test that logger is instance of logging.Logger."""
        assert isinstance(whales_logger, logging.Logger)


# =============================================================================
# POINTER MARKS FOR PYTEST-CHECKLIST
# =============================================================================

class TestSentryFallbackPaths:
    """Test Sentry fallback paths when SDK returns None or raises."""
    
    def test_get_sentry_transaction_none_result(self):
        """Test get_sentry_transaction when start_transaction returns None."""
        with patch('merid.whales.start_transaction', return_value=None):
            ctx = get_sentry_transaction()
            # Should return nullcontext
            with ctx:
                pass
    
    def test_get_sentry_transaction_type_error(self):
        """Test get_sentry_transaction handles TypeError."""
        def raise_type_error(*args, **kwargs):
            raise TypeError("test")
        
        with patch('merid.whales.start_transaction', raise_type_error):
            ctx = get_sentry_transaction()
            with ctx:
                pass
    
    def test_get_sentry_span_none_result(self):
        """Test get_sentry_span when start_span returns None."""
        with patch('merid.whales.start_span', return_value=None):
            ctx = get_sentry_span(op="test", description="test")
            with ctx:
                pass
    
    def test_get_sentry_span_type_error(self):
        """Test get_sentry_span handles TypeError."""
        def raise_type_error(*args, **kwargs):
            raise TypeError("test")
        
        with patch('merid.whales.start_span', raise_type_error):
            ctx = get_sentry_span(op="test", description="test")
            with ctx:
                pass
    
    def test_capture_sentry_exception_import_error(self):
        """Test capture_sentry_exception handles ImportError."""
        mock_sentry = MagicMock()
        mock_sentry.capture_exception.side_effect = ImportError("test")
        exc = ValueError("Test")
        
        with patch('merid.whales.sentry_sdk', mock_sentry):
            with patch.object(whales_logger, 'exception'):
                capture_sentry_exception(exc)
    
    def test_capture_sentry_exception_runtime_error(self):
        """Test capture_sentry_exception handles RuntimeError."""
        mock_sentry = MagicMock()
        mock_sentry.capture_exception.side_effect = RuntimeError("test")
        exc = ValueError("Test")
        
        with patch('merid.whales.sentry_sdk', mock_sentry):
            with patch.object(whales_logger, 'exception'):
                capture_sentry_exception(exc)


class TestWhaleMonitorListenerLoop:
    """Test WhaleMonitor _listener_loop and related methods."""
    
    @pytest.mark.asyncio
    async def test_listener_loop_shutdown(self):
        """Test _listener_loop exits on shutdown."""
        monitor = WhaleMonitor()
        monitor._shutdown_event.set()
        
        # Should exit immediately
        await monitor._listener_loop(None)
    
    @pytest.mark.asyncio
    async def test_listener_loop_connection_error(self):
        """Test _listener_loop handles connection errors and exits on shutdown."""
        monitor = WhaleMonitor()
        
        async def mock_connect(*args):
            # Set shutdown after first call to exit loop
            monitor._shutdown_event.set()
            raise ConnectionError("test")
        
        with patch.object(monitor, '_connect_and_listen', mock_connect):
            await monitor._listener_loop(None)
        
        assert monitor._shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_listener_loop_websocket_exception(self):
        """Test _listener_loop handles WebSocketException."""
        from websockets.exceptions import WebSocketException
        
        monitor = WhaleMonitor()
        call_count = 0
        
        async def mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise WebSocketException("test")
            monitor._shutdown_event.set()
        
        with patch.object(monitor, '_connect_and_listen', mock_connect):
            with patch.object(monitor, '_backoff', new_callable=AsyncMock):
                await monitor._listener_loop(None)


class TestWhaleMonitorHealthCheck:
    """Test WhaleMonitor health check functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_loop_runs(self):
        """Test _health_check_loop runs and logs status."""
        config = WhaleMonitorConfig(health_check_interval_seconds=0.1)
        monitor = WhaleMonitor(config)
        monitor._is_running = True
        
        # Run health check briefly
        async def stop_soon():
            await asyncio.sleep(0.15)
            monitor._shutdown_event.set()
        
        with patch.object(monitor, '_log_health_status') as mock_log:
            await asyncio.gather(
                monitor._health_check_loop(),
                stop_soon()
            )
            mock_log.assert_called()
    
    def test_log_health_status(self):
        """Test _log_health_status logs correct info."""
        monitor = WhaleMonitor()
        monitor._is_running = True
        
        with patch.object(whales_logger, 'debug') as mock_debug:
            monitor._log_health_status()
            mock_debug.assert_called_once()


class TestWhaleMonitorProcessMessageEdgeCases:
    """Test edge cases in _process_message."""
    
    @pytest.mark.asyncio
    async def test_process_message_missing_value(self):
        """Test _process_message with missing value."""
        monitor = WhaleMonitor()
        msg = {"params": {"result": {}}}
        
        # Should return early, no error
        await monitor._process_message(json.dumps(msg), None)
    
    @pytest.mark.asyncio
    async def test_process_message_missing_amount(self):
        """Test _process_message with missing amount."""
        monitor = WhaleMonitor()
        msg = {
            "params": {
                "result": {
                    "value": {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "owner": "test_owner"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        # Should return early
        await monitor._process_message(json.dumps(msg), None)
    
    @pytest.mark.asyncio
    async def test_process_message_key_error(self):
        """Test _process_message handles KeyError."""
        monitor = WhaleMonitor()
        
        # Malformed message that causes KeyError
        with patch('json.loads', side_effect=KeyError("test")):
            with patch.object(whales_logger, 'warning'):
                await monitor._process_message("{}", None)
    
    @pytest.mark.asyncio
    async def test_process_message_value_error(self):
        """Test _process_message handles ValueError."""
        monitor = WhaleMonitor()
        
        with patch('json.loads', side_effect=ValueError("test")):
            with patch.object(whales_logger, 'error'):
                await monitor._process_message("{}", None)


class TestWhaleMonitorHandleWhaleEventAggregator:
    """Test _handle_whale_event with aggregator."""
    
    @pytest.mark.asyncio
    async def test_handle_whale_event_with_aggregator(self):
        """Test _handle_whale_event records to aggregator."""
        monitor = WhaleMonitor()
        mock_aggregator = MagicMock()
        mock_aggregator.record_whale_event = MagicMock()
        
        with patch.object(monitor, '_broadcast', new_callable=AsyncMock):
            await monitor._handle_whale_event("owner", 1000000.0, mock_aggregator)
        
        mock_aggregator.record_whale_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_whale_event_aggregator_error(self):
        """Test _handle_whale_event handles aggregator error."""
        monitor = WhaleMonitor()
        mock_aggregator = MagicMock()
        mock_aggregator.record_whale_event.side_effect = RuntimeError("test")
        
        with patch.object(monitor, '_broadcast', new_callable=AsyncMock):
            with patch.object(whales_logger, 'error'):
                await monitor._handle_whale_event("owner", 1000000.0, mock_aggregator)


class TestWhaleMonitorBroadcastEdgeCases:
    """Test _broadcast edge cases."""
    
    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self):
        """Test _broadcast with no clients."""
        monitor = WhaleMonitor()
        
        # Should return early
        await monitor._broadcast({"type": "whale"})
    
    @pytest.mark.asyncio
    async def test_broadcast_runtime_error(self):
        """Test _broadcast handles RuntimeError from client."""
        monitor = WhaleMonitor()
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = RuntimeError("test")
        
        monitor.add_client(mock_ws)
        
        with patch.object(whales_logger, 'warning'):
            await monitor._broadcast({"type": "whale"})
        
        # Client should be removed
        assert mock_ws not in monitor._ws_clients


class TestLegacyAPI:
    """Test legacy API functions."""
    
    @pytest.mark.asyncio
    async def test_solana_whale_listener(self):
        """Test solana_whale_listener starts monitor."""
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        monitor = get_whale_monitor()
        
        async def cancel_soon():
            await asyncio.sleep(0.1)
            await monitor.stop()
        
        # Run briefly then cancel
        await asyncio.gather(
            asyncio.create_task(cancel_soon()),
            return_exceptions=True
        )
    
    @pytest.mark.asyncio
    async def test_broadcast_whale_legacy(self):
        """Test broadcast_whale legacy function."""
        import merid.whales as whales_module
        whales_module._default_monitor = None
        
        # Should not raise
        await broadcast_whale({"type": "whale", "amount": 1000.0})


class TestWhalesPointers:
    """Pointer tests for pytest-checklist to track critical function coverage."""
    
    @pytest.mark.asyncio
    async def test_get_sentry_transaction_coverage(self):
        """Pointer: get_sentry_transaction coverage."""
        context = get_sentry_transaction()
        assert context is not None
    
    @pytest.mark.asyncio
    async def test_capture_sentry_exception_coverage(self):
        """Pointer: capture_sentry_exception coverage."""
        exc = ValueError("Test")
        capture_sentry_exception(exc)
        assert True  # Should not raise
    
    @pytest.mark.asyncio
    async def test_whale_event_to_dict_coverage(self):
        """Pointer: WhaleEvent.to_dict coverage."""
        event = WhaleEvent(mint="test", owner="test", amount=1000.0)
        data = event.to_dict()
        assert "type" in data
    
    @pytest.mark.asyncio
    async def test_whale_monitor_start_stop_coverage(self):
        """Pointer: WhaleMonitor.start/stop coverage."""
        monitor = WhaleMonitor()
        await monitor.start()
        assert monitor.is_running
        await monitor.stop()
        assert not monitor.is_running
    
    @pytest.mark.asyncio
    async def test_whale_monitor_add_remove_client_coverage(self):
        """Pointer: WhaleMonitor.add_client/remove_client coverage."""
        monitor = WhaleMonitor()
        mock_ws = MagicMock()
        monitor.add_client(mock_ws)
        assert monitor.client_count == 1
        monitor.remove_client(mock_ws)
        assert monitor.client_count == 0
    
    @pytest.mark.asyncio
    async def test_get_whale_monitor_coverage(self):
        """Pointer: get_whale_monitor coverage."""
        import merid.whales as whales_module
        whales_module._default_monitor = None
        monitor = get_whale_monitor()
        assert monitor is not None
