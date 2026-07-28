"""
Unit tests for WsEvent parser and health semantics.

Tests the new centralized WebSocket event parsing and health check logic
introduced in the Kalshi WebSocket pipeline refactoring.
"""
import time
import pytest
from merid.event_venues.kalshi.ws_event import WsEvent, WsEventKind
from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store


class TestWsEventParser:
    """Test WsEvent.from_kalshi_message parsing correctness."""

    def test_orderbook_snapshot_with_ticker(self):
        """Parse orderbook_snapshot with top-level ticker field."""
        msg = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTCD-25JUN-T100000",
            "yes": [{"price": 50, "count": 10}],
            "no": [{"price": 50, "count": 10}],
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDERBOOK_SNAPSHOT
        assert event.ticker == "KXBTCD-25JUN-T100000"
        assert event.raw == msg

    def test_orderbook_snapshot_with_market_ticker(self):
        """Parse orderbook_snapshot with market_ticker field."""
        msg = {
            "type": "orderbook_snapshot",
            "market_ticker": "KXETHD-25JUN-T100000",
            "yes": [{"price": 50, "count": 10}],
            "no": [{"price": 50, "count": 10}],
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDERBOOK_SNAPSHOT
        assert event.ticker == "KXETHD-25JUN-T100000"

    def test_orderbook_snapshot_nested_msg(self):
        """Parse orderbook_snapshot with nested msg structure."""
        msg = {
            "msg": {
                "type": "orderbook_snapshot",
                "market_ticker": "KXSOLD-25JUN-T100000",
                "yes": [{"price": 50, "count": 10}],
                "no": [{"price": 50, "count": 10}],
            }
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDERBOOK_SNAPSHOT
        assert event.ticker == "KXSOLD-25JUN-T100000"

    def test_orderbook_delta(self):
        """Parse orderbook_delta message."""
        msg = {
            "type": "orderbook_delta",
            "ticker": "KXBTCD-25JUN-T100000",
            "delta_fp": "0.01",
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDERBOOK_DELTA
        assert event.ticker == "KXBTCD-25JUN-T100000"

    def test_ticker_snapshot(self):
        """Parse ticker snapshot message."""
        msg = {
            "type": "ticker",
            "ticker": "KXBTCD-25JUN-T100000",
            "price": 50,
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.TICKER_SNAPSHOT
        assert event.ticker == "KXBTCD-25JUN-T100000"

    def test_fill_message(self):
        """Parse fill message."""
        msg = {
            "type": "fill",
            "ticker": "KXBTCD-25JUN-T100000",
            "side": "yes",
            "count": 10,
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.FILL
        assert event.ticker == "KXBTCD-25JUN-T100000"

    def test_order_group_update(self):
        """Parse order_group_update message."""
        msg = {
            "type": "order_group_update",
            "ticker": "KXBTCD-25JUN-T100000",
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDER_GROUP_UPDATE
        assert event.ticker == "KXBTCD-25JUN-T100000"

    def test_unknown_message_type(self):
        """Parse unknown message type falls back to UNKNOWN."""
        msg = {
            "type": "unknown_type",
            "ticker": "KXBTCD-25JUN-T100000",
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.UNKNOWN
        assert event.ticker == "KXBTCD-25JUN-T100000"

    def test_missing_ticker(self):
        """Parse message without ticker returns 'unknown' ticker."""
        msg = {
            "type": "orderbook_snapshot",
            "yes": [{"price": 50, "count": 10}],
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.ticker == "unknown"

    def test_channel_field_mapping(self):
        """Parse message using channel field instead of type."""
        msg = {
            "channel": "orderbook_snapshot",
            "ticker": "KXBTCD-25JUN-T100000",
        }
        event = WsEvent.from_kalshi_message(msg)
        
        assert event.kind == WsEventKind.ORDERBOOK_SNAPSHOT

    def test_ts_received_set(self):
        """Verify ts_received is set to current monotonic time."""
        before = time.monotonic()
        msg = {"type": "orderbook_snapshot", "ticker": "KXBTCD-25JUN-T100000"}
        event = WsEvent.from_kalshi_message(msg)
        after = time.monotonic()
        
        assert before <= event.ts_received <= after


class TestKalshiMarketStateHealth:
    """Test KalshiMarketState.check_health health semantics."""

    def test_fresh_ws_tight_spread_all_healthy(self):
        """Fresh WS update with tight spread → all healthy."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0  # 1 second ago
        state.best_bid_cents = 49
        state.best_ask_cents = 51
        state.spread_cents = 2
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        assert health["liquidity_healthy"] is True
        assert health["state_consistent"] is True
        assert health["overall_healthy"] is True
        assert health["transport_mode"] == "ws"
        assert state.transport_stale is False
        assert state.illiquid is False
        assert state.state_inconsistent is False

    def test_ws_stale_rest_recent_transport_healthy(self):
        """WS stale but REST recent → transport healthy via REST."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 10.0  # 10 seconds ago (stale)
        state.last_rest_update_ts = time.monotonic() - 30.0  # 30 seconds ago (fresh)
        state.best_bid_cents = 49
        state.best_ask_cents = 51
        state.spread_cents = 2
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        assert health["transport_mode"] == "rest"
        assert state.transport_stale is False

    def test_ws_fresh_wide_spread_illiquid(self):
        """WS fresh but wide spread → illiquid but transport healthy."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0  # 1 second ago
        state.best_bid_cents = 40
        state.best_ask_cents = 60
        state.spread_cents = 20  # > 15c threshold
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        assert health["liquidity_healthy"] is False
        assert health["overall_healthy"] is False
        assert health["transport_mode"] == "ws"
        assert state.transport_stale is False
        assert state.illiquid is True

    def test_yes_no_sum_off_state_inconsistent(self):
        """YES+NO sum off by >2c → state inconsistent."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0
        state.best_bid_cents = 40
        state.best_ask_cents = 65  # 40+65=105, off by 5c (>2c threshold)
        state.spread_cents = 25  # Above 20c threshold, will be marked illiquid
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        # Spread above 20c threshold is marked illiquid
        assert health["liquidity_healthy"] is False
        assert health["state_consistent"] is False
        assert health["overall_healthy"] is False
        assert state.state_inconsistent is True

    def test_both_stale_transport_unhealthy(self):
        """Both WS and REST stale → transport unhealthy."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 10.0  # 10 seconds ago
        state.last_rest_update_ts = time.monotonic() - 70.0  # 70 seconds ago (>60s threshold)
        state.best_bid_cents = 49
        state.best_ask_cents = 51
        state.spread_cents = 2
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is False
        assert health["transport_mode"] == "none"
        assert state.transport_stale is True

    def test_shallow_depth_illiquid(self):
        """Shallow depth (zero depth) → illiquid."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0
        state.best_bid_cents = 49
        state.best_ask_cents = 51
        state.spread_cents = 2
        state.min_depth_yes = 0  # No depth
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        assert health["liquidity_healthy"] is False
        assert state.illiquid is True

    def test_no_bid_or_ask_illiquid(self):
        """Missing bid or ask → illiquid."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0
        state.best_bid_cents = None  # No bid
        state.best_ask_cents = 51
        state.spread_cents = None
        state.min_depth_yes = 0
        state.min_depth_no = 10
        
        health = state.check_health()
        
        assert health["transport_healthy"] is True
        assert health["liquidity_healthy"] is False
        assert state.illiquid is True

    def test_health_returns_all_fields(self):
        """Verify check_health returns all expected fields."""
        state = KalshiMarketState(ticker="KXBTCD-25JUN-T100000")
        state.last_book_update_ts = time.monotonic() - 1.0
        state.best_bid_cents = 49
        state.best_ask_cents = 51
        state.spread_cents = 2
        state.min_depth_yes = 10
        state.min_depth_no = 10
        
        health = state.check_health()
        
        expected_fields = {
            "transport_healthy",
            "liquidity_healthy",
            "state_consistent",
            "overall_healthy",
            "transport_mode",
            "ws_age_s",
            "rest_age_s",
            "spread_cents",
            "depth_yes",
            "depth_no",
        }
        assert set(health.keys()) == expected_fields


class TestApplyOrderbookMessageProvenance:
    """Test apply_orderbook_message provenance tracking."""

    def test_via_bridge_queue_sets_transport_mode_ws(self):
        """Call with via=bridge_queue sets transport_mode to ws."""
        store = get_kalshi_market_state_store()
        ticker = "KXBTC15M-25JUN-T100000"  # Valid 15m timeframe ticker
        
        # Create state directly to test transport_mode setting
        state = store._get_or_create(ticker)
        state.transport_mode = "unknown"  # Reset to unknown
        
        # Simulate what _sync_book_fields does with via parameter
        store._sync_book_fields(state, store._ob.get_book(ticker), ticker, via="bridge_queue")
        
        assert state.transport_mode == "ws"

    def test_via_rest_bootstrap_sets_transport_mode_rest(self):
        """Call with via=rest_bootstrap sets transport_mode to rest."""
        store = get_kalshi_market_state_store()
        ticker = "KXBTC15M-25JUN-T100000"  # Valid 15m timeframe ticker
        
        # Create state directly to test transport_mode setting
        state = store._get_or_create(ticker)
        state.transport_mode = "unknown"  # Reset to unknown
        
        # Simulate what _sync_book_fields does with via parameter
        store._sync_book_fields(state, store._ob.get_book(ticker), ticker, via="rest_bootstrap")
        
        assert state.transport_mode == "rest"

    def test_via_unknown_sets_transport_mode_unknown(self):
        """Call with via=unknown sets transport_mode to unknown."""
        store = get_kalshi_market_state_store()
        ticker = "KXBTC15M-25JUN-T100000"  # Valid 15m timeframe ticker
        
        # Create state directly to test transport_mode setting
        state = store._get_or_create(ticker)
        state.transport_mode = "ws"  # Reset to ws
        
        # Simulate what _sync_book_fields does with via parameter
        store._sync_book_fields(state, store._ob.get_book(ticker), ticker, via="unknown")
        
        assert state.transport_mode == "unknown"

    def test_via_default_unknown_sets_transport_mode_unknown(self):
        """Call without via parameter defaults to unknown."""
        store = get_kalshi_market_state_store()
        ticker = "KXBTC15M-25JUN-T100000"  # Valid 15m timeframe ticker
        
        # Create state directly to test transport_mode setting
        state = store._get_or_create(ticker)
        state.transport_mode = "ws"  # Reset to ws
        
        # Simulate what _sync_book_fields does with via parameter (default)
        store._sync_book_fields(state, store._ob.get_book(ticker), ticker)  # No via parameter
        
        assert state.transport_mode == "unknown"
