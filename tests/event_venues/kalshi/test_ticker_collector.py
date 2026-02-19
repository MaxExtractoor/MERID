"""Tests for TickerCollector — WS ticker data into pandas DataFrame."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from merid.event_venues.kalshi.ticker_collector import (
    TickRecord,
    TickerCollector,
    _COLS,
)


# ── TickRecord ───────────────────────────────────────────────────────────────

class TestTickRecord:
    def test_to_dict_keys(self):
        r = TickRecord(ts=1000.0, market_id="KXBTC-1H", yes_bid=0.55, yes_ask=0.60)
        d = r.to_dict()
        assert set(d.keys()) == {"ts", "market_id", "yes_bid", "yes_ask", "last_price", "volume", "spread"}

    def test_spread_computed(self):
        r = TickRecord(ts=1000.0, market_id="X", yes_bid=0.50, yes_ask=0.60, spread=0.10)
        assert r.spread == 0.10

    def test_defaults_none(self):
        r = TickRecord(ts=1000.0, market_id="X")
        assert r.yes_bid is None
        assert r.volume is None


# ── TickerCollector core ─────────────────────────────────────────────────────

class TestCollectorBuffer:
    def test_empty_snapshot_returns_empty(self):
        c = TickerCollector(max_rows=100)
        df = c.snapshot()
        assert len(df) == 0

    def test_ingest_via_handler(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {
            "payload": {
                "market_id": "KXBTC-1H",
                "bid": 0.55,
                "ask": 0.60,
                "last": 0.58,
                "volume": 1200,
            }
        }
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 1
        assert len(c._buffer) == 1

    def test_spread_calculated_on_ingest(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {
            "payload": {
                "market_id": "X",
                "bid": 0.50,
                "ask": 0.58,
            }
        }
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        row = list(c._buffer)[0]
        assert row["spread"] == pytest.approx(0.08, abs=0.001)

    def test_buffer_ring_behavior(self):
        c = TickerCollector(max_rows=5)
        c._running = True
        for i in range(10):
            event = {"payload": {"market_id": f"M{i}", "bid": 0.5, "ask": 0.6}}
            asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert len(c._buffer) == 5
        assert c._ticks_ingested == 10
        # Oldest should be M5 (first 5 dropped)
        assert list(c._buffer)[0]["market_id"] == "M5"

    def test_not_running_ignores_events(self):
        c = TickerCollector(max_rows=100)
        c._running = False
        event = {"payload": {"market_id": "X", "bid": 0.5, "ask": 0.6}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 0


class TestCollectorSnapshot:
    def _ingest(self, c, market_id, bid=0.50, ask=0.60):
        c._running = True
        event = {"payload": {"market_id": market_id, "bid": bid, "ask": ask, "volume": 100}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))

    def test_snapshot_all(self):
        c = TickerCollector(max_rows=100)
        self._ingest(c, "A")
        self._ingest(c, "B")
        df = c.snapshot()
        assert len(df) == 2

    def test_snapshot_filtered(self):
        c = TickerCollector(max_rows=100)
        self._ingest(c, "A")
        self._ingest(c, "B")
        self._ingest(c, "A")
        df = c.snapshot(market_id="A")
        assert len(df) == 2

    def test_market_ids(self):
        c = TickerCollector(max_rows=100)
        self._ingest(c, "B")
        self._ingest(c, "A")
        self._ingest(c, "C")
        assert c.market_ids() == ["A", "B", "C"]

    def test_latest(self):
        c = TickerCollector(max_rows=100)
        for i in range(30):
            self._ingest(c, f"M{i}")
        latest = c.latest(n=5)
        assert len(latest) == 5
        assert latest[-1]["market_id"] == "M29"


class TestCollectorResample:
    def _ingest_n(self, c, n, market_id="BTC"):
        c._running = True
        for i in range(n):
            event = {
                "payload": {
                    "market_id": market_id,
                    "bid": 0.50 + i * 0.001,
                    "ask": 0.55 + i * 0.001,
                    "last": 0.52 + i * 0.001,
                    "volume": 100 + i,
                }
            }
            asyncio.get_event_loop().run_until_complete(c._on_price_update(event))

    def test_resample_empty(self):
        c = TickerCollector(max_rows=100)
        result = c.resample("5min")
        assert len(result) == 0

    def test_resample_produces_bars(self):
        c = TickerCollector(max_rows=100)
        self._ingest_n(c, 10)
        bars = c.resample("1min")
        # All ticks are within ~same second, so 1 bar
        assert len(bars) >= 1
        assert "close" in bars.columns
        assert "tick_count" in bars.columns
        assert "spread_mean" in bars.columns


class TestMalformedMessages:
    """Ensure malformed or incomplete payloads don't crash the handler."""

    def test_empty_payload(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {"payload": {}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 1
        row = list(c._buffer)[0]
        assert row["market_id"] == ""
        assert row["yes_bid"] is None
        assert row["spread"] is None

    def test_missing_payload_key(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {}  # no 'payload' key at all
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 1
        row = list(c._buffer)[0]
        assert row["market_id"] == ""

    def test_partial_payload_bid_only(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {"payload": {"market_id": "X", "bid": 0.55}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        row = list(c._buffer)[0]
        assert row["yes_bid"] == 0.55
        assert row["yes_ask"] is None
        assert row["spread"] is None  # can't compute without ask

    def test_partial_payload_ask_only(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {"payload": {"market_id": "Y", "ask": 0.60}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        row = list(c._buffer)[0]
        assert row["yes_ask"] == 0.60
        assert row["yes_bid"] is None

    def test_none_values_in_payload(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {"payload": {"market_id": "Z", "bid": None, "ask": None, "volume": None}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        row = list(c._buffer)[0]
        assert row["yes_bid"] is None
        assert row["spread"] is None


class TestKalshiFormatMessages:
    """Test with messages shaped like raw Kalshi WS ticker data."""

    def test_kalshi_ticker_format(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        # Simulate how the bridge transforms a Kalshi ticker into an event
        event = {
            "payload": {
                "market_id": "KXBTC-26FEB16-1H-T95000",
                "bid": 0.62,
                "ask": 0.64,
                "last": 0.63,
                "volume": 1500,
            }
        }
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 1
        row = list(c._buffer)[0]
        assert row["market_id"] == "KXBTC-26FEB16-1H-T95000"
        assert row["yes_bid"] == 0.62
        assert row["yes_ask"] == 0.64
        assert row["last_price"] == 0.63
        assert row["volume"] == 1500
        assert row["spread"] == pytest.approx(0.02, abs=0.001)

    def test_multiple_kalshi_tickers(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        tickers = [
            {"market_id": "KXBTC-1H", "bid": 0.55, "ask": 0.60, "volume": 1000},
            {"market_id": "KXETH-15M", "bid": 0.45, "ask": 0.47, "volume": 500},
            {"market_id": "KXBTC-1H", "bid": 0.56, "ask": 0.61, "volume": 1050},
        ]
        for t in tickers:
            event = {"payload": t}
            asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 3
        assert len(c.market_ids()) == 2
        df = c.snapshot(market_id="KXBTC-1H")
        assert len(df) == 2

    def test_high_frequency_burst(self):
        c = TickerCollector(max_rows=1000)
        c._running = True
        for i in range(500):
            event = {
                "payload": {
                    "market_id": f"KXBTC-{i % 5}",
                    "bid": 0.50 + (i % 10) * 0.01,
                    "ask": 0.55 + (i % 10) * 0.01,
                    "volume": 100 + i,
                }
            }
            asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        assert c._ticks_ingested == 500
        assert len(c._buffer) == 500
        assert len(c.market_ids()) == 5


class TestCollectorStats:
    def test_stats_structure(self):
        c = TickerCollector(max_rows=100)
        s = c.stats()
        assert "running" in s
        assert "ticks_ingested" in s
        assert "buffer_size" in s
        assert "buffer_max" in s
        assert s["buffer_max"] == 100

    def test_stats_after_ingest(self):
        c = TickerCollector(max_rows=100)
        c._running = True
        event = {"payload": {"market_id": "X", "bid": 0.5, "ask": 0.6}}
        asyncio.get_event_loop().run_until_complete(c._on_price_update(event))
        s = c.stats()
        assert s["ticks_ingested"] == 1
        assert s["buffer_size"] == 1
        assert s["unique_markets"] == 1
