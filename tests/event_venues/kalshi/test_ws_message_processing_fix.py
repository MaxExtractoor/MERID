"""Tests for WebSocket message processing fix in ws.py.

Tests the fix for the logic error where debug code was unreachable
due to misplaced continue statement in JSON parsing.
"""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig
from core.fault_manager import reset_fault_manager


@pytest.fixture(autouse=True)
def _isolate_fault_manager():
    """Reset the process-wide FaultManager around each test."""
    reset_fault_manager()
    try:
        yield
    finally:
        reset_fault_manager()


@pytest.fixture
def config():
    """Create test Kalshi config."""
    return KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )


@pytest.fixture
def ws_client(config):
    """Create test Kalshi WebSocket client."""
    return KalshiWebSocket(config)


class TestWebSocketMessageProcessingFix:
    """Test the WebSocket message processing fix."""
    
    @pytest.mark.asyncio
    async def test_json_parsing_with_orderbook_delta(self, ws_client):
        """Test that orderbook_delta messages are properly parsed and logged."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({
                "type": "orderbook_delta",
                "msg": {
                    "market_ticker": "KXBTC15M-26JUN022300-00",
                    "yes_levels": [[50, 10]],
                    "no_levels": [[50, 10]]
                }
            }),
            asyncio.CancelledError()  # End the loop
        ])

        ws_client._ws = mock_ws
        ws_client._running = True

        # Mock the message queue and other dependencies
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        ws_client._msg_queue.qsize = MagicMock(return_value=0)

        # Mock sequence check
        ws_client._check_sequence = MagicMock(return_value=True)

        # Mock message priority classification
        ws_client._classify_message_priority = MagicMock(return_value=1)

        # Track processed messages
        processed_messages = []

        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)

        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait

        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
            finally:
                # Ensure proper cleanup
                ws_client._running = False
        
        # Verify that the orderbook_delta message was processed
        assert len(processed_messages) == 1
        assert processed_messages[0]["type"] == "orderbook_delta"
        assert processed_messages[0]["msg"]["market_ticker"] == "KXBTC15M-26JUN022300-00"
    
    @pytest.mark.asyncio
    async def test_json_parsing_with_error_message(self, ws_client):
        """Test that error messages are properly handled."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({
                "type": "error",
                "msg": "Test error message"
            }),
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock error handler
        ws_client._handle_error_message = MagicMock()
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify error handler was called
        ws_client._handle_error_message.assert_called_once()
        error_data = ws_client._handle_error_message.call_args[0][0]
        assert error_data["type"] == "error"
        assert error_data["msg"] == "Test error message"
    
    @pytest.mark.asyncio
    async def test_malformed_json_is_dropped(self, ws_client):
        """Test that malformed JSON is properly dropped."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            '{"type": "orderbook_delta", "msg": incomplete',
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock the message queue
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        
        # Track processed messages
        processed_messages = []
        
        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)
        
        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify no messages were processed due to malformed JSON
        assert len(processed_messages) == 0
    
    @pytest.mark.asyncio
    async def test_sequence_check_failure_drops_message(self, ws_client):
        """Test that messages failing sequence check are dropped."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({
                "type": "orderbook_delta",
                "msg": {
                    "market_ticker": "KXBTC15M-26JUN022300-00",
                    "yes_levels": [[50, 10]],
                    "no_levels": [[50, 10]]
                }
            }),
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock the message queue
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        
        # Mock sequence check to fail
        ws_client._check_sequence = MagicMock(return_value=False)
        
        # Track processed messages
        processed_messages = []
        
        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)
        
        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify no messages were processed due to sequence check failure
        assert len(processed_messages) == 0
        ws_client._check_sequence.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_multiple_messages_processed_correctly(self, ws_client):
        """Test that multiple valid messages are all processed correctly."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({
                "type": "orderbook_delta",
                "msg": {
                    "market_ticker": "KXBTC15M-26JUN022300-00",
                    "yes_levels": [[50, 10]],
                    "no_levels": [[50, 10]]
                }
            }),
            json.dumps({
                "type": "ticker",
                "msg": {
                    "market_ticker": "KXETH15M-26JUN022300-00",
                    "price": 50
                }
            }),
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock the message queue
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        ws_client._msg_queue.qsize = MagicMock(return_value=0)
        
        # Mock sequence check
        ws_client._check_sequence = MagicMock(return_value=True)
        
        # Mock message priority classification
        ws_client._classify_message_priority = MagicMock(return_value=1)
        
        # Track processed messages
        processed_messages = []
        
        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)
        
        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify both messages were processed
        assert len(processed_messages) == 2
        assert processed_messages[0]["type"] == "orderbook_delta"
        assert processed_messages[1]["type"] == "ticker"
    
    @pytest.mark.asyncio
    async def test_bytes_message_handling(self, ws_client):
        """Test that bytes messages are properly decoded."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b'{"type": "orderbook_delta", "msg": {"market_ticker": "KXBTC15M-26JUN022300-00"}}',
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock the message queue
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        ws_client._msg_queue.qsize = MagicMock(return_value=0)
        
        # Mock sequence check
        ws_client._check_sequence = MagicMock(return_value=True)
        
        # Mock message priority classification
        ws_client._classify_message_priority = MagicMock(return_value=1)
        
        # Track processed messages
        processed_messages = []
        
        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)
        
        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify the bytes message was processed
        assert len(processed_messages) == 1
        assert processed_messages[0]["type"] == "orderbook_delta"
        assert processed_messages[0]["msg"]["market_ticker"] == "KXBTC15M-26JUN022300-00"
    
    @pytest.mark.asyncio
    async def test_unknown_message_type_handling(self, ws_client):
        """Test that unknown message types are handled gracefully."""
        # Mock the WebSocket connection
        mock_ws = MagicMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({
                "type": "unknown_type",
                "msg": {
                    "some_field": "some_value"
                }
            }),
            asyncio.CancelledError()  # End the loop
        ])
        
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Mock the message queue
        ws_client._msg_queue = MagicMock()
        ws_client._msg_queue.maxsize = 1000
        ws_client._msg_queue.put_nowait = MagicMock()
        ws_client._msg_queue.qsize = MagicMock(return_value=0)
        
        # Mock sequence check
        ws_client._check_sequence = MagicMock(return_value=True)
        
        # Mock message priority classification
        ws_client._classify_message_priority = MagicMock(return_value=1)
        
        # Track processed messages
        processed_messages = []
        
        def capture_put_nowait(item):
            priority, data = item
            processed_messages.append(data)
        
        ws_client._msg_queue.put_nowait.side_effect = capture_put_nowait
        
        # Run the message processing
        with patch('time.monotonic', return_value=123456789.0):
            try:
                await ws_client._process_messages_until_disconnect()
            except asyncio.CancelledError:
                pass  # Expected termination
        
        # Verify the unknown message was still processed
        assert len(processed_messages) == 1
        assert processed_messages[0]["type"] == "unknown_type"
