"""Tests for KalshiMarketState, KalshiMarketStateStore, and _resolve_tif."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.market_state import (
    KalshiMarketStateStore,
    _recompute_seconds_to_expiry,
    IOC_AUTO_BELOW_SECONDS,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _iso(seconds_from_now: float) -> str:
    """Return an ISO-8601 string *seconds_from_now* seconds in the future."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot_msg(ticker: str, yes: list, no: list) -> dict:
    return {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "msg": {"yes": yes, "no": no},
    }


def _delta_msg(ticker: str, side: str, price: int, size_delta: int) -> dict:
    return {
        "type": "orderbook_delta",
        "ticker": ticker,
        "side": side,
        "price": price,
        "size_delta": size_delta,
    }


# ── KalshiMarketState dataclass ────────────────────────────────────────────


class TestKalshiMarketState:
    def test_defaults(self):
        s = KalshiMarketState(ticker="TEST-01")
        assert s.ticker == "TEST-01"
        assert s.yes_bids == []
        assert s.no_bids == []
        assert s.best_bid_cents is None
        assert s.best_ask_cents is None
        assert s.mid_cents is None
        assert s.spread_cents is None
        assert s.top_of_book_size == 0
        assert s.depth_10c == 0
        assert s.book_initialized is False
        assert s.last_book_update_ts == 0.0
        # REST numeric fields default to 0 until first REST merge (unknown ≠ unset for ints)
        assert s.volume_24h == 0
        assert s.open_interest == 0
        assert s.notional_value_cents == 0
        assert s.expiration_time is None
        assert s.expected_expiration_time is None
        assert s.latest_expiration_time is None
        assert s.seconds_to_expiry is None
        assert s.last_rest_update_ts == 0.0

    def test_fields_are_independent(self):
        a = KalshiMarketState(ticker="A")
        b = KalshiMarketState(ticker="B")
        a.yes_bids.append((55, 10))
        assert b.yes_bids == []


# ── _recompute_seconds_to_expiry ───────────────────────────────────────────


class TestRecomputeSecondsToExpiry:
    def test_uses_expected_expiration_time_first(self):
        s = KalshiMarketState(ticker="T")
        s.expected_expiration_time = _iso(300)
        s.expiration_time = _iso(600)
        _recompute_seconds_to_expiry(s)
        assert s.seconds_to_expiry is not None
        assert 290 < s.seconds_to_expiry < 310

    def test_falls_back_to_expiration_time(self):
        s = KalshiMarketState(ticker="T")
        s.expiration_time = _iso(900)
        _recompute_seconds_to_expiry(s)
        assert s.seconds_to_expiry is not None
        assert 890 < s.seconds_to_expiry < 910

    def test_zero_floor_for_past_expiry(self):
        s = KalshiMarketState(ticker="T")
        s.expiration_time = _iso(-60)
        _recompute_seconds_to_expiry(s)
        assert s.seconds_to_expiry == 0.0

    def test_none_when_no_expiry(self):
        s = KalshiMarketState(ticker="T")
        _recompute_seconds_to_expiry(s)
        assert s.seconds_to_expiry is None

    def test_none_on_bad_format(self):
        s = KalshiMarketState(ticker="T")
        s.expiration_time = "not-a-date"
        _recompute_seconds_to_expiry(s)
        assert s.seconds_to_expiry is None


# ── KalshiMarketStateStore — WS path ──────────────────────────────────────


class TestMarketStateStoreWS:
    def setup_method(self):
        self.store = KalshiMarketStateStore()

    def test_unknown_channel_returns_none(self):
        result = self.store.apply_orderbook_message({"type": "trade", "ticker": "X"})
        assert result is None

    def test_missing_ticker_returns_none(self):
        result = self.store.apply_orderbook_message({"type": "orderbook_snapshot"})
        assert result is None

    def test_snapshot_creates_state(self):
        msg = _snapshot_msg("KXBTC-01", [[60, 5], [55, 10]], [[40, 8], [45, 3]])
        state = self.store.apply_orderbook_message(msg)
        assert state is not None
        assert state.ticker == "KXBTC-01"
        assert state.book_initialized is True

    def test_snapshot_populates_best_bid_ask(self):
        msg = _snapshot_msg("KXBTC-01", [[60, 5], [55, 10]], [[35, 8]])
        state = self.store.apply_orderbook_message(msg)
        # best yes_bid = 60; best_ask = 100 - 35 = 65
        assert state.best_bid_cents == 60
        assert state.best_ask_cents == 65

    def test_snapshot_computes_mid(self):
        msg = _snapshot_msg("KXBTC-01", [[60, 5]], [[40, 8]])
        state = self.store.apply_orderbook_message(msg)
        # mid = (60 + (100-40)) / 2 = (60 + 60) / 2 = 60
        assert state.mid_cents == 60.0

    def test_snapshot_computes_spread(self):
        msg = _snapshot_msg("KXBTC-01", [[58, 5]], [[38, 8]])
        state = self.store.apply_orderbook_message(msg)
        # spread = (100-38) - 58 = 62 - 58 = 4
        assert state.spread_cents == 4

    def test_snapshot_top_of_book_size(self):
        msg = _snapshot_msg("KXBTC-01", [[60, 7]], [[40, 3]])
        state = self.store.apply_orderbook_message(msg)
        assert state.top_of_book_size == 10  # 7 + 3

    def test_delta_dropped_before_snapshot(self):
        result = self.store.apply_orderbook_message(
            _delta_msg("KXBTC-NEW", "yes", 55, 5)
        )
        # delta before snapshot → dropped, None returned
        assert result is None

    def test_delta_after_snapshot_updates_book(self):
        self.store.apply_orderbook_message(
            _snapshot_msg("KXBTC-02", [[60, 5]], [[40, 8]])
        )
        state = self.store.apply_orderbook_message(
            _delta_msg("KXBTC-02", "yes", 60, -3)
        )
        # yes level 60 was 5, delta -3 → now 2
        assert state is not None
        best = state.best_bid_cents
        assert best == 60

    def test_last_book_update_ts_updated(self):
        msg = _snapshot_msg("KXBTC-03", [[55, 2]], [[45, 2]])
        before = time.monotonic()
        state = self.store.apply_orderbook_message(msg)
        assert state.last_book_update_ts >= before

    def test_get_returns_same_state(self):
        msg = _snapshot_msg("KXBTC-04", [[55, 2]], [[45, 2]])
        self.store.apply_orderbook_message(msg)
        s = self.store.get("KXBTC-04")
        assert s is not None
        assert s.ticker == "KXBTC-04"

    def test_get_unknown_ticker_returns_none(self):
        assert self.store.get("DOES-NOT-EXIST") is None

    def test_depth_10c_computed(self):
        # yes = [(60, 5), (45, 10)], no = [(42, 8)]
        # best_bid = 60, best_no_price = 42, best_ask = 100-42 = 58
        # mid = (60+58)/2 = 59, lo = 49, hi = 69
        # within window:  yes p=60 (60≤69) ✓ sz=5
        #                 yes p=45 (45<49) ✗
        #                 no  p=42 → equiv=58 (49≤58≤69) ✓ sz=8
        msg = _snapshot_msg("KXBTC-05", [[60, 5], [45, 10]], [[42, 8]])
        state = self.store.apply_orderbook_message(msg)
        assert state.depth_10c == 5 + 8

    def test_market_ticker_fallback(self):
        """apply_orderbook_message accepts market_ticker key too."""
        msg = {
            "type": "orderbook_snapshot",
            "market_ticker": "KXBTC-06",
            "msg": {"yes": [[55, 2]], "no": [[45, 2]]},
        }
        state = self.store.apply_orderbook_message(msg)
        assert state is not None
        assert state.ticker == "KXBTC-06"


# ── KalshiMarketStateStore — REST path ────────────────────────────────────


class TestMarketStateStoreREST:
    def setup_method(self):
        self.store = KalshiMarketStateStore()

    def test_missing_ticker_returns_none(self):
        assert self.store.apply_rest_market({"volume_24h": 100}) is None

    def test_volume_and_oi_populated(self):
        state = self.store.apply_rest_market({
            "ticker": "KXBTC-10",
            "volume_24h": 500,
            "open_interest": 200,
            "notional_value": 12500,
        })
        assert state.volume_24h == 500
        assert state.open_interest == 200
        assert state.notional_value_cents == 12500

    def test_expiry_fields_populated(self):
        state = self.store.apply_rest_market({
            "ticker": "KXBTC-11",
            "expiration_time": "2025-12-31T23:59:59Z",
            "expected_expiration_time": "2025-12-31T20:00:00Z",
            "latest_expiration_time": "2026-01-01T06:00:00Z",
        })
        assert state.expiration_time == "2025-12-31T23:59:59Z"
        assert state.expected_expiration_time == "2025-12-31T20:00:00Z"
        assert state.latest_expiration_time == "2026-01-01T06:00:00Z"

    def test_seconds_to_expiry_recomputed(self):
        state = self.store.apply_rest_market({
            "ticker": "KXBTC-12",
            "expected_expiration_time": _iso(1800),
        })
        assert state.seconds_to_expiry is not None
        assert 1790 < state.seconds_to_expiry < 1810

    def test_deprecated_liquidity_field_ignored(self):
        """liquidity / liquidity_dollars must not overwrite our computed metrics."""
        state = self.store.apply_rest_market({
            "ticker": "KXBTC-13",
            "liquidity": 0,
            "liquidity_dollars": 0,
            "volume_24h": 300,
        })
        # top_of_book_size and depth_10c come from the book; REST never sets them
        assert state.top_of_book_size == 0
        assert state.depth_10c == 0

    def test_rest_does_not_clear_book_fields(self):
        """REST update must not wipe already-populated orderbook fields."""
        snap = _snapshot_msg("KXBTC-14", [[60, 5]], [[40, 8]])
        self.store.apply_orderbook_message(snap)
        self.store.apply_rest_market({"ticker": "KXBTC-14", "volume_24h": 100})
        state = self.store.get("KXBTC-14")
        assert state.best_bid_cents == 60
        assert state.book_initialized is True

    def test_last_rest_update_ts_updated(self):
        before = time.monotonic()
        state = self.store.apply_rest_market({"ticker": "KXBTC-15", "volume_24h": 1})
        assert state.last_rest_update_ts >= before

    def test_partial_update_preserves_existing(self):
        self.store.apply_rest_market({
            "ticker": "KXBTC-16",
            "volume_24h": 100,
            "open_interest": 50,
        })
        self.store.apply_rest_market({
            "ticker": "KXBTC-16",
            "expected_expiration_time": _iso(600),
        })
        state = self.store.get("KXBTC-16")
        assert state.volume_24h == 100
        assert state.open_interest == 50


# ── _resolve_tif ──────────────────────────────────────────────────────────


class TestResolveTif:
    """Tests for the order-router's _resolve_tif() helper."""

    def _make_intent(self, tif="gtc", order_expiration_ts=None):
        from merid.event_venues.kalshi.order_router import OrderIntent
        return OrderIntent(
            ticker="KXBTC-ROUTER",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            time_in_force=tif,
            order_expiration_ts=order_expiration_ts,
        )

    def _store_with_secs(self, ticker: str, secs: float) -> KalshiMarketStateStore:
        store = KalshiMarketStateStore()
        state = store._get_or_create(ticker)
        state.seconds_to_expiry = secs
        return store

    # _resolve_tif does a local import inside the function body, so the patch
    # target must be the module where the function lives, not order_router.
    _PATCH = "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"

    def test_ioc_when_near_expiry(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", IOC_AUTO_BELOW_SECONDS - 1)
        with patch(self._PATCH, return_value=store):
            tif, exp_ts = _resolve_tif(self._make_intent("gtc"))
        assert tif == "IOC"
        assert exp_ts is None

    def test_ioc_strips_expiration_ts_when_near_expiry(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", 10)
        with patch(self._PATCH, return_value=store):
            tif, exp_ts = _resolve_tif(self._make_intent("gtc", order_expiration_ts=9999999))
        assert tif == "IOC"
        assert exp_ts is None

    def test_gtt_when_expiration_ts_provided(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", 3600)
        future_ts = int(time.time()) + 1800
        with patch(self._PATCH, return_value=store):
            tif, exp_ts = _resolve_tif(self._make_intent("gtc", order_expiration_ts=future_ts))
        assert tif == "GTT"
        assert exp_ts == future_ts

    def test_ioc_intent_stays_ioc_no_expiry(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", 3600)
        with patch(self._PATCH, return_value=store):
            tif, exp_ts = _resolve_tif(self._make_intent("ioc"))
        assert tif == "IOC"
        assert exp_ts is None

    def test_ioc_with_expiration_ts_drops_ts(self):
        """IoC must never carry an expiration_ts even if caller set one."""
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", 3600)
        with patch(self._PATCH, return_value=store):
            tif, exp_ts = _resolve_tif(self._make_intent("ioc", order_expiration_ts=9999999))
        assert tif == "IOC"
        assert exp_ts is None

    def test_unknown_tif_normalises_to_gtc(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        store = self._store_with_secs("KXBTC-ROUTER", 3600)
        with patch(self._PATCH, return_value=store):
            tif, _ = _resolve_tif(self._make_intent("bogus"))
        assert tif == "GTC"

    def test_no_market_state_passes_through(self):
        """If no state exists for the ticker, _resolve_tif should not crash."""
        from merid.event_venues.kalshi.order_router import _resolve_tif
        empty_store = KalshiMarketStateStore()
        with patch(self._PATCH, return_value=empty_store):
            tif, exp_ts = _resolve_tif(self._make_intent("gtc"))
        assert tif == "GTC"
        assert exp_ts is None


# ── VenueOrder.expiration_ts ───────────────────────────────────────────────


class TestVenueOrderExpirationTs:
    def test_default_is_none(self):
        from decimal import Decimal
        from merid.event_venues.base import VenueOrder
        order = VenueOrder(market_id="T", side="buy", size=Decimal("5"))
        assert order.expiration_ts is None

    def test_can_set_gtt(self):
        from decimal import Decimal
        from merid.event_venues.base import VenueOrder
        order = VenueOrder(
            market_id="T", side="buy", size=Decimal("5"),
            time_in_force="GTT", expiration_ts=1999999999,
        )
        assert order.time_in_force == "GTT"
        assert order.expiration_ts == 1999999999


# ── OrderIntent.order_expiration_ts ───────────────────────────────────────


class TestOrderIntentExpirationTs:
    def test_default_is_none(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(ticker="T", side="yes", action="buy", price_cents=50, count=1)
        assert intent.order_expiration_ts is None

    def test_can_set(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(
            ticker="T", side="yes", action="buy", price_cents=50, count=1,
            time_in_force="GTT", order_expiration_ts=2000000000,
        )
        assert intent.order_expiration_ts == 2000000000


# ── apply_quote tests ────────────────────────────────────────────────────


class TestMarketStateStoreQuote:
    """Tests for KalshiMarketStateStore.apply_quote()."""

    def test_apply_quote_creates_state(self):
        store = KalshiMarketStateStore()
        state = store.apply_quote("KXBTC-T100", bid_cents=45, ask_cents=55)
        assert state is not None
        assert state.ticker == "KXBTC-T100"

    def test_apply_quote_sets_bid_ask_mid_spread(self):
        store = KalshiMarketStateStore()
        state = store.apply_quote("KXBTC-T100", bid_cents=40, ask_cents=60)
        assert state.best_bid_cents == 40
        assert state.best_ask_cents == 60
        assert state.mid_cents == 50
        assert state.spread_cents == 20

    def test_apply_quote_sets_volume(self):
        store = KalshiMarketStateStore()
        state = store.apply_quote("KXBTC-T100", volume=1234)
        assert state.volume_24h == 1234

    def test_apply_quote_last_price_fallback(self):
        store = KalshiMarketStateStore()
        state = store.apply_quote("KXBTC-T100", last_cents=47)
        assert state.mid_cents == 47

    def test_apply_quote_empty_ticker_returns_none(self):
        store = KalshiMarketStateStore()
        assert store.apply_quote("") is None

    def test_apply_quote_no_overwrite_when_book_initialized(self):
        """When orderbook is initialized, quote bid/ask should NOT overwrite book data."""
        store = KalshiMarketStateStore()
        # First: initialize via orderbook snapshot
        store.apply_orderbook_message(_snapshot_msg(
            "KXBTC-T100",
            yes=[[42, 10], [40, 5]],
            no=[[55, 8]],
        ))
        ob_state = store.get("KXBTC-T100")
        assert ob_state.book_initialized is True
        ob_bid = ob_state.best_bid_cents
        ob_ask = ob_state.best_ask_cents

        # Now: apply quote with different bid/ask
        store.apply_quote("KXBTC-T100", bid_cents=10, ask_cents=90, volume=5000)

        state = store.get("KXBTC-T100")
        # bid/ask should stay from orderbook, not overwritten by quote
        assert state.best_bid_cents == ob_bid
        assert state.best_ask_cents == ob_ask
        # volume should always update
        assert state.volume_24h == 5000

    def test_apply_quote_updates_timestamp(self):
        store = KalshiMarketStateStore()
        t0 = time.monotonic()
        store.apply_quote("KXBTC-T100", bid_cents=45, ask_cents=55)
        state = store.get("KXBTC-T100")
        assert state.last_book_update_ts >= t0


# ── WS bridge → MarketStateStore pipeline tests ─────────────────────────


class TestWSBridgeMarketStatePipeline:
    """Verify the WS bridge feeds events into KalshiMarketStateStore."""

    def test_bridge_publish_event_feeds_orderbook_to_store(self):
        """_publish_event for orderbook_snapshot should call apply_orderbook_message."""
        import asyncio
        from unittest.mock import AsyncMock, patch as _patch

        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

        mock_ws = MagicMock()
        bridge = KalshiWebSocketBridge(ws=mock_ws)

        ob_event = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTC-T100",
            "msg": {"yes": [[50, 10]], "no": [[45, 5]]},
        }

        mock_store = MagicMock()
        with _patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=mock_store,
        ), _patch.object(bridge, "_publish_to_bus", new_callable=AsyncMock):
            asyncio.run(bridge._publish_event(ob_event))

        mock_store.apply_orderbook_message.assert_called_once_with(ob_event)

    def test_bridge_publish_event_feeds_quote_to_store(self):
        """_publish_event for QuoteEvent should call apply_quote."""
        import asyncio
        from unittest.mock import AsyncMock, patch as _patch
        from merid.event_venues.base import QuoteEvent
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        from decimal import Decimal
        from datetime import datetime, timezone

        mock_ws = MagicMock()
        bridge = KalshiWebSocketBridge(ws=mock_ws)

        quote = QuoteEvent(
            market_id="KXBTC-T100",
            outcome_id=None,
            bid_price=Decimal("0.45"),
            ask_price=Decimal("0.55"),
            last_price=Decimal("0.50"),
            volume=Decimal("1000"),
            timestamp=datetime.now(timezone.utc),
        )

        mock_store = MagicMock()
        with _patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=mock_store,
        ), _patch.object(bridge, "_publish_to_bus", new_callable=AsyncMock):
            asyncio.run(bridge._publish_event(quote))

        mock_store.apply_quote.assert_called_once()
        call_kwargs = mock_store.apply_quote.call_args
        assert call_kwargs[0][0] == "KXBTC-T100"  # positional ticker
        assert call_kwargs[1]["bid_cents"] == 45
        assert call_kwargs[1]["ask_cents"] == 55
        assert call_kwargs[1]["volume"] == 1000
