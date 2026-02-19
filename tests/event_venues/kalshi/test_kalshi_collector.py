"""Tests for Kalshi Historical Data Collector."""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.archiver import SnapshotArchiver
from merid.event_venues.kalshi.collector import (
    CRYPTO_SERIES,
    CollectionResult,
    CollectorConfig,
    HistoricalCollector,
)
from merid.event_venues.kalshi.historical_sim import HistoricalTrade


# ── Helpers ────────────────────────────────────────────────────────────

def _mock_client(markets=None, trades=None):
    """Create a mock KalshiVenueClient."""
    client = AsyncMock()

    # list_markets_result returns OperationResult-like object
    market_result = MagicMock()
    market_result.success = True
    market_result.data = markets or []
    client.list_markets_result = AsyncMock(return_value=market_result)

    # _request_with_resilience for trades endpoint
    trade_result = MagicMock()
    trade_result.success = True
    trade_result.data = {"trades": trades or [], "cursor": None}
    client._request_with_resilience = AsyncMock(return_value=trade_result)

    return client


def _mock_market(ticker="KXBTC-H-55-60", resolved=True, active=False):
    """Create a mock EventMarket."""
    m = MagicMock()
    m.market_id = ticker
    m.question = f"BTC hourly {ticker}"
    m.end_date = None
    m.category = "crypto"
    m.resolved = resolved
    m.active = active
    return m


def _mock_trade(ts=1739664000, price=55, size=10, side="buy"):
    return {
        "created_time": ts,
        "price": price,
        "count": size,
        "taker_side": side,
    }


# ── Config ────────────────────────────────────────────────────────────

class TestConfig:
    def test_default_config(self):
        cfg = CollectorConfig()
        assert cfg.max_markets_per_run == 200
        assert cfg.inter_request_delay == 0.2
        assert cfg.lookback_days == 30

    def test_crypto_series(self):
        assert "BTC" in CRYPTO_SERIES
        assert "ETH" in CRYPTO_SERIES
        assert CRYPTO_SERIES["BTC"] == "KXBTC"


# ── Collection result ─────────────────────────────────────────────────

class TestCollectionResult:
    def test_to_dict(self):
        r = CollectionResult(asset="BTC", timeframe="hourly", markets_found=5)
        d = r.to_dict()
        assert d["asset"] == "BTC"
        assert d["markets_found"] == 5
        assert "error_details" in d


# ── Collect closed hourlies ──────────────────────────────────────────

class TestCollectClosedHourlies:
    @pytest.mark.asyncio
    async def test_unknown_asset(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)
        result = await collector.collect_closed_hourlies("UNKNOWN")
        assert result.errors == 1
        assert "Unknown asset" in result.error_details[0]

    @pytest.mark.asyncio
    async def test_no_markets_found(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client(markets=[])
        collector = HistoricalCollector(client, archiver)
        result = await collector.collect_closed_hourlies("BTC")
        assert result.markets_found == 0
        assert result.trades_archived == 0

    @pytest.mark.asyncio
    async def test_collects_resolved_markets(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        markets = [_mock_market("KXBTC-H1"), _mock_market("KXBTC-H2")]
        trades = [_mock_trade(ts=1739664000 + i) for i in range(5)]
        client = _mock_client(markets=markets, trades=trades)

        cfg = CollectorConfig(inter_request_delay=0.0)
        collector = HistoricalCollector(client, archiver, config=cfg)
        result = await collector.collect_closed_hourlies("BTC")

        assert result.markets_found == 2
        assert result.markets_processed == 2
        assert result.trades_archived > 0

    @pytest.mark.asyncio
    async def test_handles_trade_fetch_failure(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        markets = [_mock_market("KXBTC-H1")]

        client = _mock_client(markets=markets)
        # Make trade fetch fail
        fail_result = MagicMock()
        fail_result.success = False
        fail_result.error = "timeout"
        client._request_with_resilience = AsyncMock(return_value=fail_result)

        cfg = CollectorConfig(inter_request_delay=0.0)
        collector = HistoricalCollector(client, archiver, config=cfg)
        result = await collector.collect_closed_hourlies("BTC")

        assert result.markets_found == 1
        assert result.trades_archived == 0


# ── Collect all crypto ───────────────────────────────────────────────

class TestCollectAllCrypto:
    @pytest.mark.asyncio
    async def test_collects_multiple_assets(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client(markets=[], trades=[])
        cfg = CollectorConfig(inter_request_delay=0.0)
        collector = HistoricalCollector(client, archiver, config=cfg)

        results = await collector.collect_all_crypto(assets=["BTC", "ETH"])
        assert len(results) == 2
        assert results[0].asset == "BTC"
        assert results[1].asset == "ETH"

    @pytest.mark.asyncio
    async def test_defaults_to_all_assets(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client(markets=[], trades=[])
        cfg = CollectorConfig(inter_request_delay=0.0)
        collector = HistoricalCollector(client, archiver, config=cfg)

        results = await collector.collect_all_crypto()
        assert len(results) == len(CRYPTO_SERIES)


# ── Trade conversion ─────────────────────────────────────────────────

class TestTradeConversion:
    def test_trades_to_snapshots(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)

        raw = [_mock_trade(ts=1000 + i, price=55, size=10) for i in range(3)]
        snaps = collector._trades_to_snapshots(raw, "KXBTC-H1")
        assert len(snaps) == 3
        assert snaps[0].ticker == "KXBTC-H1"
        assert snaps[0].last_trade_price == 55

    def test_trades_to_historical(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)

        raw = [_mock_trade(ts=1000, price=55, size=10, side="buy")]
        hist = collector.trades_to_historical(raw, "KXBTC-H1")
        assert len(hist) == 1
        assert isinstance(hist[0], HistoricalTrade)
        assert hist[0].price == Decimal("0.55")
        assert hist[0].side == "buy"

    def test_malformed_trade_skipped(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)

        raw = [{"bad": "data"}]
        snaps = collector._trades_to_snapshots(raw, "KXBTC-H1")
        # Should not crash, may produce 0 or 1 snapshots depending on defaults
        assert isinstance(snaps, list)


# ── Timestamp parsing ────────────────────────────────────────────────

class TestTimestampParsing:
    def test_epoch_seconds(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)
        ts = collector._parse_ts({"created_time": 1739664000})
        assert ts == 1739664000.0

    def test_epoch_milliseconds(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)
        ts = collector._parse_ts({"created_time": 1739664000000})
        assert abs(ts - 1739664000.0) < 1.0

    def test_iso_string(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)
        ts = collector._parse_ts({"created_time": "2025-02-16T00:00:00Z"})
        assert ts > 0

    def test_fallback_to_now(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        client = _mock_client()
        collector = HistoricalCollector(client, archiver)
        ts = collector._parse_ts({})
        assert ts > 0  # Falls back to time.time()
