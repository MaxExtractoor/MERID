"""
Phase 2: WS Resilience Tests

Tests for Kalshi WebSocket resilience covering:
1. Disconnect/reconnect with exponential backoff
2. Sequence gap recovery with REST snapshot refresh
3. Malformed message handling

Reference: .windsurf/tickets/phase2-ws-resilience-tests.md
Baseline: Commit c25d2702
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig
from core.fault_manager import reset_fault_manager


@pytest.fixture(autouse=True)
def _isolate_fault_manager():
    """Reset the ``FaultManager`` singleton before and after each test.

    ``KalshiWebSocket._reconnect`` consults the process-wide ``FaultManager``
    via ``get_fault_manager().can_attempt_reconnect("kalshi")`` and trips the
    venue circuit breaker after a handful of failures.  When these unit tests
    run back-to-back without isolation, earlier failure counts leak into later
    tests and silently short-circuit the reconnect path — every assertion that
    depends on ``_reconnect_delay`` bookkeeping then breaks for reasons
    unrelated to the code under test.
    """
    reset_fault_manager()
    try:
        yield
    finally:
        reset_fault_manager()


class TestDisconnectReconnectBackoff:
    """Test disconnect/reconnect with exponential backoff."""

    @pytest.mark.asyncio
    async def test_reconnect_applies_exponential_backoff(self):
        """Verify reconnect delay doubles on repeated *failures*.

        Current production semantics (``ws.py``):
          * successful reconnect → ``_reconnect_delay`` is **reset** to 1.0
          * failed reconnect      → ``_reconnect_delay`` doubles (capped)

        The backoff curve therefore only advances when ``connect()`` raises.
        """
        ws = KalshiWebSocket()
        ws._running = True
        ws._reconnect_delay = 1.0

        # Mock connect to *fail* so exponential backoff actually advances
        async def failing_connect():
            raise ConnectionError("simulated connect failure")

        ws.connect = failing_connect

        # Mock sleep to track delays
        sleep_times = []

        async def mock_sleep(delay):
            sleep_times.append(delay)

        with patch('asyncio.sleep', side_effect=mock_sleep):
            await ws._reconnect()
            first_delay = sleep_times[0]

            # Delay should be ~1.0s with jitter (±25%)
            assert 0.75 <= first_delay <= 1.25, f"Expected ~1.0s, got {first_delay}"

            # Verify delay doubled after one failed attempt
            assert ws._reconnect_delay == 2.0

            await ws._reconnect()
            second_delay = sleep_times[1]

            # Delay should be ~2.0s with jitter
            assert 1.5 <= second_delay <= 2.5, f"Expected ~2.0s, got {second_delay}"

            # Verify delay doubled again
            assert ws._reconnect_delay == 4.0

    @pytest.mark.asyncio
    async def test_reconnect_caps_at_max_delay(self):
        """Verify reconnect delay caps at max_reconnect_delay on repeated failures."""
        ws = KalshiWebSocket()
        ws._running = True
        ws._reconnect_delay = 50.0  # Start near max
        ws._max_reconnect_delay = 60.0

        async def failing_connect():
            raise ConnectionError("simulated connect failure")

        ws.connect = failing_connect

        with patch('asyncio.sleep', new_callable=AsyncMock):
            await ws._reconnect()
            # Should cap at 60.0, not double to 100.0
            assert ws._reconnect_delay == 60.0

            await ws._reconnect()
            # Should stay at cap
            assert ws._reconnect_delay == 60.0

    @pytest.mark.asyncio
    async def test_reconnect_respects_rate_limits(self):
        """Verify reconnect does not exceed Kalshi rate limits on rapid failures."""
        ws = KalshiWebSocket()
        ws._running = True
        ws._reconnect_delay = 0.1  # Very short delay

        connect_times = []

        async def mock_connect():
            connect_times.append(time.time())
            raise ConnectionError("simulated connect failure")

        ws.connect = mock_connect

        with patch('asyncio.sleep', new_callable=AsyncMock):
            # Simulate several rapid reconnects — each raises so backoff
            # keeps doubling until the FaultManager circuit breaker opens
            # and blocks further attempts (which is exactly the "respect
            # the rate limit" behaviour we want to verify).
            for _ in range(5):
                await ws._reconnect()

        # Verify delays are being applied (not all connecting at once):
        # the backoff has grown strictly above the starting value, meaning
        # consecutive failures each introduced additional sleep time.
        assert ws._reconnect_delay > 0.1
        assert ws._reconnect_delay >= 0.4

    @pytest.mark.asyncio
    async def test_reconnect_resubscribes_to_all_channels(self):
        """Verify reconnect resubscribes to quotes, trades, and orderbooks."""
        ws = KalshiWebSocket()
        ws._running = True
        
        # Set up existing subscriptions (BUG-6 replay uses _ticker_subscriptions, not _subscriptions)
        ws._ticker_subscriptions = {"KXBTC-24FEB16", "KINX-24MAR15"}
        ws._trade_tickers = {"KXBTC-24FEB16"}
        ws._orderbook_tickers = {"KINX-24MAR15"}
        
        ws.connect = AsyncMock()
        ws.subscribe_quotes = AsyncMock()
        ws.subscribe_trades = AsyncMock()
        ws.subscribe_orderbooks_batch = AsyncMock()
        
        with patch('asyncio.sleep', new_callable=AsyncMock):
            await ws._reconnect()
        
        # Verify resubscriptions
        ws.subscribe_quotes.assert_called_once()
        ws.subscribe_trades.assert_called_once()
        ws.subscribe_orderbooks_batch.assert_called()

    @pytest.mark.asyncio
    async def test_reconnect_clears_orderbook_cache(self):
        """Verify reconnect clears cached orderbook state."""
        ws = KalshiWebSocket()
        ws._running = True
        
        # Populate cache
        ws._ob_initialised.add("KXBTC-24FEB16")
        ws._ob_snapshots["KXBTC-24FEB16"] = {"yes_bid": 55, "no_bid": 44}
        ws._last_seq["KXBTC-24FEB16"] = 1234
        
        ws.connect = AsyncMock()
        
        with patch('asyncio.sleep', new_callable=AsyncMock):
            await ws._reconnect()
        
        # Verify cache cleared
        assert len(ws._ob_initialised) == 0
        assert len(ws._ob_snapshots) == 0
        assert len(ws._last_seq) == 0


class TestSequenceGapRecovery:
    """Test sequence gap detection and orderbook recovery."""

    @pytest.mark.asyncio
    async def test_sequence_gap_detected_and_logged(self):
        """Verify sequence gaps are detected and logged."""
        ws = KalshiWebSocket()

        # Initialize sequence
        ws._last_seq["KXBTC-24FEB16"] = 100
        ws._ob_initialised.add("KXBTC-24FEB16")
        ws._ob_snapshots["KXBTC-24FEB16"] = {"type": "orderbook_snapshot", "ticker": "KXBTC-24FEB16"}

        # Simulate message with gap (expect 101, got 110)
        message = {
            "seq": 110,
            "ticker": "KXBTC-24FEB16",
            "type": "orderbook_delta"
        }

        result = ws._check_sequence(message)

        # Message should be accepted (returns True)
        assert result is True

        # Gap counter should increase
        assert ws._seq_gaps == 9  # Gap of 9 messages

        # Orderbook cache should be invalidated
        assert "KXBTC-24FEB16" not in ws._ob_initialised
        assert "KXBTC-24FEB16" not in ws._ob_snapshots

    @pytest.mark.asyncio
    async def test_sequence_gap_invalidates_orderbook_cache(self):
        """Verify sequence gap invalidates cached orderbook."""
        ws = KalshiWebSocket()

        # Set up cached orderbook
        market_id = "KINX-24MAR15"
        ws._last_seq[market_id] = 50
        ws._ob_initialised.add(market_id)
        ws._ob_snapshots[market_id] = {"yes_bid": 60, "no_bid": 39}

        # Message with gap
        message = {"seq": 60, "ticker": market_id}

        ws._check_sequence(message)
        
        # Cache should be invalidated (stale snapshot removed so get_live_prices cannot serve corrupt books)
        assert market_id not in ws._ob_initialised
        assert market_id not in ws._ob_snapshots

    def test_out_of_order_message_dropped(self):
        """Verify out-of-order messages are dropped."""
        ws = KalshiWebSocket()
        
        ws._last_seq["KXBTC-24FEB16"] = 100
        
        # Message with old sequence (out of order)
        message = {"seq": 95, "ticker": "KXBTC-24FEB16"}
        
        result = ws._check_sequence(message)
        
        # Message should be dropped
        assert result is False
        
        # Last sequence should not update
        assert ws._last_seq["KXBTC-24FEB16"] == 100

    def test_duplicate_sequence_dropped(self):
        """Verify duplicate sequence numbers are dropped."""
        ws = KalshiWebSocket()
        
        ws._last_seq["KXBTC-24FEB16"] = 100
        
        # Duplicate message
        message = {"seq": 100, "ticker": "KXBTC-24FEB16"}
        
        result = ws._check_sequence(message)
        
        assert result is False
        assert ws._last_seq["KXBTC-24FEB16"] == 100

    def test_orderbook_delta_forwarded_without_ws_snapshot_cache(self):
        """Pre-snapshot deltas are forwarded so market_state can queue them (H3)."""
        ws = KalshiWebSocket()
        
        # Market not initialized (no snapshot)
        market_id = "KXBTC-24FEB16"
        assert market_id not in ws._ob_initialised
        
        # Try to parse delta without snapshot
        delta_message = {
            "type": "orderbook_delta",
            "ticker": market_id,
            "seq": 100,
            "delta": {"yes": [{"price": 55, "quantity": 10}]}
        }
        
        event = ws._parse_message(delta_message)
        
        assert event is delta_message


class TestReconnectResilience:
    """Additional reconnect resilience scenarios."""

    @pytest.mark.asyncio
    async def test_reconnect_handles_repeated_connection_failures(self):
        """Verify reconnect continues trying on repeated connection failures."""
        ws = KalshiWebSocket()
        ws._running = True
        ws._reconnect_delay = 1.0

        # Mock connect to fail multiple times
        connect_attempts = []
        call_count = 0

        async def mock_connect():
            nonlocal call_count
            call_count += 1
            connect_attempts.append(time.time())
            if call_count < 3:
                raise ConnectionError("Connection refused")
            # Succeed on 3rd attempt

        ws.connect = mock_connect

        with patch('asyncio.sleep', new_callable=AsyncMock):
            # First attempt fails
            await ws._reconnect()
            assert len(connect_attempts) == 1

            # Second attempt fails
            await ws._reconnect()
            assert len(connect_attempts) == 2

            # Third attempt succeeds
            await ws._reconnect()
            assert len(connect_attempts) == 3

    @pytest.mark.asyncio
    async def test_reconnect_resets_delay_on_success(self):
        """Verify reconnect delay resets to 1.0 on successful connection.

        Current production semantics (``ws.py`` _reconnect success branch,
        line ~1012):  ``self._reconnect_delay = 1.0`` immediately after
        ``await self.connect()`` returns without raising.
        """
        ws = KalshiWebSocket()
        ws._running = True
        ws._reconnect_delay = 16.0  # High from previous failures

        ws.connect = AsyncMock()

        with patch('asyncio.sleep', new_callable=AsyncMock):
            await ws._reconnect()

        # Successful reconnect resets backoff to the base delay
        assert ws._reconnect_delay == 1.0
