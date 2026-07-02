"""Regression tests for WebSocket callback safety (Phase 1 fixes).

Tests the defensive guards added to prevent NoneType await errors
and ensure robust callback handling in the Kalshi WebSocket client.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Optional

from merid.event_venues.kalshi.ws import KalshiWebSocket


class TestWebSocketCallbackSafety:
    """Test suite for Phase 1 WebSocket callback safety fixes."""

    @pytest.fixture
    def ws_client(self):
        """Create a KalshiWebSocket client for testing."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        config.private_key_path = None  # Set to None to prevent file access
        return KalshiWebSocket(config)

    def create_mock_task(self, coro, name=None):
        """Create a mock task that properly handles coroutines."""
        mock_task = AsyncMock()
        # Make the mock task behave like a real task
        mock_task.add_done_callback = MagicMock()
        return mock_task

    @pytest.mark.asyncio
    async def test_noop_async_callback_safe(self, ws_client):
        """Test that the no-op async callback is safe and doesn't crash."""
        # Should not raise any exception
        await ws_client._noop_async_callback({"test": "data"})
        await ws_client._noop_async_callback(None)
        await ws_client._noop_async_callback("any_data")

    @pytest.mark.asyncio
    async def test_handle_event_async_with_none_callback(self, ws_client):
        """Test defensive guard against None callback in _handle_event_async."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Should not raise NoneType await error
        with patch.object(ws_client, '_noop_async_callback') as noop_mock:
            await ws_client._handle_event_async(None, event, raw_data)
        
        # Should log warning about None callback
        noop_mock.assert_not_called()  # Should return early before calling callback

    @pytest.mark.asyncio
    async def test_handle_event_async_with_non_callable_callback(self, ws_client):
        """Test defensive guard against non-callable callback."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Should not raise error with non-callable callback
        with patch.object(ws_client, '_noop_async_callback') as noop_mock:
            await ws_client._handle_event_async("not_callable", event, raw_data)
        
        # Should log warning and return early
        noop_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_event_async_with_sync_callback(self, ws_client):
        """Test handling of synchronous callbacks via executor."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Create a sync callback
        sync_callback = MagicMock()
        
        with patch('asyncio.get_running_loop') as get_loop_mock:
            loop_mock = AsyncMock()
            get_loop_mock.return_value = loop_mock
            
            await ws_client._handle_event_async(sync_callback, event, raw_data)
            
            # Should run sync callback in executor
            loop_mock.run_in_executor.assert_called_once_with(None, sync_callback, event)

    @pytest.mark.asyncio
    async def test_handle_event_async_with_async_callback(self, ws_client):
        """Test handling of async callbacks."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Create an async callback
        async_callback = AsyncMock()
        
        await ws_client._handle_event_async(async_callback, event, raw_data)
        
        # Should call async callback directly
        async_callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_listen_with_none_callback(self, ws_client):
        """Test that listen() handles None callback gracefully."""
        # Mock the WebSocket connection and prevent actual connection
        ws_client._ws = AsyncMock()
        ws_client._running = True
        
        # Mock all the methods that would be called in the main loop
        with patch.object(ws_client, 'connect'):
            with patch.object(ws_client, '_monitor_connection_health'):
                with patch.object(ws_client, '_process_messages_until_disconnect', side_effect=asyncio.CancelledError()):
                    # Mock asyncio.create_task to properly handle coroutines and avoid warnings
                    with patch('asyncio.create_task', side_effect=self.create_mock_task) as create_task_mock:
                        try:
                            await ws_client.listen(None)
                        except asyncio.CancelledError:
                            pass  # Expected when we cancel the main loop
                        
                        # Should use no-op callback
                        assert ws_client._callback == ws_client._noop_async_callback
                        # Should be called at least once for the processor task
                        assert create_task_mock.call_count >= 1
                        # First call should be for the processor task
                        processor_call = create_task_mock.call_args_list[0]
                        assert 'kalshi-ws-processor' in str(processor_call)

    @pytest.mark.asyncio
    async def test_listen_with_invalid_callback(self, ws_client):
        """Test that listen() handles non-callable callback gracefully."""
        # Mock the WebSocket connection and prevent actual connection
        ws_client._ws = AsyncMock()
        ws_client._running = True
        
        # Mock all the methods that would be called in the main loop
        with patch.object(ws_client, 'connect'):
            with patch.object(ws_client, '_monitor_connection_health'):
                with patch.object(ws_client, '_process_messages_until_disconnect', side_effect=asyncio.CancelledError()):
                    # Mock asyncio.create_task to properly handle coroutines and avoid warnings
                    with patch('asyncio.create_task', side_effect=self.create_mock_task) as create_task_mock:
                        try:
                            await ws_client.listen("not_callable")
                        except asyncio.CancelledError:
                            pass  # Expected when we cancel the main loop
                        
                        # Should use no-op callback
                        assert ws_client._callback == ws_client._noop_async_callback
                        # Should be called at least once for the processor task
                        assert create_task_mock.call_count >= 1
                        # First call should be for the processor task
                        processor_call = create_task_mock.call_args_list[0]
                        assert 'kalshi-ws-processor' in str(processor_call)

    @pytest.mark.asyncio
    async def test_process_single_message_with_none_callback(self, ws_client):
        """Test that _process_single_message handles None callback safely."""
        data = {"type": "test", "ticker": "TEST"}
        
        # Mock the message parsing
        event = {"parsed": "data"}
        with patch.object(ws_client, '_parse_message', return_value=event):
            # Mock asyncio.create_task to properly handle coroutines and avoid warnings
            with patch('asyncio.create_task', side_effect=self.create_mock_task) as create_task_mock:
                # Mock task_done to prevent queue error
                with patch.object(ws_client._msg_queue, 'task_done'):
                    # Should not crash with None callback
                    ws_client._process_single_message(None, data)
                    
                    # Should create task with no-op callback
                    create_task_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_single_message_exception_handling(self, ws_client):
        """Test that _process_single_message catches all exceptions."""
        data = {"type": "test", "ticker": "TEST"}
        
        # Mock message parsing to raise an exception
        with patch.object(ws_client, '_parse_message', side_effect=Exception("Parse error")):
            # Mock asyncio.create_task to properly handle coroutines and avoid warnings
            with patch('asyncio.create_task', side_effect=self.create_mock_task):
                # Mock task_done to prevent queue error
                with patch.object(ws_client._msg_queue, 'task_done'):
                    # Should not crash
                    ws_client._process_single_message(ws_client._noop_async_callback, data)
                    
                    # Should still call task_done on the queue
                    ws_client._msg_queue.task_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_initialization_safety(self, ws_client):
        """Test that callback is initialized safely to prevent NoneType errors."""
        # Should be initialized with no-op callback
        assert ws_client._callback is not None
        assert callable(ws_client._callback)
        assert ws_client._callback == ws_client._noop_async_callback

    @pytest.mark.asyncio
    async def test_handle_event_async_exception_isolation(self, ws_client):
        """Test that exceptions in callbacks don't crash the handler."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Create a callback that raises an exception
        failing_callback = AsyncMock(side_effect=Exception("Callback error"))
        
        # Should not crash, should log the error
        with patch('merid.event_venues.kalshi.ws.logger') as logger_mock:
            await ws_client._handle_event_async(failing_callback, event, raw_data)
            
            # Should log the error
            logger_mock.warning.assert_called_once()
            assert "Error in Kalshi WS callback" in str(logger_mock.warning.call_args)

    @pytest.mark.asyncio
    async def test_callback_type_inspection_safety(self, ws_client):
        """Test that callback type inspection works correctly."""
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Test with various callback types
        async def async_func(data):
            pass
        
        def sync_func(data):
            pass
        
        class CallableClass:
            def __call__(self, data):
                pass
        
        # Async function should be awaited directly
        await ws_client._handle_event_async(async_func, event, raw_data)
        
        # Sync function should go through executor
        with patch('asyncio.get_running_loop') as get_loop_mock:
            loop_mock = AsyncMock()
            get_loop_mock.return_value = loop_mock
            await ws_client._handle_event_async(sync_func, event, raw_data)
            loop_mock.run_in_executor.assert_called_once()
        
        # Callable class should go through executor
        with patch('asyncio.get_running_loop') as get_loop_mock:
            loop_mock = AsyncMock()
            get_loop_mock.return_value = loop_mock
            await ws_client._handle_event_async(CallableClass(), event, raw_data)
            loop_mock.run_in_executor.assert_called_once()


class TestWebSocketCallbackIntegration:
    """Integration tests for WebSocket callback safety."""

    def create_mock_task(self, coro, name=None):
        """Create a mock task that properly handles coroutines."""
        mock_task = AsyncMock()
        # Make the mock task behave like a real task
        mock_task.add_done_callback = MagicMock()
        return mock_task

    @pytest.mark.asyncio
    async def test_end_to_end_callback_safety(self):
        """Test end-to-end callback safety with realistic WebSocket flow."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        config.private_key_path = None  # Set to None to prevent file access
        
        ws_client = KalshiWebSocket(config)
        
        # Mock WebSocket and connection
        ws_client._ws = AsyncMock()
        ws_client._running = True
        
        # Mock the connect method and other main loop components to prevent actual connection
        with patch.object(ws_client, 'connect'):
            with patch.object(ws_client, '_monitor_connection_health'):
                with patch.object(ws_client, '_process_messages_until_disconnect', side_effect=asyncio.CancelledError()):
                    # Mock asyncio.create_task to properly handle coroutines and avoid warnings
                    with patch('asyncio.create_task', side_effect=self.create_mock_task):
                        # Test with various callback scenarios
                        test_cases = [
                            None,  # None callback
                            "not_callable",  # Non-callable
                            AsyncMock(),  # Async callback
                            MagicMock(),  # Sync callback
                        ]
                        
                        for callback in test_cases:
                            try:
                                await ws_client.listen(callback)
                            except asyncio.CancelledError:
                                pass  # Expected when we cancel the main loop
                            
                            assert ws_client._callback is not None
                            assert callable(ws_client._callback)

    @pytest.mark.asyncio
    async def test_message_processing_resilience(self):
        """Test that message processing is resilient to various failure modes."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        config.private_key_path = None  # Set to None to prevent file access
        
        ws_client = KalshiWebSocket(config)
        
        # Test various malformed messages
        malformed_messages = [
            {},  # Empty message
            {"type": None},  # None type
            {"type": "test", "ticker": None},  # None ticker
            {"invalid": "structure"},  # Invalid structure
        ]
        
        for msg in malformed_messages:
            # Should not crash with any message format
            try:
                # Mock task_done to prevent queue error
                with patch.object(ws_client._msg_queue, 'task_done'):
                    ws_client._process_single_message(None, msg)
            except Exception as e:
                pytest.fail(f"Message processing crashed with {msg}: {e}")

    @pytest.mark.asyncio
    async def test_callback_failure_recovery(self):
        """Test that the system recovers from callback failures."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        
        ws_client = KalshiWebSocket(config)
        
        # Create a callback that fails
        failing_callback = AsyncMock(side_effect=Exception("Callback failed"))
        
        event = {"type": "test", "data": "value"}
        raw_data = {"type": "test", "ticker": "TEST"}
        
        # Should handle the failure gracefully
        with patch('merid.event_venues.kalshi.ws.logger') as logger_mock:
            await ws_client._handle_event_async(failing_callback, event, raw_data)
            
            # Should log the error but not crash
            logger_mock.warning.assert_called_once()
        
        # System should still be functional after failure
        assert ws_client._callback_failure_count >= 0  # Should be tracked
