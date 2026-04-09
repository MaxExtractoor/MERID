"""Tests for KalshiWebSocket hardening — error handling, sequence tracking,
backpressure, reconnect, and observability."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.ws import KalshiWebSocket, _FATAL_ERROR_CODES, _WARN_ERROR_CODES


@pytest.fixture
def ws():
    """Fresh KalshiWebSocket instance (not connected)."""
    return KalshiWebSocket()


# ── Error message handling ───────────────────────────────────────────────────

class TestErrorMessageHandling:
    def test_fatal_error_increments_counter(self, ws):
        data = {"type": "error", "code": "auth_failed", "msg": "bad token"}
        ws._ws = MagicMock()
        ws._ws.close = AsyncMock()
        ws._handle_error_message(data)
        assert ws._errors_received == 1

    def test_fatal_error_triggers_close(self, ws):
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        ws._ws = mock_ws
        data = {"type": "error", "code": "auth_failed", "msg": "bad token"}
        ws._handle_error_message(data)
        # Should have scheduled a close
        assert ws._errors_received == 1

    def test_warn_error_increments_counter(self, ws):
        data = {"type": "error", "code": "invalid_channel", "msg": "no such channel"}
        ws._handle_error_message(data)
        assert ws._errors_received == 1

    def test_unknown_error_increments_counter(self, ws):
        data = {"type": "error", "code": "something_new", "msg": "surprise"}
        ws._handle_error_message(data)
        assert ws._errors_received == 1

    def test_multiple_errors_counted(self, ws):
        for i in range(5):
            ws._handle_error_message({"type": "error", "code": "bad_request", "msg": f"err{i}"})
        assert ws._errors_received == 5

    def test_fatal_codes_set(self):
        assert "auth_failed" in _FATAL_ERROR_CODES
        assert "rate_limited" in _FATAL_ERROR_CODES

    def test_warn_codes_set(self):
        assert "invalid_channel" in _WARN_ERROR_CODES
        assert "unknown_ticker" in _WARN_ERROR_CODES


# ── Sequence tracking ────────────────────────────────────────────────────────

class TestSequenceTracking:
    def test_first_message_always_accepted(self, ws):
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 1}
        assert ws._check_sequence(data) is True
        assert ws._last_seq["KXBTC"] == 1

    def test_sequential_accepted(self, ws):
        ws._last_seq["KXBTC"] = 5
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 6}
        assert ws._check_sequence(data) is True
        assert ws._last_seq["KXBTC"] == 6

    def test_duplicate_rejected(self, ws):
        ws._last_seq["KXBTC"] = 5
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 5}
        assert ws._check_sequence(data) is False

    def test_out_of_order_rejected(self, ws):
        ws._last_seq["KXBTC"] = 10
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 8}
        assert ws._check_sequence(data) is False

    def test_gap_detected_but_accepted(self, ws):
        ws._last_seq["KXBTC"] = 5
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 10}
        assert ws._check_sequence(data) is True
        assert ws._seq_gaps == 4  # 6,7,8,9 missing
        assert ws._last_seq["KXBTC"] == 10

    def test_gap_invalidates_orderbook_cache(self, ws):
        ws._ob_initialised.add("KXBTC")
        ws._last_seq["KXBTC"] = 5
        data = {"type": "ticker", "ticker": "KXBTC", "seq": 10}
        ws._check_sequence(data)
        assert "KXBTC" not in ws._ob_initialised

    def test_no_seq_field_always_accepted(self, ws):
        data = {"type": "subscribed", "channel": "ticker"}
        assert ws._check_sequence(data) is True

    def test_multiple_markets_independent(self, ws):
        ws._check_sequence({"ticker": "A", "seq": 1})
        ws._check_sequence({"ticker": "B", "seq": 1})
        ws._check_sequence({"ticker": "A", "seq": 2})
        assert ws._last_seq["A"] == 2
        assert ws._last_seq["B"] == 1

    def test_cumulative_gap_count(self, ws):
        ws._last_seq["X"] = 1
        ws._check_sequence({"ticker": "X", "seq": 5})  # gap=3
        ws._check_sequence({"ticker": "X", "seq": 10})  # gap=4
        assert ws._seq_gaps == 7


# ── Orderbook snapshot caching ───────────────────────────────────────────────

class TestOrderbookCaching:
    def test_snapshot_cached(self, ws):
        data = {"type": "orderbook_snapshot", "ticker": "KXBTC", "bids": [], "asks": []}
        result = ws._parse_message(data)
        assert result is not None
        assert "KXBTC" in ws._ob_initialised
        assert "KXBTC" in ws._ob_snapshots

    def test_delta_without_snapshot_dropped(self, ws):
        data = {"type": "orderbook_delta", "ticker": "KXBTC", "bids": []}
        result = ws._parse_message(data)
        assert result is None

    def test_delta_with_snapshot_forwarded(self, ws):
        ws._ob_initialised.add("KXBTC")
        data = {"type": "orderbook_delta", "ticker": "KXBTC", "bids": []}
        result = ws._parse_message(data)
        assert result is not None


# ── Parse message ────────────────────────────────────────────────────────────

class TestParseMessage:
    def test_ticker_parsed(self, ws):
        data = {"type": "ticker", "ticker": "KXBTC", "bid": 55, "ask": 60, "volume": 1200}
        event = ws._parse_message(data)
        assert event is not None
        assert event.market_id == "KXBTC"

    def test_trade_parsed(self, ws):
        data = {
            "type": "trade",
            "trade_id": "t1",
            "ticker": "KXBTC",
            "order_id": "o1",
            "side": "buy",
            "count": 10,
            "price": 55,
            "fee": 7,
        }
        event = ws._parse_message(data)
        assert event is not None
        assert event.trade_id == "t1"

    def test_subscribed_skipped(self, ws):
        data = {"type": "subscribed", "channel": "ticker"}
        assert ws._parse_message(data) is None

    def test_unknown_type_returns_none(self, ws):
        data = {"type": "something_else"}
        assert ws._parse_message(data) is None


# ── Observability stats ──────────────────────────────────────────────────────

class TestStats:
    def test_stats_structure(self, ws):
        s = ws.stats()
        assert "connected" in s
        assert "messages_received" in s
        assert "errors_received" in s
        assert "reconnect_count" in s
        assert "seq_gaps" in s
        assert "queue_depth" in s
        assert "queue_max" in s
        assert "ob_cached_markets" in s
        assert "subscriptions" in s

    def test_stats_initial_values(self, ws):
        s = ws.stats()
        assert s["connected"] is False
        assert s["messages_received"] == 0
        assert s["errors_received"] == 0
        assert s["reconnect_count"] == 0
        assert s["seq_gaps"] == 0

    def test_stats_reflect_errors(self, ws):
        ws._handle_error_message({"type": "error", "code": "x", "msg": "y"})
        ws._handle_error_message({"type": "error", "code": "x", "msg": "y"})
        s = ws.stats()
        assert s["errors_received"] == 2


# ── Reconnect ────────────────────────────────────────────────────────────────

class TestReconnect:
    def test_reconnect_increments_counter(self, ws):
        ws._running = True
        ws._reconnect_delay = 0.01
        ws._max_reconnect_delay = 0.02

        async def mock_connect():
            ws._ws = MagicMock()

        ws.connect = mock_connect
        ws.subscribe_quotes = AsyncMock()
        ws.subscribe_trades = AsyncMock()
        ws.subscribe_orderbook = AsyncMock()

        asyncio.run(ws._reconnect())
        assert ws._reconnect_count == 1

    def test_reconnect_clears_state(self, ws):
        ws._running = True
        ws._reconnect_delay = 0.01
        ws._max_reconnect_delay = 0.02
        ws._ob_initialised.add("KXBTC")
        ws._ob_snapshots["KXBTC"] = {}
        ws._last_seq["KXBTC"] = 10

        async def mock_connect():
            ws._ws = MagicMock()

        ws.connect = mock_connect
        ws.subscribe_quotes = AsyncMock()
        ws.subscribe_trades = AsyncMock()
        ws.subscribe_orderbook = AsyncMock()

        asyncio.run(ws._reconnect())
        assert len(ws._ob_initialised) == 0
        assert len(ws._ob_snapshots) == 0
        assert len(ws._last_seq) == 0

    def test_not_running_skips_reconnect(self, ws):
        ws._running = False
        asyncio.run(ws._reconnect())
        assert ws._reconnect_count == 0


# ── Backpressure (queue) ─────────────────────────────────────────────────────

class TestBackpressure:
    def test_queue_has_bounded_size(self, ws):
        assert ws._msg_queue.maxsize == 4096

    def test_queue_accepts_messages(self, ws):
        ws._msg_queue.put_nowait({"type": "ticker"})
        assert ws._msg_queue.qsize() == 1

    def test_queue_reports_depth_in_stats(self, ws):
        ws._msg_queue.put_nowait({"type": "ticker"})
        ws._msg_queue.put_nowait({"type": "ticker"})
        s = ws.stats()
        assert s["queue_depth"] == 2
