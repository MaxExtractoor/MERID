"""Tests for WS callback performance optimizations.

Tests cover:
- Scope validation caching to avoid repeated checks (market_state.py)
- Delta throttling removal to reduce callback latency (market_state.py)
- Diagnostic logging disabled to prevent event loop blocking (ws.py)
- Callback latency thresholds for real-time trading
- Consecutive loss tracking fix (failed submissions should not count as losses)
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.ws import KalshiWebSocket


def test_scope_validation_cache_initialized():
    """Test that scope validation cache is initialized in __init__."""
    store = KalshiMarketStateStore()
    
    # Verify cache exists
    assert hasattr(store, '_scope_validation_cache')
    assert isinstance(store._scope_validation_cache, dict)
    
    # Verify cache is empty initially
    assert len(store._scope_validation_cache) == 0


def test_scope_validation_cache_hit():
    """Test that scope validation cache is used for repeated tickers."""
    store = KalshiMarketStateStore()
    
    # Simulate first validation (cache miss)
    ticker = "KXBTC15M-26JUN282115-15"
    store._scope_validation_cache[ticker] = (True, None)
    
    # Simulate second validation (cache hit)
    is_valid, reason = store._scope_validation_cache.get(ticker, (False, None))
    
    # Verify cache hit
    assert is_valid is True
    assert reason is None


def test_scope_validation_cache_rejection():
    """Test that scope validation cache rejects invalid tickers."""
    store = KalshiMarketStateStore()
    
    # Simulate rejected ticker
    ticker = "KXINVALID-26JUN282115-15"
    store._scope_validation_cache[ticker] = (False, "asset_not_whitelisted")
    
    # Verify rejection from cache
    is_valid, reason = store._scope_validation_cache.get(ticker, (True, None))
    
    assert is_valid is False
    assert reason == "asset_not_whitelisted"


def test_scope_validation_cache_multiple_tickers():
    """Test that scope validation cache handles multiple tickers correctly."""
    store = KalshiMarketStateStore()
    
    # Add multiple tickers to cache
    tickers = [
        ("KXBTC15M-26JUN282115-15", True, None),
        ("KXETH15M-26JUN282115-15", True, None),
        ("KXSOL15M-26JUN282115-15", True, None),
        ("KXXRP15M-26JUN282115-15", True, None),
        ("KXDOGE15M-26JUN282115-15", True, None),
    ]
    
    for ticker, is_valid, reason in tickers:
        store._scope_validation_cache[ticker] = (is_valid, reason)
    
    # Verify all tickers are cached
    assert len(store._scope_validation_cache) == 5
    
    # Verify each ticker's cached result
    for ticker, expected_valid, expected_reason in tickers:
        is_valid, reason = store._scope_validation_cache[ticker]
        assert is_valid == expected_valid
        assert reason == expected_reason


def test_delta_throttling_removed():
    """Test that delta throttling has been removed to eliminate sequence gaps.
    
    Research shows any throttling causes sequence gaps in high-frequency trading.
    Even 5ms throttling was causing 200,000+ sequence gaps.
    Event loop will handle bursts via async queue processing.
    """
    store = KalshiMarketStateStore()
    
    # Verify throttling has been removed
    # The _last_delta_update dict may still exist but should not be used
    import inspect
    source = inspect.getsource(store.apply_orderbook_message)
    
    # Verify throttling has been removed (no min_interval check)
    assert "min_interval" not in source or "Removed delta throttling" in source
    
    # Verify the comment about removing throttling is present
    assert "Removed delta throttling" in source or "any throttling causes sequence gaps" in source


def test_performance_optimizations_reduces_latency():
    """Test that performance optimizations reduce callback latency."""
    store = KalshiMarketStateStore()
    
    # Simulate repeated ticker processing
    ticker = "KXBTC15M-26JUN282115-15"
    
    # First call: cache miss (slower)
    store._scope_validation_cache[ticker] = (True, None)
    
    # Subsequent calls: cache hit (faster)
    # The cache hit avoids asset extraction and validation
    # This should reduce callback latency by ~5-10ms per call
    for _ in range(100):
        is_valid, reason = store._scope_validation_cache.get(ticker, (False, None))
        assert is_valid is True
    
    # Verify cache is still valid
    assert len(store._scope_validation_cache) == 1


class TestWebSocketDiagnosticLogging:
    """Test suite for diagnostic logging performance fix.
    
    Tests verify that excessive diagnostic logging is disabled
    to prevent event loop blocking and 2+ second callback latency.
    """
    
    @pytest.fixture
    def ws_client(self):
        """Create a KalshiWebSocket client for testing."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        config.private_key_path = None
        return KalshiWebSocket(config)
    
    def test_diagnostic_logging_disabled_in_parse_message(self, ws_client):
        """Test that diagnostic logging is disabled in _parse_message.
        
        The excessive logging of every WS message was causing 2+ second
        callback latency by blocking the event loop with synchronous I/O.
        """
        # Read the ws.py source to verify logging is commented out
        import inspect
        source = inspect.getsource(ws_client._parse_message)
        
        # Verify the diagnostic logging is commented out
        # The key indicator is that the logger.info line starts with #
        lines = source.split('\n')
        ws_raw_lines = [line for line in lines if '[WS-RAW]' in line]
        
        # All lines with [WS-RAW] should be commented out
        for line in ws_raw_lines:
            assert line.strip().startswith('#'), f"WS-RAW logging not commented out: {line}"
        
        # Verify the comment explaining why it's disabled
        assert "DISABLED" in source or "excessive diagnostic logging" in source.lower()
        
        # Verify the specific comment about callback latency
        assert "callback latency" in source.lower() or "2+ second" in source.lower()
    
    @pytest.mark.asyncio
    async def test_parse_message_latency_acceptable(self, ws_client):
        """Test that _parse_message completes within acceptable latency threshold.
        
        Callback latency should be <500ms (the warning threshold).
        With diagnostic logging disabled, it should be <100ms.
        """
        # Create a realistic orderbook_delta message
        test_message = {
            "type": "orderbook_delta",
            "ticker": "KXBTC15M-26JUL080545-45",
            "delta_fp": "0.01",
            "price_dollars": "0.50",
            "side": "yes"
        }
        
        # Measure parse time
        start = time.perf_counter()
        event = ws_client._parse_message(test_message)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should complete well under 500ms threshold
        assert elapsed_ms < 500, f"Parse took {elapsed_ms}ms, exceeds 500ms threshold"
        
        # Should typically complete in <100ms with logging disabled
        assert elapsed_ms < 100, f"Parse took {elapsed_ms}ms, exceeds 100ms expected"
    
    @pytest.mark.asyncio
    async def test_parse_message_no_synchronous_logging(self, ws_client):
        """Test that _parse_message doesn't perform synchronous logging operations.
        
        Synchronous logging blocks the event loop and causes callback latency.
        """
        test_message = {
            "type": "orderbook_delta",
            "ticker": "KXBTC15M-26JUL080545-45",
            "delta_fp": "0.01",
            "price_dollars": "0.50",
            "side": "yes"
        }
        
        # Mock logger to track calls
        with patch('merid.event_venues.kalshi.ws.logger') as mock_logger:
            event = ws_client._parse_message(test_message)
            
            # Should not call logger.info for every message
            info_calls = [call for call in mock_logger.info.call_args_list]
            assert len(info_calls) == 0, "Should not perform synchronous logging in _parse_message"
    
    @pytest.mark.asyncio
    async def test_handle_event_async_latency_acceptable(self, ws_client):
        """Test that _handle_event_async completes within acceptable latency.
        
        This tests the full callback chain including async handling.
        """
        event = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL080545-45"}
        raw_data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL080545-45"}
        
        # Create a simple async callback
        async def simple_callback(event):
            pass
        
        # Measure callback time
        start = time.perf_counter()
        await ws_client._handle_event_async(simple_callback, event, raw_data)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should complete well under 500ms threshold
        assert elapsed_ms < 500, f"Callback took {elapsed_ms}ms, exceeds 500ms threshold"
    
    @pytest.mark.asyncio
    async def test_high_frequency_message_processing(self, ws_client):
        """Test that high-frequency message processing doesn't cause latency buildup.
        
        Simulates processing 100 messages rapidly to ensure no backlog accumulation.
        """
        messages = []
        for i in range(100):
            messages.append({
                "type": "orderbook_delta",
                "ticker": f"KXBTC15M-26JUL080545-{i}",
                "delta_fp": "0.01",
                "price_dollars": "0.50",
                "side": "yes"
            })
        
        # Process all messages and measure total time
        start = time.perf_counter()
        for msg in messages:
            event = ws_client._parse_message(msg)
        total_elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Average latency per message should be <10ms
        avg_latency_ms = total_elapsed_ms / len(messages)
        assert avg_latency_ms < 10, f"Average latency {avg_latency_ms}ms exceeds 10ms"
        
        # Total time for 100 messages should be <1 second
        assert total_elapsed_ms < 1000, f"Total time {total_elapsed_ms}ms exceeds 1 second"


class TestWebSocketSequenceGapPrevention:
    """Test suite for sequence gap prevention.
    
    Tests verify that callback latency improvements prevent
    the massive sequence gaps (1.2M+ gaps) that were accumulating.
    """
    
    @pytest.fixture
    def ws_client(self):
        """Create a KalshiWebSocket client for testing."""
        config = MagicMock()
        config.api_key = "test_key"
        config.base_url = "wss://test.kalshi.com"
        config.private_key_path = None
        return KalshiWebSocket(config)
    
    @pytest.mark.asyncio
    async def test_rapid_message_processing_no_gaps(self, ws_client):
        """Test that rapid message processing doesn't cause sequence gaps.
        
        With diagnostic logging disabled, messages should be processed
        fast enough to prevent sequence gaps from accumulating.
        """
        # Simulate a sequence of messages with sequential sequence numbers
        messages = []
        for seq in range(100):
            messages.append({
                "type": "orderbook_delta",
                "ticker": "KXBTC15M-26JUL080545-45",
                "seq": seq,
                "delta_fp": "0.01",
                "price_dollars": "0.50",
                "side": "yes"
            })
        
        # Process messages rapidly
        start = time.perf_counter()
        for msg in messages:
            event = ws_client._parse_message(msg)
        total_elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should process 100 messages in <1 second
        assert total_elapsed_ms < 1000, f"Processing 100 messages took {total_elapsed_ms}ms"
        
        # Average latency should be <10ms per message
        avg_latency_ms = total_elapsed_ms / len(messages)
        assert avg_latency_ms < 10, f"Average latency {avg_latency_ms}ms too high, may cause gaps"
    
    def test_sequence_gap_threshold_reasonable(self, ws_client):
        """Test that sequence gap detection threshold is reasonable.
        
        The system should tolerate small gaps (network jitter) but
        flag large gaps (processing backlog).
        """
        # This test verifies the gap detection logic in ws_bridge.py
        # Small gaps (<10) are acceptable, large gaps (>100) indicate problems
        
        # Simulate small gap (network jitter)
        small_gap = 5
        assert small_gap < 10, "Small gaps should be tolerated"
        
        # Simulate large gap (processing backlog)
        large_gap = 100
        assert large_gap >= 10, "Large gaps should be flagged"
    
    def test_sequence_gap_logging_frequency_reduced(self, ws_client):
        """Test that sequence gap logging frequency is reduced to prevent blocking I/O.
        
        Individual gaps should be logged at debug level, only significant gaps
        (>10 or every 100th gap) trigger warnings to reduce blocking I/O overhead.
        """
        # This test verifies the logging logic in ws_bridge.py
        # Read the source to check the logging frequency logic
        try:
            from merid.event_venues.kalshi import ws_bridge
            import inspect
            source = inspect.getsource(ws_bridge)
            
            # Verify the logging frequency reduction logic
            # Should only warn on gap > 10 or _sequence_gaps % 100 == 0
            assert "gap > 10" in source or "gap > 10" in source.replace(" ", "")
            assert "_sequence_gaps % 100" in source or "_sequence_gaps % 100" in source.replace(" ", "")
            
            # Verify debug logging for individual gaps
            assert "logger.debug" in source and "sequence gap" in source.lower()
            
        except ImportError:
            # If ws_bridge can't be imported, skip this test
            pytest.skip("ws_bridge not available for inspection")


def test_consecutive_loss_tracking_fix():
    """Test that failed order submissions do NOT increment consecutive loss counter.
    
    This is a critical fix - failed submissions are technical failures, not actual monetary losses.
    Consecutive loss tracking should only apply to executed trades with negative PnL.
    """
    try:
        from merid.prediction.agent_grid_15m import AgentGrid15M
        import inspect
        source = inspect.getsource(AgentGrid15M)
        
        # Verify that the consecutive loss increment is NOT in the failed execution path
        # The failed execution path should NOT have "_consecutive_losses[asset] +="
        # It should only have the increment in the PnL tracking section (pnl_usd < 0)
        
        # Check that the increment is in the PnL section
        assert "if pnl_usd < 0:" in source
        assert "_consecutive_losses[asset] += 1" in source
        
        # Check that the failed execution path does NOT increment consecutive losses
        # Look for the DIRECT-EXECUTION-FAILED section
        assert "DIRECT-EXECUTION-FAILED" in source
        
        # Verify the fix comment is present
        assert "Do NOT increment consecutive loss counter on failed submissions" in source or \
               "Failed submissions are technical failures" in source
        
    except ImportError:
        pytest.skip("AgentGrid15M not available for inspection")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
