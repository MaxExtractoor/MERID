"""Tests for WebSocket price feed: PriceUpdate model, CoinbasePriceFeed, WSFeedManager.

Covers:
- PriceUpdate: construction, spread/spread_bps computation, to_dict, edge cases
- Symbol mapping: MERID↔Coinbase bidirectional
- CoinbasePriceFeed: message handling, subscriber pattern, status, latest prices,
  error counting, non-ticker message filtering
- WSFeedManager: start/stop lifecycle, status, price ingestion callback
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.signals.ws_price_feed import (
    COINBASE_TO_MERID,
    MERID_TO_COINBASE,
    CoinbasePriceFeed,
    PriceUpdate,
    WSFeedManager,
)


# ── PriceUpdate Model Tests ──────────────────────────────────────────

class TestPriceUpdate:
    """Verify PriceUpdate dataclass behavior."""

    def test_basic_construction(self):
        pu = PriceUpdate(symbol="BTC", price=50000.0, bid=49990.0, ask=50010.0)
        assert pu.symbol == "BTC"
        assert pu.venue == "coinbase"
        assert pu.price == 50000.0

    def test_spread_computation(self):
        pu = PriceUpdate(symbol="BTC", price=50000.0, bid=49990.0, ask=50010.0)
        assert pu.spread == 20.0

    def test_spread_bps_computation(self):
        pu = PriceUpdate(symbol="BTC", price=50000.0, bid=49990.0, ask=50010.0)
        # spread=20, price=50000 → 20/50000*10000 = 4.0 bps
        assert pu.spread_bps == pytest.approx(4.0)

    def test_spread_zero_when_no_bid_ask(self):
        pu = PriceUpdate(symbol="BTC", price=50000.0)
        assert pu.spread == 0.0
        assert pu.spread_bps == 0.0

    def test_spread_bps_zero_when_price_zero(self):
        pu = PriceUpdate(symbol="BTC", price=0.0, bid=10.0, ask=20.0)
        assert pu.spread_bps == 0.0

    def test_to_dict_structure(self):
        pu = PriceUpdate(
            symbol="ETH", venue="coinbase", price=3000.0,
            bid=2999.0, ask=3001.0, volume_24h=1000000.0,
        )
        d = pu.to_dict()
        assert d["symbol"] == "ETH"
        assert d["venue"] == "coinbase"
        assert d["price"] == 3000.0
        assert d["bid"] == 2999.0
        assert d["ask"] == 3001.0
        assert d["volume_24h"] == 1000000.0
        assert "spread_bps" in d
        assert "timestamp" in d

    def test_to_dict_spread_bps_rounded(self):
        pu = PriceUpdate(symbol="SOL", price=100.0, bid=99.97, ask=100.03)
        d = pu.to_dict()
        # spread=0.06, bps=0.06/100*10000=6.0
        assert d["spread_bps"] == 6.0

    def test_default_timestamp(self):
        before = time.time()
        pu = PriceUpdate(symbol="BTC")
        after = time.time()
        assert before <= pu.timestamp <= after

    def test_raw_field_default(self):
        pu = PriceUpdate(symbol="BTC")
        assert pu.raw == {}

    def test_custom_raw_data(self):
        raw = {"type": "ticker", "product_id": "BTC-USD"}
        pu = PriceUpdate(symbol="BTC", raw=raw)
        assert pu.raw["type"] == "ticker"


# ── Symbol Mapping Tests ─────────────────────────────────────────────

class TestSymbolMapping:
    """Verify bidirectional symbol mapping."""

    def test_merid_to_coinbase_known(self):
        assert MERID_TO_COINBASE["BTC"] == "BTC-USD"
        assert MERID_TO_COINBASE["ETH"] == "ETH-USD"
        assert MERID_TO_COINBASE["SOL"] == "SOL-USD"

    def test_coinbase_to_merid_known(self):
        assert COINBASE_TO_MERID["BTC-USD"] == "BTC"
        assert COINBASE_TO_MERID["ETH-USD"] == "ETH"

    def test_bidirectional_consistency(self):
        for merid, coinbase in MERID_TO_COINBASE.items():
            assert COINBASE_TO_MERID[coinbase] == merid

    def test_all_major_symbols_mapped(self):
        required = {"BTC", "ETH", "SOL", "AVAX", "LINK", "POL", "DOGE"}
        assert required.issubset(set(MERID_TO_COINBASE.keys()))

    def test_no_stablecoins_in_map(self):
        for sym in ("USDT", "USDC", "DAI"):
            assert sym not in MERID_TO_COINBASE, f"Stablecoin {sym} should not appear in Coinbase WS map"


# ── CoinbasePriceFeed Tests ──────────────────────────────────────────

class TestCoinbasePriceFeedMessageHandling:
    """Verify _handle_message processes ticker data correctly."""

    @pytest.fixture
    def feed(self):
        return CoinbasePriceFeed(["BTC-USD", "ETH-USD"])

    def test_handles_ticker_message(self, feed):
        msg = {
            "type": "ticker",
            "product_id": "BTC-USD",
            "price": "50000.00",
            "best_bid": "49990.00",
            "best_ask": "50010.00",
            "volume_24h": "1234.56",
        }
        feed._handle_message(msg)
        assert "BTC" in feed._latest_prices
        pu = feed._latest_prices["BTC"]
        assert pu.price == 50000.0
        assert pu.bid == 49990.0
        assert pu.ask == 50010.0
        assert pu.volume_24h == 1234.56

    def test_ignores_non_ticker_messages(self, feed):
        feed._handle_message({"type": "subscriptions"})
        feed._handle_message({"type": "heartbeat"})
        feed._handle_message({"type": "error", "message": "bad"})
        assert len(feed._latest_prices) == 0
        assert feed._message_count == 0

    def test_increments_message_count(self, feed):
        msg = {"type": "ticker", "product_id": "BTC-USD", "price": "50000"}
        feed._handle_message(msg)
        feed._handle_message(msg)
        assert feed._message_count == 2

    def test_handles_unknown_product_id(self, feed):
        msg = {"type": "ticker", "product_id": "UNKNOWN-USD", "price": "1.0"}
        feed._handle_message(msg)
        assert "UNKNOWN" in feed._latest_prices

    def test_handles_missing_fields_gracefully(self, feed):
        msg = {"type": "ticker", "product_id": "BTC-USD"}
        feed._handle_message(msg)
        pu = feed._latest_prices["BTC"]
        assert pu.price == 0.0
        assert pu.bid == 0.0

    def test_overwrites_latest_price(self, feed):
        msg1 = {"type": "ticker", "product_id": "BTC-USD", "price": "50000"}
        msg2 = {"type": "ticker", "product_id": "BTC-USD", "price": "51000"}
        feed._handle_message(msg1)
        feed._handle_message(msg2)
        assert feed._latest_prices["BTC"].price == 51000.0

    def test_tracks_multiple_symbols(self, feed):
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        feed._handle_message({"type": "ticker", "product_id": "ETH-USD", "price": "3000"})
        assert len(feed._latest_prices) == 2
        assert feed._latest_prices["BTC"].price == 50000.0
        assert feed._latest_prices["ETH"].price == 3000.0


class TestCoinbasePriceFeedSubscribers:
    """Verify subscriber pattern."""

    @pytest.fixture
    def feed(self):
        return CoinbasePriceFeed(["BTC-USD"])

    def test_subscribe_receives_updates(self, feed):
        received = []
        feed.subscribe(lambda pu: received.append(pu))
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        assert len(received) == 1
        assert received[0].symbol == "BTC"

    def test_multiple_subscribers(self, feed):
        r1, r2 = [], []
        feed.subscribe(lambda pu: r1.append(pu))
        feed.subscribe(lambda pu: r2.append(pu))
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        assert len(r1) == 1
        assert len(r2) == 1

    def test_unsubscribe(self, feed):
        received = []
        cb = lambda pu: received.append(pu)
        feed.subscribe(cb)
        feed.unsubscribe(cb)
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        assert len(received) == 0

    def test_bad_subscriber_does_not_break_feed(self, feed):
        good_received = []
        feed.subscribe(lambda pu: 1 / 0)  # Bad subscriber
        feed.subscribe(lambda pu: good_received.append(pu))
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        assert len(good_received) == 1


class TestCoinbasePriceFeedAccessors:
    """Verify latest() and all_latest() accessors."""

    def test_latest_returns_none_when_empty(self):
        feed = CoinbasePriceFeed()
        assert feed.latest("BTC") is None

    def test_latest_returns_update(self):
        feed = CoinbasePriceFeed()
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        pu = feed.latest("BTC")
        assert pu is not None
        assert pu.price == 50000.0

    def test_all_latest_returns_copy(self):
        feed = CoinbasePriceFeed()
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        all_prices = feed.all_latest()
        assert "BTC" in all_prices
        # Verify it's a copy
        all_prices.pop("BTC")
        assert feed.latest("BTC") is not None


class TestCoinbasePriceFeedStatus:
    """Verify status reporting."""

    def test_status_initial(self):
        feed = CoinbasePriceFeed(["BTC-USD"])
        s = feed.status()
        assert s["connected"] is False
        assert s["products"] == ["BTC-USD"]
        assert s["message_count"] == 0
        assert s["error_count"] == 0
        assert s["uptime_seconds"] == 0

    def test_status_after_messages(self):
        feed = CoinbasePriceFeed(["BTC-USD"])
        feed._connected_at = time.time() - 60
        feed._running = True
        feed._handle_message({"type": "ticker", "product_id": "BTC-USD", "price": "50000"})
        s = feed.status()
        assert s["message_count"] == 1
        assert "BTC" in s["latest_prices"]
        assert s["uptime_seconds"] >= 59

    def test_status_error_count(self):
        feed = CoinbasePriceFeed()
        feed._error_count = 5
        s = feed.status()
        assert s["error_count"] == 5


class TestCoinbasePriceFeedErrorHandling:
    """Verify error counting on bad data."""

    def test_invalid_price_data_increments_error(self):
        feed = CoinbasePriceFeed()
        # Inject a message where price conversion will fail
        msg = {"type": "ticker", "product_id": "BTC-USD", "price": "not_a_number"}
        feed._handle_message(msg)
        assert feed._error_count == 1
        assert "BTC" not in feed._latest_prices


class TestCoinbasePriceFeedLifecycle:
    """Verify connect/disconnect without real WebSocket."""

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        feed = CoinbasePriceFeed()
        await feed.disconnect()  # Should not raise
        assert feed._running is False

    @pytest.mark.asyncio
    async def test_connect_without_websockets_package(self):
        feed = CoinbasePriceFeed()
        with patch.dict("sys.modules", {"websockets": None}):
            # connect() should handle ImportError gracefully and return early
            await feed.connect()
        # Feed degrades gracefully — _running stays False when websockets unavailable
        assert feed._running is False


# ── WSFeedManager Tests ──────────────────────────────────────────────

class TestWSFeedManager:
    """Verify WSFeedManager lifecycle and status."""

    def test_initial_state(self):
        mgr = WSFeedManager()
        assert mgr.is_active is False
        s = mgr.status()
        assert s["active"] is False

    @pytest.mark.asyncio
    async def test_start_with_unmappable_symbols(self):
        mgr = WSFeedManager()
        await mgr.start(["UNKNOWN1", "UNKNOWN2"])
        assert mgr.is_active is False

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        mgr = WSFeedManager()
        await mgr.stop()  # Should not raise
        assert mgr.is_active is False

    def test_status_when_feed_active(self):
        mgr = WSFeedManager()
        feed = CoinbasePriceFeed(["BTC-USD"])
        feed._running = True
        feed._connected_at = time.time()
        mgr._feed = feed
        mgr._active = True
        s = mgr.status()
        assert s["active"] is True
        assert "products" in s

    def test_on_price_update_callback(self):
        mgr = WSFeedManager()
        update = PriceUpdate(symbol="BTC", price=50000.0)
        # _on_price_update should not raise even if feature service is unavailable
        mgr._on_price_update(update)  # Should handle import/init errors gracefully
